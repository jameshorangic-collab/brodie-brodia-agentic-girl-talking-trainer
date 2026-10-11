"""P04 checks for explicit ending, ephemeral evidence, and one feedback transition."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facetime.brodia import FeedbackSession


def main():
    session = FeedbackSession()
    assert session.observe({'type': 'voice', 'role': 'caller', 'text': 'Hi, how is your day?'}) is None
    prompt = session.observe({'type': 'voice', 'role': 'caller', 'text': 'Thanks, I would like to end practice now.'})
    assert prompt is not None and 'Hi, how is your day?' in prompt
    assert 'two strengths, two improvements' in prompt
    assert session.observe({'type': 'voice', 'role': 'caller', 'text': 'bye'}) is None
    empty = FeedbackSession(); prompt = empty.observe({'type': 'voice', 'role': 'caller', 'text': 'bye'})
    assert 'No usable caller transcript' not in prompt  # the goodbye itself is evidence
    visual = FeedbackSession()
    visual.observe({'type': 'vision_note', 'source_verified': False, 'observable_description': 'facing the camera'})
    visual.observe({'type': 'vision_note', 'source_verified': True, 'observable_description': 'turned away from the camera', 'optional_nearby_utterance': 'I have to go'})
    prompt = visual.observe({'type': 'voice', 'role': 'caller', 'text': 'Please end practice'})
    assert 'turned away from the camera' in prompt and 'facing the camera' not in prompt
    no_video = FeedbackSession(); prompt = no_video.observe({'type': 'voice', 'role': 'caller', 'text': 'end practice'})
    assert 'No verified visual observation is available' in prompt
    print('P04 explicit end and grounded feedback transition: PASS')


if __name__ == '__main__':
    main()
