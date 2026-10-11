"""Small local Brodia selector server: mints a short-lived room token and explicit agent dispatch."""
import asyncio, json, os, secrets
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from livekit import api
from facetime.brodia import RoleplayConfig
from facetime import next_call
from facetime.mint_token import mint

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'


MAX_BODY = 4096


class ServerConfigError(Exception):
    """LiveKit URL/keys missing locally; reported to the browser as a generic 500 without details."""


async def create_session(data):
    if not isinstance(data, dict): raise ValueError('expected a JSON object')
    config = RoleplayConfig(data.get('scenario'), data.get('receptivity'))
    room = 'brodia-' + secrets.token_urlsafe(10).lower()
    try:                                      # config first, so a missing URL/key never leaves an orphan dispatched agent
        url = os.environ['LIVEKIT_URL']; token = mint('brodia-browser', room, ttl_s=600)
    except (KeyError, SystemExit):            # mint() raises SystemExit when the API key/secret are missing
        raise ServerConfigError('LiveKit is not configured') from None
    metadata = json.dumps({'brodia': {'scenario': config.scenario, 'receptivity': config.receptivity}})
    async with api.LiveKitAPI() as lk:
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=os.environ.get('AGENT_NAME', 'brodia'), room=room, metadata=metadata))
    return {'room': room, 'url': url, 'token': token, 'scenario': config.scenario, 'receptivity': config.receptivity}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(WEB), **kwargs)
    def send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def local_host(self):
        """Only this page on this laptop may change state: blocks DNS rebinding (a foreign Host header)."""
        port = self.server.server_address[1]
        return (self.headers.get('Host') or '').strip().lower() in {f'127.0.0.1:{port}', f'localhost:{port}'}
    def read_json_object(self):
        """Guarded JSON body for POSTs: local Host, application/json (forces a CORS preflight cross-site), <= 4 KB, an object.
        Returns the dict, or None after sending the error response."""
        if not self.local_host(): self.send_json(403, {'error': 'forbidden'}); return None
        if (self.headers.get('Content-Type') or '').split(';')[0].strip().lower() != 'application/json':
            self.send_json(415, {'error': 'Content-Type must be application/json'}); return None
        try: n = int(self.headers.get('Content-Length', '0'))
        except ValueError: self.send_json(400, {'error': 'bad Content-Length'}); return None
        if n > MAX_BODY: self.send_json(413, {'error': 'request body too large'}); self.close_connection = True; return None
        try: payload = json.loads(self.rfile.read(n) if n > 0 else b'')
        except ValueError: self.send_json(400, {'error': 'invalid JSON'}); return None
        if not isinstance(payload, dict): self.send_json(400, {'error': 'expected a JSON object'}); return None
        return payload
    def do_GET(self):
        if self.path == '/api/next-call': self.send_json(200, next_call.status()); return
        super().do_GET()
    def do_DELETE(self):
        if self.path != '/api/next-call': self.send_error(404); return
        if not self.local_host(): self.send_json(403, {'error': 'forbidden'}); return
        self.send_json(200, {'cleared': next_call.clear()})
    def do_POST(self):
        if self.path not in ('/api/session', '/api/next-call'): self.send_error(404); return
        payload = self.read_json_object()
        if payload is None: return
        if self.path == '/api/next-call': self.post_next_call(payload); return
        try:
            result = asyncio.run(create_session(payload))
        except ValueError as e:
            self.send_json(400, {'error': str(e)}); return
        except ServerConfigError:
            print('[selector] /api/session: LiveKit URL/API key not configured (check .env.local)', flush=True)
            self.send_json(500, {'error': 'Practice server is not configured'}); return
        except Exception as e:
            print(f'[selector] /api/session dispatch failed: {type(e).__name__}', flush=True)
            self.send_json(502, {'error': 'Unable to start practice session'}); return
        self.send_json(201, result)
    def post_next_call(self, payload):
        """P13 demo-only: store ONE pending selection for the next Chert FaceTime caller (facetime/next_call.py)."""
        try:
            record = next_call.store(payload.get('scenario'), payload.get('receptivity'))
        except ValueError as e:
            self.send_json(400, {'error': str(e)}); return
        print(f"[selector] next-call selection {record['id']}: {record['scenario']} + {record['receptivity']} "
              f"(demo-only, expires in {record['expires_at'] - record['created_at']:.0f} s)", flush=True)
        self.send_json(201, {'pending': True, 'id': record['id'], 'scenario': record['scenario'], 'receptivity': record['receptivity'],
                             'expires_in': round(record['expires_at'] - record['created_at'], 1)})


def main():
    port = int(os.environ.get('BRODIA_WEB_PORT', '8080'))
    print(f'Brodia selector: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()

if __name__ == '__main__': main()
