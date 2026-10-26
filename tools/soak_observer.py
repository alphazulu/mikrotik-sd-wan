"""Pure host-side acceptance rules; never controls a router's WAN selection."""
import copy
import json


def expected_selection(cfg, frame):
    """Use the controller's coherent SLA states and frozen policy order."""
    assert not frame.get('error'), 'controller error in status frame'
    assert frame.get('revision') == cfg['revision'], 'status configuration revision differs'
    states = frame.get('states', {})
    samples = frame.get('samples', {})
    maintenance = frame.get('maintenance', {})
    wans = {w['name']: w for w in cfg['wans']}
    choices = {}
    for policy in cfg['policies']:
        eligible = []
        for name in policy['wans']:
            key = policy['profile'] + '/' + name
            assert key in states and name in samples and name in maintenance, 'missing WAN state/sample/admission: ' + key
            detail = states[key]
            assert detail.get('state') in ('healthy', 'degraded', 'down', 'recovering', 'unknown'), 'unknown SLA state: ' + key
            admit = maintenance[name].get('admit')
            assert type(admit) is bool, 'missing boolean admission: ' + name
            if wans[name].get('admin_state', 'enabled') != 'enabled':
                assert admit is False, 'maintenance WAN incorrectly admits traffic'
            # Stale raw probes may precede a confirmed state transition while
            # fail_windows hysteresis runs. Do not invent a stricter selector.
            assert type(samples[name].get('stale')) is bool, 'missing probe freshness: ' + key
            if admit:
                eligible.append((name, detail['state']))
        levels = ('healthy', 'degraded') if policy['allow_degraded'] else ('healthy',)
        choices[policy['name']] = next((name for level in levels for name, quality in eligible if quality == level), 'none')
    return choices


class EventCursor:
    """Detect both missed events and out-and-back transitions between polls."""
    def __init__(self, frame, cfg):
        self.cfg = cfg
        self.qualities = copy.deepcopy(frame["states"])
        self.selected = dict(frame['selected'])
        self.seq = max((e['seq'] for e in frame.get('events', [])), default=0)
        self.uptime = frame['uptime_seconds']
        self.revision = frame['revision']

    def advance(self, frame, expected):
        assert frame['revision'] == self.revision, 'configuration changed during observation'
        assert frame['uptime_seconds'] >= self.uptime, 'router rebooted or status regressed'
        events = frame.get('events', [])
        numbers = [e['seq'] for e in events]
        assert numbers == sorted(set(numbers)), 'event sequence duplicated or reordered'
        fresh = [e for e in events if e['seq'] > self.seq]
        if fresh:
            assert fresh[0]['seq'] == self.seq + 1, 'event history gap; transitions unproven'
            assert [e['seq'] for e in fresh] == list(range(self.seq + 1, fresh[-1]['seq'] + 1)), 'event history gap'
        selected = dict(self.selected)
        transitions = []
        for event in fresh:
            assert event.get('revision') == self.revision, 'event belongs to another configuration'
            if event['type'] == 'link':
                for key in self.qualities:
                    if key.endswith('/' + event['wan']):
                        self.qualities[key]['state'] = 'unknown'
            if event['type'] == 'state':
                key = event['policy']
                assert key in self.qualities and event['from'] == self.qualities[key]['state'], 'SLA event chain is broken'
                self.qualities[key]['state'] = event['to']
            if event['type'] == 'policy':
                policy = event['policy']
                assert policy in selected and event['from'] == selected[policy], 'policy transition chain is broken'
                assert event['to'] != event['from'], 'empty policy transition'
                replay = dict(frame, states=self.qualities)
                assert expected_selection(self.cfg, replay)[policy] == event['to'], 'policy event is not justified by its SLA history'
                selected[policy] = event['to']
                transitions.append(dict(event))
        assert {k:v['state'] for k,v in self.qualities.items()} == {k:v['state'] for k,v in frame['states'].items()}, 'SLA changed without recorded evidence'
        assert selected == frame['selected'], 'selection changed without a complete event chain'
        assert frame['selected'] == expected, 'selection does not follow configured SLA/priority/admission'
        self.selected = selected
        self.seq = fresh[-1]['seq'] if fresh else self.seq
        self.uptime = frame['uptime_seconds']
        return transitions


def validate_intent(old_text, new_text, cfg, frame, transitions=(), backend_start=False):
    """Persistent intent may change only for a proved plan/ownership transition."""
    if old_text == new_text:
        return None
    assert backend_start or transitions, 'steady controller rewrote persistent intent'
    old = json.loads(old_text) if old_text.strip() else {}
    new = json.loads(new_text)
    assert new.get('revision') == cfg['revision'], 'intent revision differs'
    assert new.get('protocol') == 1 and new.get('release') is False, 'invalid or released intent'
    # Field schema is checked against the controller's accepted fenced lease,
    # not against a host-generated desired plan.
    accepted = frame.get('container', {})
    assert accepted.get('active') is True, 'changed intent has no accepted active lease'
    assert new.get('instance') == accepted.get('owner_instance'), 'intent owner differs from accepted lease'
    assert new.get('boot_id') == accepted.get('boot_id') and new.get('generation') == accepted.get('generation'), 'intent fence differs from accepted lease'
    assert accepted.get('lease_remaining_seconds', 0) > 0, 'intent lease is not live'
    assert type(new.get('observed_uptime')) is int and 0 <= frame['uptime_seconds'] - new['observed_uptime'] <= 12, 'intent observation is stale'
    assert type(new.get('seq')) is int and new['seq'] > 0, 'missing intent sequence'
    assert new.get('selected') == frame['selected'], 'intent plan differs from observed selection'
    if not backend_start:
        assert new.get('instance') == old.get('instance'), 'unobserved controller instance change'
        assert new['seq'] > old.get('seq', -1), 'intent sequence did not advance'
    return {'changed_fields': sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k)),
            'sequence_before': old.get('seq'), 'sequence_after': new['seq']}


class FlowObserver:
    """Recreate only proved retired test flows; untouched streams stay original."""
    def __init__(self, streams, policies, now, retained, old_path):
        self.streams = streams
        self.policies = policies
        self.retained = retained
        self.old_path = old_path
        self.pending = {}
        self.transitions = []
        self.last_progress = {label: now for label in streams}
        self.last_bytes = {label: int(flow.snapshot['repl-bytes']) for label,flow in streams.items()}

    def tick(self, state, events, rows, now, traffic):
        for label, policy in self.policies.items():
            relevant = [e for e in events if e['policy'] == policy]
            if not relevant:
                continue
            assert label not in self.pending or self.pending[label]['stage'] == 'closed', 'Selection changed during unverified reconnection; evidence is inconclusive'
            flow = self.streams[label]
            self.pending[label] = {'stage':'retiring', 'old':flow, 'target':state['selected'][policy], 'started':now,
                                   'event_seq':[e['seq'] for e in relevant], 'old_tuple':dict(flow.snapshot), 'policy':policy}
        for label, flow in list(self.streams.items()):
            pending = self.pending.get(label)
            if pending:
                if pending['stage'] == 'retiring':
                    if any(self.old_path(pending['old'], row) for row in rows):
                        assert now - pending['started'] <= 6, label + ': old marked connection was not retired'
                        continue
                    pending['retired_seconds'] = now - pending['started']
                    if pending['target'] == 'none':
                        traffic.stop_stream(pending['old'])
                        pending['stage'] = 'closed'
                        continue
                    mark = 'sdwan-out-' + pending['policy'] + ':' + pending['target']
                    traffic.restart_stream(pending['old'], mark, timeout=None)
                    pending.update(stage='reconnecting', mark=mark, launched=now)
                    continue
                if pending['stage'] == 'closed':
                    assert state['selected'][pending['policy']] == 'none', 'Closed stream needs an observed admission event'
                    continue
                assert now - pending['launched'] <= 25, label + ': replacement transfer did not recover'
                replacement = traffic.find_stream(flow.port, pending['mark'], rows)
                if replacement is None:
                    continue
                assert replacement.http['generation'] > pending['old'].http['generation'], 'HTTP generation was not advanced'
                self.streams[label] = replacement
                self.last_bytes[label] = int(replacement.snapshot['repl-bytes'])
                self.last_progress[label] = now
                self.transitions.append({key:value for key,value in pending.items() if key != 'old'} |
                                        {'label':label, 'recovery_seconds':now-pending['started'], 'new_tuple':dict(replacement.snapshot),
                                         'http_generation':replacement.http['generation']})
                del self.pending[label]
                continue
            row = self.retained(flow.last, rows)
            flow.last = dict(row)
            stats = flow.http
            assert stats['requests'] == 1 and stats['active'] == 1 and stats['error'] is None, label + ': original HTTP transfer closed or restarted'
            count = int(row['repl-bytes'])
            if count > self.last_bytes[label]:
                self.last_progress[label] = now
            assert now-self.last_progress[label] <= 12, label + ': original TCP stream stalled'
            self.last_bytes[label] = count

    def summary(self):
        return {'pending': {label:{k:v for k,v in item.items() if k != 'old'} for label,item in self.pending.items()},
                'transitions':self.transitions, 'reply_bytes':dict(self.last_bytes)}
