"""P03 unit checks: all nine configurations are supported and bounded."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facetime.brodia import RECEPTIVITIES, SCENARIOS, RoleplayConfig, build_prompt


def main():
    prompts = {}
    for scenario in SCENARIOS:
        for receptivity in RECEPTIVITIES:
            prompt = build_prompt(RoleplayConfig(scenario, receptivity))
            assert 'adults' in prompt.lower()
            assert 'respect' in prompt.lower()
            prompts[(scenario, receptivity)] = prompt
    assert len(prompts) == 9
    assert prompts['street', 'uninterested'] != prompts['barista', 'interested']
    for scenario, receptivity in (('cafe', 'neutral'), ('park', 'maybe')):
        try:
            RoleplayConfig(scenario, receptivity)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid configuration accepted')
    print('P03 nine roleplay variants and strict validation: PASS')


if __name__ == '__main__':
    main()
