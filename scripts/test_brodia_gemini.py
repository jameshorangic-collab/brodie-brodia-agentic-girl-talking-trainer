"""Regression checks: browser Brodia dispatch becomes Gemini's active system prompt."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import os as _os, tempfile as _tempfile; _os.environ['BRODIA_NEXT_CALL_PATH'] = _os.path.join(_tempfile.mkdtemp(prefix='brodia-test-'), 'next_call.json')  # never touch a real pending P13 selection

from facetime import worker
from facetime.brodia import RECEPTIVITIES, SCENARIOS, RoleplayConfig, build_prompt
from facetime.voice import GeminiModel


FITNESS_PROMPT_LEAKS = ('warm, brief fitness coach', 'squats:10', 'pushups:8', 'the session plan', 'set just ended', 'fast path counts')


def check(ok, message):
    if not ok:
        raise AssertionError(message)
    print('PASS:', message)


def fresh_args():
    args = worker.build_parser().parse_args(['--agent-name', 'brodia', '--voice', 'gemini'])
    return worker.resolve_mode(args)


def test_all_dispatches():
    for scenario in SCENARIOS:
        for receptivity in RECEPTIVITIES:
            args = worker.apply_brodia_dispatch(fresh_args(), json.loads(json.dumps({
                'brodia': {'scenario': scenario, 'receptivity': receptivity},
            })))
            prompt = worker.brodia_persona(args)
            check(prompt == build_prompt(RoleplayConfig(scenario, receptivity)),
                  f'{scenario}/{receptivity}: browser metadata selects its exact Brodia prompt')
            check(args.perception == 'off' and args.floor == 'open', f'{scenario}/{receptivity}: roleplay voice mode')
            check(args.handlers == 'none' and args.plan is None and args.plan_text is None,
                  f'{scenario}/{receptivity}: starter plan and handlers disabled')
            check(all(term not in prompt.lower() for term in FITNESS_PROMPT_LEAKS),
                  f'{scenario}/{receptivity}: no fitness instruction in Brodia prompt')


async def test_gemini_start_receives_prompt():
    """Exercise GeminiModel.start with a fake AgentSession, not just its stored persona."""
    import livekit.agents as agents
    original_agent, original_session = agents.Agent, agents.AgentSession
    captured = {}

    class SpyAgent:
        def __init__(self, instructions, allow_interruptions):
            self.instructions = instructions
            self.allow_interruptions = allow_interruptions
            self.chat_ctx = SimpleNamespace(copy=lambda: None)

    class FakeInput:
        def set_audio_enabled(self, enabled):
            captured['input_enabled'] = enabled

    class FakeSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.output = SimpleNamespace(audio=None)
            self.input = FakeInput()

        def on(self, *_args):
            return None

        async def start(self, agent, **_kwargs):
            captured['agent'] = agent

    args = worker.apply_brodia_dispatch(fresh_args(), {'brodia': {'scenario': 'barista', 'receptivity': 'uninterested'}})
    prompt = worker.brodia_persona(args)
    try:
        agents.Agent, agents.AgentSession = SpyAgent, FakeSession
        model = GeminiModel(prompt, api_key='test-key')
        model.rt = object()  # build() must not make a network request in this regression test
        await model.start(sink=object())
    finally:
        agents.Agent, agents.AgentSession = original_agent, original_session
    check(captured['agent'].instructions == prompt,
          'Gemini AgentSession starts with the selected Brodia system instructions')
    check(captured['input_enabled'] is False, 'Gemini input follows the existing floor initialization')


def main():
    test_all_dispatches()
    asyncio.run(test_gemini_start_receives_prompt())
    print('Brodia Gemini dispatch and system-prompt contract: PASS')


if __name__ == '__main__':
    main()
