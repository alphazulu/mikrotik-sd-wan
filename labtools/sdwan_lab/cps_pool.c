#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define MAX_SOURCES 512
#define MAX_LISTENERS 512
#define MAX_ACTIVE 256
#define MAX_SECONDS 1200
#define FRESH_PER_DESTINATION 20000
static volatile sig_atomic_t stopping;
static void stop_now(int signo) { (void)signo; stopping = 1; }
static double now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) exit(2);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static uint64_t number(const char *text, uint64_t low, uint64_t high) {
    char *end;
    errno = 0;
    unsigned long long value = strtoull(text, &end, 10);
    if (!*text || *text == '-' || *end || errno || value < low || value > high) {
        fprintf(stderr, "invalid numeric argument\n"); exit(2);
    }
    return value;
}
static struct in_addr ipv4(const char *text) {
    struct in_addr addr;
    if (inet_pton(AF_INET, text, &addr) != 1) { fputs("invalid IPv4\n", stderr); exit(2); }
    return addr;
}
static int nonblocking_socket(void) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    int flags = fcntl(fd, F_GETFL);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK)) { close(fd); return -1; }
    return fd;
}
struct slot {
    int fd, state;
    unsigned char sent[32], received[32];
    size_t tx, rx;
    double created;
};
struct counts {
    unsigned attempts, connected, completed, errors, measured, active, peak;
    unsigned per_second[MAX_SECONDS];
    int last_errno;
    double start, maximum_lateness;
};
static void client_finish(struct slot *slot, struct counts *c, int success, unsigned warmup, unsigned duration) {
    if (success) {
        c->completed++;
        double elapsed = now() - c->start;
        if (elapsed >= warmup && elapsed < warmup + duration) c->measured++;
        if (elapsed >= 0 && elapsed < MAX_SECONDS) c->per_second[(unsigned)elapsed]++;
    } else { c->errors++; c->last_errno = errno; }
    close(slot->fd); slot->fd = -1; c->active--;
}
static int server(struct in_addr host, unsigned base, unsigned listeners) {
    int sockets[MAX_LISTENERS];
    struct slot slots[MAX_ACTIVE];
    for (unsigned i = 0; i < MAX_ACTIVE; i++) slots[i].fd = -1;
    for (unsigned i = 0; i < listeners; i++) {
        sockets[i] = nonblocking_socket(); int one = 1;
        struct sockaddr_in addr = {.sin_family=AF_INET, .sin_port=htons(base+i), .sin_addr=host};
        if (sockets[i] < 0 || setsockopt(sockets[i], SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) ||
            bind(sockets[i], (void *)&addr, sizeof(addr)) || listen(sockets[i], 256)) {
            perror("listen"); return 2;
        }
    }
    unsigned accepted=0, completed=0, errors=0, active=0, peak=0;
    double drain_until = 0;
    printf("ready %u ports\n", listeners); fflush(stdout);
    while (!stopping || active) {
        double stamp = now();
        if (stopping && !drain_until) drain_until = stamp + 2;
        for (unsigned i=0; i<MAX_ACTIVE; i++) if (slots[i].fd >= 0 &&
                (stamp-slots[i].created >= 3 || (stopping && stamp >= drain_until))) {
            close(slots[i].fd); slots[i].fd=-1; active--; errors++;
        }
        if (stopping && !active) break;
        struct pollfd fds[MAX_LISTENERS+MAX_ACTIVE]; unsigned indices[MAX_LISTENERS+MAX_ACTIVE], n=0;
        if (!stopping) for (unsigned i=0; i<listeners; i++) {
            fds[n]=(struct pollfd){.fd=sockets[i], .events=POLLIN}; indices[n++]=MAX_ACTIVE+i;
        }
        for (unsigned i=0; i<MAX_ACTIVE; i++) if (slots[i].fd >= 0) {
            fds[n]=(struct pollfd){.fd=slots[i].fd, .events=slots[i].state==2 ? POLLOUT : POLLIN}; indices[n++]=i;
        }
        if (poll(fds, n, 20)<0) { if (errno==EINTR) continue; return 2; }
        for (unsigned j=0; j<n; j++) {
            if (!fds[j].revents) continue;
            if (indices[j]>=MAX_ACTIVE) {
                for (;;) {
                    int fd=accept(fds[j].fd, NULL, NULL);
                    if (fd<0) { if (errno==EINTR) continue; if (errno==EAGAIN || errno==EWOULDBLOCK) break; return 2; }
                    accepted++; unsigned i=0;
                    while (i<MAX_ACTIVE && slots[i].fd>=0) i++;
                    int flags=fcntl(fd,F_GETFL);
                    if (i==MAX_ACTIVE || flags<0 || fcntl(fd,F_SETFL,flags|O_NONBLOCK)) { close(fd); errors++; continue; }
                    memset(&slots[i],0,sizeof(slots[i])); slots[i].fd=fd;slots[i].state=1;slots[i].created=now();
                    active++; if (active>peak) peak=active;
                }
                continue;
            }
            struct slot *s=&slots[indices[j]]; int failed=0, finished=0;
            if (fds[j].revents & (POLLERR|POLLNVAL)) failed=1;
            if (!failed && s->state==1 && (fds[j].revents & (POLLIN|POLLHUP))) {
                ssize_t bytes=recv(s->fd,s->received+s->rx,sizeof(s->received)-s->rx,0);
                if (bytes>0) { s->rx+=(size_t)bytes; if (s->rx==sizeof(s->received)) s->state=2; }
                else if (!bytes || (errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)) failed=1;
            }
            if (!failed && s->state==2) {
                ssize_t bytes=send(s->fd,s->received+s->tx,sizeof(s->received)-s->tx,MSG_NOSIGNAL);
                if (bytes>0) { s->tx+=(size_t)bytes; if (s->tx==sizeof(s->received)) s->state=3; }
                else if (bytes<0 && errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR) failed=1;
            }
            /* Let the client actively close. Server TIME_WAIT must not become
               a hidden ceiling behind a DUT that performs source NAT. */
            if (!failed && s->state==3 && (fds[j].revents & (POLLIN|POLLHUP))) {
                unsigned char extra;ssize_t bytes=recv(s->fd,&extra,1,0);
                if (!bytes) finished=1;
                else if (bytes>0 || (errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)) failed=1;
            }
            if (failed || finished) { close(s->fd);s->fd=-1;active--;if (finished) completed++;else errors++; }
        }
    }
    for (unsigned i=0;i<listeners;i++) close(sockets[i]);
    printf("{\"accepted\":%u,\"completed\":%u,\"errors\":%u,\"active\":%u,\"peak_active\":%u}\n",accepted,completed,errors,active,peak);
    return 0;
}
static int client(struct in_addr host,unsigned base,unsigned destinations,unsigned rate,unsigned warmup,
                  unsigned duration,unsigned concurrency,char *source_list,unsigned port_low,unsigned port_high,uint64_t offset) {
    struct in_addr sources[MAX_SOURCES];unsigned source_count=0;char *save;
    for (char *word=strtok_r(source_list,",",&save);word;word=strtok_r(NULL,",",&save)) {
        if (source_count==MAX_SOURCES) return 2;
        sources[source_count]=ipv4(word);
        for (unsigned i=0;i<source_count;i++) if (sources[i].s_addr==sources[source_count].s_addr) return 2;
        source_count++;
    }
    uint64_t total=(uint64_t)rate*(warmup+duration), budget=(uint64_t)source_count*(port_high-port_low+1);
    if (!source_count || offset+total>budget || (total+destinations-1)/destinations>FRESH_PER_DESTINATION) {
        fputs("fresh source tuple or destination port budget exceeded\n",stderr);return 2;
    }
    struct counts c={.start=now()};struct slot slots[MAX_ACTIVE];
    for (unsigned i=0;i<concurrency;i++) slots[i].fd=-1;
    while (!stopping && (c.attempts<total || c.active)) {
        double stamp=now();
        for (unsigned i=0;i<concurrency;i++) if (slots[i].fd>=0 && stamp-slots[i].created>=3) {
            errno=ETIMEDOUT;client_finish(&slots[i],&c,0,warmup,duration);
        }
        while (c.attempts<total && c.active<concurrency && now()>=c.start+c.attempts/(double)rate) {
            unsigned index=0;while (index<concurrency && slots[index].fd>=0) index++;
            if (index==concurrency) return 2;
            double late=now()-(c.start+c.attempts/(double)rate);if (late>c.maximum_lateness)c.maximum_lateness=late;
            uint64_t tuple=offset+c.attempts;unsigned port=port_low+(unsigned)(tuple/source_count);
            struct sockaddr_in local={.sin_family=AF_INET,.sin_port=htons(port),.sin_addr=sources[tuple%source_count]};
            struct sockaddr_in peer={.sin_family=AF_INET,.sin_port=htons(base+c.attempts%destinations),.sin_addr=host};
            struct slot *s=&slots[index];memset(s,0,sizeof(*s));memcpy(s->sent,&tuple,sizeof(tuple));c.attempts++;
            s->created=now();s->fd=nonblocking_socket();
            if (s->fd<0) { c.errors++;c.last_errno=errno;continue; }
            c.active++;if(c.active>c.peak)c.peak=c.active;
            if (bind(s->fd,(void *)&local,sizeof(local))) { client_finish(s,&c,0,warmup,duration);continue; }
            if (!connect(s->fd,(void *)&peer,sizeof(peer))) { c.connected++;s->state=1; }
            else if (errno!=EINPROGRESS)client_finish(s,&c,0,warmup,duration);
        }
        struct pollfd fds[MAX_ACTIVE];unsigned indices[MAX_ACTIVE],n=0;
        for (unsigned i=0;i<concurrency;i++) if (slots[i].fd>=0) {
            fds[n]=(struct pollfd){.fd=slots[i].fd,.events=slots[i].state==2?POLLIN:POLLOUT};indices[n++]=i;
        }
        int delay=10;
        if(c.attempts<total && c.active<concurrency) { double d=c.start+c.attempts/(double)rate-now();delay=d<=0?0:(int)(d*1000)+1; }
        if(poll(fds,n,delay)<0) { if(errno==EINTR)continue;return 2; }
        for(unsigned j=0;j<n;j++) {
            if(!fds[j].revents)continue;
            struct slot *s=&slots[indices[j]];
            if(fds[j].revents&POLLNVAL) { errno=EBADF;client_finish(s,&c,0,warmup,duration);continue; }
            if(s->state==0 || (fds[j].revents&POLLERR)) {
                int error=0;socklen_t len=sizeof(error);
                if(getsockopt(s->fd,SOL_SOCKET,SO_ERROR,&error,&len)||error) { if(error)errno=error;client_finish(s,&c,0,warmup,duration);continue; }
                if(s->state==0) {c.connected++;s->state=1;}
            }
            if(s->state==1) {
                ssize_t bytes=send(s->fd,s->sent+s->tx,sizeof(s->sent)-s->tx,MSG_NOSIGNAL);
                if(bytes>0) {s->tx+=(size_t)bytes;if(s->tx==sizeof(s->sent))s->state=2;}
                else if(bytes<0 && errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR) {client_finish(s,&c,0,warmup,duration);continue;}
            }
            if(s->state==2 && (fds[j].revents&(POLLIN|POLLHUP))) {
                ssize_t bytes=recv(s->fd,s->received+s->rx,sizeof(s->received)-s->rx,0);
                if(bytes>0) {
                    s->rx+=(size_t)bytes;
                    if(s->rx==sizeof(s->received)) {int valid=!memcmp(s->sent,s->received,sizeof(s->sent));if(!valid)errno=EBADMSG;client_finish(s,&c,valid,warmup,duration);}
                } else if(!bytes || (errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)) {if(!bytes)errno=ECONNRESET;client_finish(s,&c,0,warmup,duration);}
            }
        }
    }
    for(unsigned i=0;i<concurrency;i++)if(slots[i].fd>=0) {errno=ECANCELED;client_finish(&slots[i],&c,0,warmup,duration);}
    struct rusage usage;getrusage(RUSAGE_SELF,&usage);
    printf("{\"attempts\":%u,\"planned_attempts\":%" PRIu64 ",\"connected\":%u,\"echo_success\":%u,\"error_count\":%u,\"last_errno\":%d,\"peak_active\":%u,\"concurrency_limit\":%u,\"offered_cps\":%u,\"measured_successes\":%u,\"successful_cps\":%.6f,\"maximum_schedule_lateness_seconds\":%.9f,\"origin_monotonic_seconds\":%.9f,\"duration_seconds\":%.6f,\"user_cpu_seconds\":%.6f,\"system_cpu_seconds\":%.6f,\"source_count\":%u,\"tuple_offset\":%" PRIu64 ",\"next_tuple_offset\":%" PRIu64 ",\"destination_port_base\":%u,\"destination_port_count\":%u,\"client_active_close\":true,\"interrupted\":%s,\"completion_counts_per_second\":[",
           c.attempts,total,c.connected,c.completed,c.errors,c.last_errno,c.peak,concurrency,rate,c.measured,c.measured/(double)duration,c.maximum_lateness,c.start,now()-c.start,
           usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6,usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6,source_count,offset,offset+c.attempts,base,destinations,stopping?"true":"false");
    for(unsigned i=0;i<warmup+duration;i++)printf("%s%u",i?",":"",c.per_second[i]);
    puts("]}");
    return 0;
}
int main(int argc,char **argv) {
    struct sigaction action={.sa_handler=stop_now};sigemptyset(&action.sa_mask);
    sigaction(SIGINT,&action,NULL);sigaction(SIGTERM,&action,NULL);
    if(argc==5 && !strcmp(argv[1],"server")) {
        unsigned base=number(argv[3],1024,65535),count=number(argv[4],1,MAX_LISTENERS);
        if(base+count-1>65535)return 2;
        return server(ipv4(argv[2]),base,count);
    }
    if(argc!=13 || strcmp(argv[1],"client"))return 2;
    unsigned base=number(argv[3],1024,65535),destinations=number(argv[4],1,MAX_LISTENERS);
    unsigned rate=number(argv[5],1,20000),warmup=number(argv[6],0,600),duration=number(argv[7],1,600),concurrency=number(argv[8],1,MAX_ACTIVE);
    unsigned low=number(argv[10],1024,65535),high=number(argv[11],low,65535);uint64_t offset=number(argv[12],0,40000000);
    if(base+destinations-1>65535 || (uint64_t)rate*(warmup+duration)>10000000)return 2;
    return client(ipv4(argv[2]),base,destinations,rate,warmup,duration,concurrency,argv[9],low,high,offset);
}
