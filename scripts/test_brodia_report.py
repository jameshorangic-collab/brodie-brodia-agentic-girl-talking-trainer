"""Offline tests for the post-call review (facetime/brodia_report.py): turn log, coach text, size cap, who receives it."""
import asyncio, json, sys, unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os as _os, tempfile as _tempfile; _os.environ['BRODIA_NEXT_CALL_PATH'] = _os.path.join(_tempfile.mkdtemp(prefix='brodia-test-'), 'next_call.json')
from facetime import brodia_report
from facetime.brodia import FeedbackSession, RoleplayConfig
from facetime.brodia_live import BrodiaController


def ev(delta=0, kind='neutral', reliable=True, boundary='none'):
    return dict(rapport_delta=delta, reason=f'fixture {kind} {delta}', interaction_type=kind, reliable=reliable, boundary=boundary, english=True)


class Evaluator:
    def __init__(self, results): self.results = list(results)
    async def evaluate(self, payload): return self.results.pop(0)


class FakeParticipant:
    def __init__(self): self.sent = []
    async def publish_data(self, data, **kw): self.sent.append((json.loads(data), kw))


def job(bound, controller, feedback, connected=True):
    lp = FakeParticipant()
    return NS(bound=bound, room=NS(local_participant=lp), room_connected=lambda: connected, brodia_controller=controller,
              brodia_feedback=feedback, report_sent=None), lp


class Report(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # one result per final transcript, in order: the evaluator also reads the character's line (never scored)
        self.c = BrodiaController(RoleplayConfig('park', 'neutral'), evaluator=Evaluator(
            [ev(3, 'positive'), ev(0, 'neutral'), ev(0, 'neutral'), ev(-2, 'negative'), ev(0, 'uncertain', reliable=False), ev(0, 'neutral')]))
        self.f = FeedbackSession()
        for role, text in (('caller', 'Is that a good book?'), ('character', 'It is, actually.'), ('caller', 'Nice weather.'),
                           ('caller', 'You should give me your number.'), ('caller', 'mmhm uh'), ('caller', 'Okay, end practice')):
            self.c.observe(role, text); self.f.observe({'type': 'voice', 'role': role, 'text': text, 't': 1.0})
        await asyncio.wait_for(self.c.queue.join(), 2)

    async def asyncTearDown(self): await self.c.aclose()

    async def test_turn_log_and_score_path(self):
        r = self.c.report()
        self.assertEqual((r['scenario'], r['receptivity']), ('park', 'neutral'))
        # "Okay, end practice" is the command to Brodia, not a line to the character: evaluated, never listed as a move
        self.assertEqual([t['quote'] for t in r['turns']], ['Is that a good book?', 'Nice weather.', 'You should give me your number.', 'mmhm uh'])
        self.assertEqual([t['type'] for t in r['turns']], ['positive', 'neutral', 'negative', 'uncertain'])
        self.assertEqual([t['delta'] for t in r['turns']], [3, 0, -2, 0])
        self.assertEqual(r['score']['start'], 40); self.assertEqual(r['score']['now'], 41)
        self.assertEqual([t['score'] for t in r['turns']], [43, 43, 41, 41])
        self.assertTrue(all(t['t'] >= 0 for t in r['turns']))

    async def test_coach_feedback_only_after_the_exit(self):
        self.assertTrue(self.f.finished)
        self.assertIsNone(self.f.coach_feedback())   # nothing spoken after the exit yet
        for text in ('Nice opener about the book.', 'Next time, ask a follow-up before asking for her number.'):
            self.f.observe({'type': 'voice', 'role': 'coach', 'text': text})
        self.assertEqual(self.f.coach_feedback(), 'Nice opener about the book. Next time, ask a follow-up before asking for her number.')
        self.assertIsNone(FeedbackSession().coach_feedback())

    async def test_sent_only_to_the_browser_caller_and_only_on_change(self):
        j, lp = job('brodia-browser', self.c, self.f)
        self.assertTrue(await brodia_report.send(j))
        report, kw = lp.sent[0]
        self.assertEqual(kw, {'reliable': True, 'topic': 'brodia.report', 'destination_identities': ['brodia-browser']})
        self.assertEqual(report['v'], 1); self.assertTrue(report['finished']); self.assertEqual(len(report['turns']), 4)
        self.assertEqual(report['visual'], [])
        self.assertFalse(await brodia_report.send(j))            # unchanged
        self.assertTrue(await brodia_report.send(j, force=True))
        self.f.observe({'type': 'voice', 'role': 'coach', 'text': 'Good exit.'})
        self.assertTrue(await brodia_report.send(j)); self.assertEqual(lp.sent[-1][0]['coach'], 'Good exit.')
        for bound, connected in (('chert-bridge-abc', True), (None, True), ('brodia-browser', False)):
            j2, lp2 = job(bound, self.c, self.f, connected)
            self.assertFalse(await brodia_report.send(j2)); self.assertEqual(lp2.sent, [])

    async def test_size_cap_drops_oldest_turns_first(self):
        r = brodia_report.build(self.c, self.f)
        r['turns'] = [dict(r['turns'][0], quote='x' * 160, reason='y' * 240, t=i) for i in range(60)]
        data = brodia_report.encode(r)
        self.assertLessEqual(len(data), brodia_report.MAX_BYTES)
        kept = json.loads(data)['turns']
        self.assertGreater(len(kept), 5); self.assertEqual(kept[-1]['t'], 59)

    async def test_aclose_clears_the_turn_log(self):
        await self.c.aclose(); self.assertEqual(self.c.report()['turns'], [])


if __name__ == '__main__':
    unittest.main()
