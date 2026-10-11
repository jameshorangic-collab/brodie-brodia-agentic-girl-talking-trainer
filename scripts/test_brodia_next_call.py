"""Offline P13 test: the DEMO-ONLY "next FaceTime call" selection (store, TTL, one-time consume, worker priority, HTTP)."""
import json
import multiprocessing
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facetime import next_call, worker


def fresh_args(*flags):
    return worker.resolve_mode(worker.build_parser().parse_args(['--voice', 'off', '--agent-name', 'brodia', *flags]))


def _race(path, q):
    record, _ = next_call.consume(path)
    q.put(None if record is None else record['id'])


def main():
    tmp = tempfile.mkdtemp(prefix='brodia-next-call-')
    path = os.path.join(tmp, 'sub', 'next.json')
    os.environ['BRODIA_NEXT_CALL_PATH'] = path
    os.environ.pop('BRODIA_NEXT_CALL_ANY_JOB', None); os.environ.pop('BRODIA_NEXT_CALL', None)

    # store / status / replacement / one-time consumption
    assert next_call.status() == {'pending': False}
    first = next_call.store('barista', 'interested', ttl=120)
    st = next_call.status(); assert st['pending'] and st['scenario'] == 'barista' and 0 < st['expires_in'] <= 120
    second = next_call.store('street', 'uninterested', ttl=120)
    record, why = next_call.consume()
    assert record['id'] == second['id'] != first['id'] and record['config'].scenario == 'street', 'replacement failed'
    assert 'consumed' in why and not os.path.exists(path)
    assert next_call.consume() == (None, 'no pending selection'), 'selection reused'
    assert next_call.status() == {'pending': False}
    assert [f for f in os.listdir(os.path.dirname(path))] == [], 'temp/claim files left behind'
    print('store, replace, one-time consume: PASS')

    # TTL expiry
    next_call.store('park', 'neutral', ttl=10, now=1000.0)
    assert next_call.status(now=1009.0)['pending'] and not next_call.status(now=1010.5)['pending']
    record, why = next_call.consume(now=1011.0)
    assert record is None and 'expired' in why and not os.path.exists(path)
    os.environ['BRODIA_NEXT_CALL_TTL_S'] = '30'; assert next_call.ttl_s() == 30
    os.environ['BRODIA_NEXT_CALL_TTL_S'] = 'junk'; assert next_call.ttl_s() == next_call.DEFAULT_TTL_S
    del os.environ['BRODIA_NEXT_CALL_TTL_S']
    print('TTL expiry and env TTL: PASS')

    # invalid selections are rejected and never stored
    for bad in (('club', 'neutral'), ('park', 'eager'), (None, None)):
        try: next_call.store(*bad)
        except ValueError: pass
        else: raise AssertionError(f'invalid selection stored: {bad}')
    assert not os.path.exists(path)
    Path(path).write_text('{"id": "x", "scenario": "club", "receptivity": "neutral", "created_at": 0, "expires_at": 9e12}')
    record, why = next_call.consume(); assert record is None and 'invalid' in why
    Path(path).write_text('{not json'); record, why = next_call.consume(); assert record is None and 'unreadable' in why
    print('invalid selections rejected: PASS')

    # worker priority: warm never consumes, explicit browser metadata wins, Chert caller consumes once,
    # and a brodia agent never falls back to the fitness coach (default Brodia persona instead)
    cfg = lambda a: (a.brodia_scenario, a.brodia_receptivity)
    default = worker.DEFAULT_BRODIA
    next_call.store('street', 'neutral', ttl=120)
    a, src = worker.select_brodia(fresh_args(), {'chert_warm': True})
    assert cfg(a) == default and 'warm' in src and next_call.status()['pending'], 'warm job consumed the selection'
    a, src = worker.select_brodia(fresh_args(), {'chert_call': 'x', 'brodia': {'scenario': 'barista', 'receptivity': 'interested'}})
    assert cfg(a) == ('barista', 'interested') and src == 'browser dispatch metadata'
    assert next_call.status()['pending'], 'explicit dispatch consumed the selection'
    a, src = worker.select_brodia(fresh_args('--brodia-scenario', 'park', '--brodia-receptivity', 'uninterested'), {'brodia': {'scenario': 'barista', 'receptivity': 'neutral'}})
    assert cfg(a) == ('barista', 'neutral'), 'explicit metadata must win over flags'
    a, src = worker.select_brodia(fresh_args(), {})
    assert cfg(a) == default and next_call.status()['pending'], 'non-Chert job consumed the selection'
    a, src = worker.select_brodia(fresh_args('--brodia-scenario', 'park', '--brodia-receptivity', 'interested'), {'chert_call': 'call-1'})
    assert cfg(a) == ('street', 'neutral') and 'next-call selection' in src
    assert a.perception == 'off' and a.handlers == 'none' and a.plan is None and worker.brodia_persona(a)
    a, src = worker.select_brodia(fresh_args('--brodia-scenario', 'park', '--brodia-receptivity', 'interested'), {'chert_call': 'call-2'})
    assert cfg(a) == ('park', 'interested') and src.startswith('worker flags') and 'no pending' in src
    a, src = worker.select_brodia(fresh_args(), {'chert_call': 'call-3'})
    assert cfg(a) == default and src.startswith('Brodia default') and a.plan is None and a.plan_text is None and a.handlers == 'none'
    # the issue's sequence: Barista+Interested for one call, Street+Uninterested for the next, no leakage
    for scen, rec, call in (('barista', 'interested', 'A'), ('street', 'uninterested', 'B')):
        next_call.store(scen, rec, ttl=120)
        a, _ = worker.select_brodia(fresh_args(), {'chert_call': call})
        assert cfg(a) == (scen, rec)
    a, _ = worker.select_brodia(fresh_args(), {'chert_call': 'C'}); assert cfg(a) == default, 'stale selection leaked'
    next_call.store('street', 'interested', ttl=120)
    os.environ['BRODIA_NEXT_CALL'] = '0'
    a, _ = worker.select_brodia(fresh_args(), {'chert_call': 'x'}); assert cfg(a) == default and next_call.status()['pending']
    del os.environ['BRODIA_NEXT_CALL']
    os.environ['BRODIA_NEXT_CALL_ANY_JOB'] = '1'
    a, _ = worker.select_brodia(fresh_args(), {'chert_warm': True}); assert cfg(a) == default, 'warm consumed with ANY_JOB'
    a, _ = worker.select_brodia(fresh_args(), {}); assert cfg(a) == ('street', 'interested'), 'ANY_JOB escape hatch'
    del os.environ['BRODIA_NEXT_CALL_ANY_JOB']
    # invalid explicit metadata: logged and ignored, never a crash; falls through to next-call / default
    for bad in ('x', None, [], 7, {'scenario': 'club', 'receptivity': 'neutral'}, {'scenario': 'park'}):
        a, src = worker.select_brodia(fresh_args(), {'brodia': bad}); assert cfg(a) == default, bad
        assert worker.dispatch_config({'brodia': bad}) is None
        a = worker.apply_brodia_dispatch(fresh_args(), {'brodia': bad}); assert cfg(a) == default, bad
    next_call.store('barista', 'uninterested', ttl=120)
    a, src = worker.select_brodia(fresh_args(), {'chert_call': 'x', 'brodia': 'x'}); assert cfg(a) == ('barista', 'uninterested')
    a, src = worker.select_brodia(fresh_args(), 'not-a-dict'); assert cfg(a) == default
    # a non-brodia agent (local starter rooms: --agent-name "") keeps the starter coach unless configured
    a, src = worker.select_brodia(fresh_args('--agent-name', ''), {}); assert a.brodia_scenario is None and src.startswith('starter coach')
    # tests never use the real data/tmp path, even without BRODIA_NEXT_CALL_PATH
    saved = os.environ.pop('BRODIA_NEXT_CALL_PATH')
    assert 'data/tmp' not in str(next_call.state_path()) and 'brodia-test-' in str(next_call.state_path())
    os.environ['BRODIA_NEXT_CALL_PATH'] = saved
    print('worker: warm skip, explicit metadata wins, consume once, flags/default fallback (never fitness), invalid metadata safe, no leakage: PASS')

    # concurrency: many processes race to consume one selection -> exactly one wins
    ctx = multiprocessing.get_context('fork')
    for _ in range(5):
        rec = next_call.store('barista', 'neutral', ttl=120); q = ctx.Queue()
        procs = [ctx.Process(target=_race, args=(path, q)) for _ in range(8)]
        for p in procs: p.start()
        for p in procs: p.join(10)
        winners = [x for x in (q.get(timeout=5) for _ in procs) if x]
        assert winners == [rec['id']], f'expected exactly one consumer, got {winners}'
    # atomic write: concurrent writers never expose a partial file to readers
    stop = threading.Event(); bad = []
    def writer():
        while not stop.is_set(): next_call.store('park', 'interested', ttl=120)
    def reader():
        while not stop.is_set():
            try: json.loads(Path(path).read_text())
            except FileNotFoundError: pass
            except ValueError: bad.append(1)
    threads = [threading.Thread(target=writer) for _ in range(3)] + [threading.Thread(target=reader) for _ in range(3)]
    for t in threads: t.start()
    threading.Event().wait(0.5); stop.set()
    for t in threads: t.join()
    assert not bad, f'{len(bad)} partial reads'
    next_call.clear()
    print('concurrency: one winner of 8 racing consumers x5, no partial reads: PASS')

    # HTTP: POST/GET/DELETE /api/next-call on the real handler (no LiveKit needed)
    from facetime import brodia_server
    srv = ThreadingHTTPServer(('127.0.0.1', 0), brodia_server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_address[1]}/api/next-call'
    def call(method, body=None):
        req = urllib.request.Request(base, method=method, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e: return e.code, None
    try:
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert call('GET') == (200, {'pending': False})
            code, body = call('POST', {'scenario': 'park', 'receptivity': 'neutral'})
            assert code == 201 and body['pending'] and body['scenario'] == 'park' and 0 < body['expires_in'] <= 120
            code, body = call('GET'); assert code == 200 and body['pending'] and set(body) == {'pending', 'id', 'scenario', 'receptivity', 'expires_in'}
            assert call('POST', {'scenario': 'club', 'receptivity': 'neutral'})[0] == 400
            assert call('POST', ['park'])[0] == 400
            assert call('GET')[1]['scenario'] == 'park', 'invalid POST replaced the pending selection'
            assert call('DELETE') == (200, {'cleared': True}) and call('GET') == (200, {'pending': False})
            for body in ([], None, 'x', 3):
                assert call('POST', body)[0] == 400, body
            def raw(headers, data=b'{"scenario": "park", "receptivity": "neutral"}', method='POST'):
                req = urllib.request.Request(base, method=method, data=data, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=5) as r: return r.status
                except urllib.error.HTTPError as e: return e.code
            assert raw({'Content-Type': 'text/plain'}) == 415
            assert raw({'Content-Type': 'application/x-www-form-urlencoded'}) == 415
            assert raw({'Content-Type': 'application/json', 'Host': 'evil.example:8080'}) == 403
            assert raw({'Content-Type': 'application/json', 'Host': 'evil.example:8080'}, data=None, method='DELETE') == 403
            assert raw({'Content-Type': 'application/json'}, data=b'{"a": "' + b'x' * 5000 + b'"}') == 413
            assert raw({'Content-Type': 'application/json; charset=utf-8'}) == 201
            assert raw({'Content-Type': 'application/json', 'Host': f'localhost:{srv.server_address[1]}'}) == 201
            assert call('GET')[1]['pending']; call('DELETE')
    finally:
        srv.shutdown(); srv.server_close()
    print('HTTP /api/next-call POST/GET/DELETE; invalid/non-object -> 400, bad Host 403, bad type 415, >4 KB 413: PASS')
    print('Brodia next-call (P13 demo-only fallback): PASS')


if __name__ == '__main__': main()
