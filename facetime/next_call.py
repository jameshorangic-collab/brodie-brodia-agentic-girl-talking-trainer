"""P13 DEMO-ONLY fallback: one pending "next FaceTime call" Brodia selection, shared by file.

Chert's shared line gives a web page no way to bind a selection to a specific inbound caller
(docs/FACETIME_VIDEO_FEASIBILITY.md). So the selector server (facetime/brodia_server.py) writes ONE
pending selection with a short TTL to a local file, and the worker (facetime/worker.py) consumes it,
once, for the first real Chert caller job. One caller at a time; not a scalable architecture.

The selector and the worker are separate processes on the same laptop, so the state is a JSON file:
  - store: write a temp file in the same directory, then os.replace (atomic; replaces any older one);
  - consume: os.rename the file to a unique claim name (atomic: exactly one consumer wins), read it,
    delete it. An expired selection is deleted and never used.
"""
import json
import os
import secrets
import sys
import time
from pathlib import Path

from facetime.brodia import RoleplayConfig

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TTL_S = 120.0


_TEST_PATH = None


def state_path():
    """BRODIA_NEXT_CALL_PATH, else data/tmp/brodia_next_call.json; a test process (scripts/test_*.py, pytest) that did not
    set the env var gets a private temp file so it can never consume a real pending selection."""
    global _TEST_PATH
    if os.environ.get('BRODIA_NEXT_CALL_PATH'): return Path(os.environ['BRODIA_NEXT_CALL_PATH'])
    if os.path.basename(sys.argv[0] if sys.argv else '').startswith('test_') or 'pytest' in sys.modules:
        if _TEST_PATH is None:
            import tempfile
            _TEST_PATH = Path(tempfile.mkdtemp(prefix='brodia-test-')) / 'brodia_next_call.json'
        return _TEST_PATH
    return ROOT / 'data' / 'tmp' / 'brodia_next_call.json'


def ttl_s():
    try: return max(5.0, min(float(os.environ.get('BRODIA_NEXT_CALL_TTL_S') or DEFAULT_TTL_S), 3600.0))
    except ValueError: return DEFAULT_TTL_S


def store(scenario, receptivity, ttl=None, path=None, now=None):
    """Validate and store the ONE pending selection (replacing any previous one). Raises ValueError if invalid."""
    config = RoleplayConfig(scenario, receptivity)
    path = Path(path or state_path()); now = time.time() if now is None else now
    ttl = ttl_s() if ttl is None else ttl
    record = {'id': secrets.token_hex(4), 'scenario': config.scenario, 'receptivity': config.receptivity,
              'created_at': now, 'expires_at': now + ttl}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp')
    with open(tmp, 'w') as f:
        json.dump(record, f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
    return record


def _read(path):
    try:
        with open(path) as f: return json.load(f)
    except (OSError, ValueError):
        return None


def status(path=None, now=None):
    """{'pending': bool, ...} for the web page. Contains no secrets."""
    record = _read(Path(path or state_path())); now = time.time() if now is None else now
    if not record or record.get('expires_at', 0) <= now:
        return {'pending': False}
    return {'pending': True, 'id': record.get('id'), 'scenario': record.get('scenario'),
            'receptivity': record.get('receptivity'), 'expires_in': round(record['expires_at'] - now, 1)}


def clear(path=None):
    try: os.unlink(path or state_path()); return True
    except FileNotFoundError: return False


def consume(path=None, now=None):
    """Atomically take the pending selection once. Returns (record_with_config | None, reason)."""
    path = Path(path or state_path()); now = time.time() if now is None else now
    claim = path.with_name(f'.{path.name}.claimed.{os.getpid()}.{secrets.token_hex(4)}')
    try:
        os.rename(path, claim)
    except FileNotFoundError:
        return None, 'no pending selection'
    try:
        record = _read(claim)
    finally:
        try: os.unlink(claim)
        except OSError: pass
    if not record:
        return None, 'pending selection unreadable (discarded)'
    age = now - record.get('created_at', now)
    if record.get('expires_at', 0) <= now:
        return None, f"pending selection {record.get('id')} expired {now - record.get('expires_at', now):.0f} s ago (discarded)"
    try:
        record['config'] = RoleplayConfig(record.get('scenario'), record.get('receptivity'))
    except ValueError as e:
        return None, f'pending selection invalid ({e}; discarded)'
    return record, f"consumed selection {record.get('id')} (set {age:.0f} s ago)"
