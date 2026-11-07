"""HTTP SLA endpoints only inside the owned peer namespace."""
import http.server
import signal
import threading


def main():
    stopped=threading.Event();signal.signal(signal.SIGINT,lambda *args:stopped.set());signal.signal(signal.SIGTERM,lambda *args:stopped.set())
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'healthy\n')
        def log_message(self,*args):pass
    servers=[]
    try:
        for port in (28081,28082,28083):
            server=http.server.ThreadingHTTPServer(('0.0.0.0',port),Handler);server.daemon_threads=True;servers.append(server)
            threading.Thread(target=server.serve_forever,daemon=True).start()
        print('ready',flush=True);stopped.wait()
    finally:
        for server in servers:server.shutdown();server.server_close()

if __name__=='__main__':main()
