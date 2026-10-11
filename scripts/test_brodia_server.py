"""Offline contract test for the selector's private LiveKit session endpoint."""
import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os as _os, tempfile as _tempfile; _os.environ['BRODIA_NEXT_CALL_PATH'] = _os.path.join(_tempfile.mkdtemp(prefix='brodia-test-'), 'next_call.json')  # never touch a real pending P13 selection
from facetime import brodia_server as server


class FakeDispatch:
    def __init__(self): self.requests = []
    async def create_dispatch(self, request): self.requests.append(request)


class FakeLiveKit:
    def __init__(self): self.agent_dispatch = FakeDispatch()
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass


def http_checks(fake, no_keys):
    """/api/session over HTTP: guards, generic 500 on config errors (no detail leak), 201 on success."""
    import contextlib, io, json, threading, urllib.error, urllib.request
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{srv.server_address[1]}/api/session'
    def post(body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        req = urllib.request.Request(url, method='POST', data=data, headers=headers or {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=5) as r: return r.status, r.read().decode()
        except urllib.error.HTTPError as e: return e.code, e.read().decode()
    good = {'scenario': 'park', 'receptivity': 'neutral'}
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for bad in ([], None, 'x', {'scenario': 'club', 'receptivity': 'neutral'}):
                assert post(bad)[0] == 400, bad
            assert post(b'{oops')[0] == 400
            assert post(good, {'Content-Type': 'text/plain'})[0] == 415
            assert post(good, {'Content-Type': 'application/json', 'Host': 'attacker.example:8080'})[0] == 403
            assert post({'scenario': 'park', 'receptivity': 'neutral', 'pad': 'x' * 5000})[0] == 413
            n = len(fake.agent_dispatch.requests)
            server.mint = no_keys; os.environ['LIVEKIT_URL'] = 'wss://example.livekit.cloud'
            code, body = post(good)
            assert code == 500 and 'LIVEKIT' not in body and 'SECRET' not in body and json.loads(body) == {'error': 'Practice server is not configured'}
            assert len(fake.agent_dispatch.requests) == n, 'orphan dispatch over HTTP'
            server.mint = lambda identity, room, ttl_s: 'token'
            code, body = post(good)
            assert code == 201 and json.loads(body)['token'] == 'token' and len(fake.agent_dispatch.requests) == n + 1
    finally:
        srv.shutdown(); srv.server_close()


def main():
    fake = FakeLiveKit()
    original_api, original_mint = server.api.LiveKitAPI, server.mint
    server.api.LiveKitAPI = lambda: fake
    server.mint = lambda identity, room, ttl_s: f'token:{identity}:{room}:{ttl_s}'
    old = dict(os.environ)
    try:
        os.environ.update(LIVEKIT_URL='wss://example.livekit.cloud', AGENT_NAME='brodia')
        result = asyncio.run(server.create_session({'scenario': 'park', 'receptivity': 'neutral'}))
        assert result['room'].startswith('brodia-') and result['token'].endswith(':600')
        request = fake.agent_dispatch.requests[0]
        assert request.agent_name == 'brodia' and request.room == result['room']
        assert '"scenario": "park"' in request.metadata and '"receptivity": "neutral"' in request.metadata
        try: asyncio.run(server.create_session({'scenario': 'invalid', 'receptivity': 'neutral'}))
        except ValueError: pass
        else: raise AssertionError('invalid session configuration was accepted')
        for bad in ([], None, 'x'):
            try: asyncio.run(server.create_session(bad))
            except ValueError: pass
            else: raise AssertionError(f'non-object accepted: {bad!r}')
        # config errors are found BEFORE any dispatch: no orphan agent
        n = len(fake.agent_dispatch.requests)
        def no_keys(*_a, **_k): raise SystemExit('LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set')
        server.mint = no_keys
        try: asyncio.run(server.create_session({'scenario': 'park', 'receptivity': 'neutral'}))
        except server.ServerConfigError: pass
        else: raise AssertionError('missing keys not reported')
        server.mint = lambda identity, room, ttl_s: 'token'
        del os.environ['LIVEKIT_URL']
        try: asyncio.run(server.create_session({'scenario': 'park', 'receptivity': 'neutral'}))
        except server.ServerConfigError: pass
        else: raise AssertionError('missing LIVEKIT_URL not reported')
        assert len(fake.agent_dispatch.requests) == n, 'dispatch created despite a config error'
        http_checks(fake, no_keys)
    finally:
        server.api.LiveKitAPI, server.mint = original_api, original_mint
        os.environ.clear(); os.environ.update(old)
    print('Brodia selector session contract (config before dispatch, HTTP guards, generic 500): PASS')


if __name__ == '__main__': main()
