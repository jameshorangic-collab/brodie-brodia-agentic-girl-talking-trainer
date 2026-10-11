"""Focused, dependency-free check for the P02 Park + Neutral voice hook."""
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'starter' / 'examples' / 'brodia_park_neutral'


def load_handlers():
    spec = importlib.util.spec_from_file_location('brodia_park_neutral_handlers', EXAMPLE / 'handlers.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    persona = (EXAMPLE / 'persona.md').read_text().lower()
    assert 'adult' in persona and 'park' in persona and 'neutral' in persona
    assert 'respect boundaries' in persona

    prompts = []
    handlers = load_handlers()
    handlers.on_event({'type': 'session', 'state': 'open'}, lambda *_: None, prompts.append)
    handlers.on_event({'type': 'status'}, lambda *_: None, prompts.append)
    assert len(prompts) == 1
    assert 'park' in prompts[0].lower()
    print('P02 Park + Neutral persona and opening hook: PASS')


if __name__ == '__main__':
    main()
