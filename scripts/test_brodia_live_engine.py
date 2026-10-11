"""Offline application + installed SDK contracts; not a live quality evaluation."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import random
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os as _os, tempfile as _tempfile; _os.environ['BRODIA_NEXT_CALL_PATH'] = _os.path.join(_tempfile.mkdtemp(prefix='brodia-test-'), 'next_call.json')  # never touch a real pending P13 selection
from facetime.brodia import RoleplayConfig, SCENARIOS, RECEPTIVITIES, FeedbackSession
from facetime.brodia_live import BrodiaController, BRODIA_VOICES
from facetime.rapport import Evaluation, RapportSettings, RapportState, acceptance_probability
from facetime.voice import GeminiModel, OpenAIModel, VoiceLayer


def result(delta=0, kind='neutral', reliable=True, boundary='none', english=True):
    return dict(rapport_delta=delta, reason='Contextual fixture observation',
                interaction_type=kind, reliable=reliable, boundary=boundary, english=english)


class Evaluator:
    def __init__(self, results): self.results, self.payloads = list(results), []
    async def evaluate(self, payload):
        self.payloads.append(payload)
        value = self.results.pop(0)
        if isinstance(value, Exception): raise value
        return value
    async def aclose(self): pass


class CountingRandom:
    def __init__(self, value): self.value, self.draws = value, 0
    def random(self): self.draws += 1; return self.value


class RapportTests(unittest.TestCase):
    def test_initial_config_all_nine(self):
        for scenario in SCENARIOS:
            for stance in RECEPTIVITIES:
                state = RapportState(RoleplayConfig(scenario, stance))
                self.assertEqual(state.score, {'interested':65,'neutral':40,'uninterested':15}[stance])
                self.assertNotIn(str(state.score), state.behavior_instruction())
        custom = RapportSettings(initial={'interested':70,'neutral':45,'uninterested':10})
        self.assertEqual(RapportState(RoleplayConfig('park','neutral'), custom).score, 45)

    def test_validated_bounded_scoring_dedupe_and_uncertainty(self):
        state = RapportState(RoleplayConfig('barista','neutral'))
        positive = Evaluation.parse(result(10,'positive'))
        self.assertEqual(state.apply('1',positive,'Nice meeting you'),4)
        self.assertEqual(state.apply('1',positive,'Another transcript'),0)
        self.assertEqual(state.apply('2',positive,'Nice meeting you'),0)
        self.assertEqual(state.apply('3',Evaluation.parse(result(0,'uncertain',False)),'???'),0)
        self.assertEqual(state.score,44)
        state.score=99
        self.assertEqual(state.apply('4',positive,'Thoughtful question'),1)
        state.score=1
        self.assertEqual(state.apply('5',Evaluation.parse(result(-10,'negative')),'Pressure'),-1)
        for bad in (result(True,'positive'),result(3,'neutral'),result(-2,'positive'),
                    result(0,reliable='true'),result(11,'positive'),result(boundary='guess')):
            with self.assertRaises(ValueError): Evaluation.parse(bad)

    def test_hysteresis(self):
        state = RapportState(RoleplayConfig('park','neutral'))
        self.assertEqual(state.band,1)
        state.apply(1,Evaluation.parse(result(2,'positive')),'First')
        self.assertEqual(state.band,1)
        state.apply(2,Evaluation.parse(result(2,'positive')),'Second')
        self.assertEqual(state.band,2)
        state.apply(3,Evaluation.parse(result(-4,'negative')),'Third')
        self.assertEqual(state.band,2)
        state.apply(4,Evaluation.parse(result(-4,'negative')),'Fourth')
        self.assertEqual(state.band,1)

    def test_smooth_curve_and_settings_validation(self):
        points=RapportSettings().probability_points
        for score, expected in points:
            self.assertAlmostEqual(acceptance_probability(score,points),expected)
        self.assertAlmostEqual(acceptance_probability(50,points),.26)
        values=[acceptance_probability(i/10,points) for i in range(1001)]
        self.assertEqual(values,sorted(values))
        self.assertLess(max(b-a for a,b in zip(values,values[1:])),.002)
        for bad in (float('nan'),float('inf'),'80'):
            with self.assertRaises(ValueError): acceptance_probability(bad,points)
        for bad in ({'max_delta':0},{'initial':{'neutral':40}}, {'probability_points':((0,.9),(100,1.))}):
            with self.assertRaises(ValueError): RapportSettings(**bad)

    def test_seeded_probability_no_reroll_and_boundaries(self):
        for stance in RECEPTIVITIES:
            a=RapportState(RoleplayConfig('park',stance),rng=random.Random(73))
            b=RapportState(RoleplayConfig('park',stance),rng=random.Random(73))
            self.assertEqual(a.decide('contact'),b.decide('contact'))
        rng=CountingRandom(.99)
        state=RapportState(RoleplayConfig('barista','interested'),rng=rng)
        self.assertFalse(state.decide('contact').accepted)
        state.score=100
        for _ in range(20): self.assertFalse(state.decide('contact').accepted)
        self.assertEqual(rng.draws,1)
        state.record_boundary('date')
        self.assertFalse(state.decide('meet_again').accepted)
        self.assertEqual(rng.draws,1)
        state.record_boundary('all')
        self.assertFalse(state.decide('continue').accepted)
        self.assertEqual(rng.draws,1)

    def test_acceptance_uncertainty_scene_and_fictional_contact(self):
        rng=CountingRandom(0)
        state=RapportState(RoleplayConfig('park','interested'),rng=rng)
        self.assertIsNone(state.decide('contact',uncertain=True))
        self.assertEqual(rng.draws,0)
        outcome=state.decide('contact')
        self.assertTrue(outcome.accepted)
        self.assertEqual(state.decide('contact'),outcome)
        self.assertIn('brodia@example.invalid',outcome.instruction()['direction'])
        state.record_boundary('contact')
        self.assertFalse(state.decide('contact').accepted)
        self.assertEqual(rng.draws,1)
        probabilities=[]
        for scene in ('street','barista','park'):
            other=RapportState(RoleplayConfig(scene,'interested'),rng=CountingRandom(0))
            probabilities.append(other.decide('date').probability)
        self.assertEqual(probabilities,sorted(probabilities))
        other=RapportState(RoleplayConfig('park','interested'),rng=CountingRandom(0))
        self.assertFalse(other.decide('date',appropriate=False).accepted)
        self.assertEqual(other.rng.draws,0)
        with self.assertRaises(ValueError): other.decide('contact',uncertain='false')


class LiveContracts(unittest.IsolatedAsyncioTestCase):
    async def test_brodia_shutdown_without_research_assets(self):
        from scripts.test_worker_shutdown import FakeCtx, FakeRoom, P
        from facetime import worker
        from facetime.perception import Config
        from facetime.audio_out import CueBank
        from livekit import rtc
        import tempfile
        with tempfile.TemporaryDirectory(prefix='brodia-shutdown-') as directory:
            args=worker.resolve_mode(worker.build_parser().parse_args(['--voice','off','--leave-grace-s','0.1']))
            args=worker.apply_brodia_dispatch(args,{'brodia':{'scenario':'barista','receptivity':'uninterested'}})
            args.cue_log=str(Path(directory)/'cues.jsonl');args.event_log=str(Path(directory)/'events.jsonl')
            for connect_error,leave in ((RuntimeError('room gone'),False),(None,False),(None,True)):
                ctx=FakeCtx(FakeRoom(),connect_error=connect_error)
                job=worker.CoachJob(ctx,args,Config.from_args(args),None,CueBank.disabled(),{})
                task=asyncio.create_task(job.run())
                if connect_error is None:
                    await asyncio.sleep(.15)
                    if leave:
                        job.bound='brodia-browser';job.on_participant_disconnected(P('brodia-browser'))
                    else: ctx.room.emit('disconnected',rtc.DisconnectReason.ROOM_DELETED)
                await asyncio.wait_for(task,2)
                self.assertTrue(job.closed)
                self.assertTrue(ctx.shutdowns)
                self.assertIsNone(job.thread)
                await job.aclose()  # idempotent

    async def test_actual_google_connect_config_all_nine(self):
        from livekit.agents import llm
        from livekit.plugins.google.realtime.realtime_api import RealtimeSession
        for scenario in SCENARIOS:
            for stance in RECEPTIVITIES:
                controller=BrodiaController(RoleplayConfig(scenario,stance),evaluator=Evaluator([]))
                with patch.dict(os.environ,{'GEMINI_VOICE':'Puck','GEMINI_LANGUAGE':'es-ES','BRODIA_GEMINI_VOICE':'Leda'}):
                    model=GeminiModel('unused',model='gemini-3.8-live',api_key='offline-test-key',controller=controller)
                    rt=model.build()
                # Exercise the installed plugin's REAL outbound connect-config builder
                # without creating its socket/background task or network client.
                session=object.__new__(RealtimeSession)
                session._opts=rt._opts
                session._tools=llm.ToolContext(controller.tools())
                session._realtime_model=rt
                session._session_resumption_handle=None
                config=session._build_connect_config()
                self.assertEqual(config.speech_config.voice_config.prebuilt_voice_config.voice_name,'Leda')
                self.assertIsNone(config.speech_config.language_code)
                instructions=config.system_instruction.parts[0].text
                self.assertEqual(instructions,controller.instructions())
                self.assertIn('ONLY natural American English',instructions)
                self.assertIn('fictional',instructions)
                self.assertNotIn('the session plan',instructions)
                self.assertIsNotNone(config.input_audio_transcription)
                self.assertIsNotNone(config.output_audio_transcription)
                declarations=config.tools[0].function_declarations
                self.assertEqual({d.name for d in declarations},{'decide_social_outcome','record_social_boundary'})
                self.assertTrue(all(d.behavior.value=='BLOCKING' for d in declarations))
                self.assertEqual(config.realtime_input_config.activity_handling.value,'START_OF_ACTIVITY_INTERRUPTS')
                await controller.aclose()

    async def test_voice_allowlist_and_openai_fallback(self):
        for voice in BRODIA_VOICES:
            controller=BrodiaController(RoleplayConfig('park','neutral'),evaluator=Evaluator([]))
            model=GeminiModel('',voice=voice,controller=controller)
            self.assertEqual(model.voice,voice)
            await controller.aclose()
        controller=BrodiaController(RoleplayConfig('park','neutral'),evaluator=Evaluator([]))
        with self.assertRaises(ValueError): GeminiModel('',voice='Puck',controller=controller)
        with self.assertRaises(ValueError): GeminiModel('',model='gemini-3.8-live-extended-thinking',controller=controller)
        fallback=OpenAIModel('Brodia',api_key='offline-test-key')
        self.assertEqual(fallback.voice,'ash')
        self.assertIsNotNone(fallback.build())
        await controller.aclose()

    async def test_final_only_and_agent_tool_registration(self):
        import livekit.agents as agents
        captures={}
        class Agent:
            def __init__(self,**kwargs): captures.update(kwargs)
        class Session:
            def __init__(self,**kwargs): self.output=NS(audio=None);self.input=NS(set_audio_enabled=lambda _:None)
            def on(self,*args): pass
            async def start(self,*args,**kwargs): pass
            async def aclose(self): pass
        evaluator=Evaluator([result(3,'positive'),result()])
        controller=BrodiaController(RoleplayConfig('barista','interested'),evaluator=evaluator)
        model=GeminiModel('',api_key='offline-test-key',controller=controller)
        model.rt=object()
        with patch.object(agents,'Agent',Agent),patch.object(agents,'AgentSession',Session):
            await model.start(object())
        self.assertEqual(captures['instructions'],controller.instructions())
        self.assertEqual(len(captures['tools']),2)
        model._on_user_transcript(NS(transcript='Nice',is_final=False))
        self.assertEqual(controller.turn_seq,0)
        # No real agent updates in this fake session.
        model.agent=None
        final=NS(transcript='Nice to meet you',is_final=True,item_id='same-turn')
        model._on_user_transcript(final)
        model._on_user_transcript(final)
        model._on_item(NS(item=NS(role='assistant',text_content='Hey!')))
        await controller.queue.join()
        self.assertEqual(controller.state.score,68)
        self.assertEqual(len(evaluator.payloads),2)
        await model.aclose()

    async def test_dialogue_A_to_I(self):
        # Semantic scores are fixtures: tests prove plumbing/rules, not model judgment.
        cases=[('A','barista','interested','Your latte art made my morning.',result(3,'positive'),68),
               ('C','barista','neutral','Hi, uh, I forgot my own name for a second.',result(),40),
               ('D','barista','uninterested','Come on, give me your number anyway.',result(-4,'negative'),11),
               ('E','park','interested','This squirrel clearly runs the park.',result(4,'positive'),69),
               ('F','street','uninterested','No worries, have a nice day. Goodbye.',result(3,'positive'),18),
               ('G','park','neutral','I promise my jokes improve after coffee.',result(2,'positive'),42),
               ('H','park','neutral','[unclear] coffee nine?',result(0,'uncertain',False),40)]
        for label,scene,stance,text,assessment,score in cases:
            evaluator=Evaluator([assessment])
            controller=BrodiaController(RoleplayConfig(scene,stance),evaluator=evaluator)
            controller.observe('caller',text)
            await controller.queue.join()
            self.assertEqual(controller.state.score,score,label)
            self.assertEqual(evaluator.payloads[0]['scenario'],scene)
            if label=='F': self.assertTrue(controller.state.finished)
            await controller.aclose()
        # B: a request uses Python BEFORE the tool returns an instruction to speak.
        controller=BrodiaController(RoleplayConfig('barista','interested'),evaluator=Evaluator([]),rng=CountingRandom(0))
        decide,boundary=controller.tools()
        answer=await decide(request='contact',appropriate=True,uncertain=False)
        self.assertEqual(answer['decision'],'accept')
        await decide(request='contact',appropriate=True,uncertain=False)
        self.assertEqual(controller.state.rng.draws,1)
        await boundary(request='contact')
        self.assertEqual((await decide(request='contact',appropriate=True,uncertain=False))['decision'],'decline')
        await controller.aclose()
        # I: detected Spanish produces English recovery, no content logs/voice change.
        controller=BrodiaController(RoleplayConfig('park','neutral'),evaluator=Evaluator([result(english=False)]))
        instructions=[];generations=[]
        async def update(value): instructions.append(value)
        controller.model=NS(agent=NS(update_instructions=update),speaking=False,generate=generations.append)
        controller.observe('character','Hola, ¿cómo estás?')
        await controller.queue.join()
        self.assertEqual(controller.diagnostics['language_failures'],1)
        self.assertIn('American English',instructions[-1])
        self.assertEqual(len(generations),1)
        await controller.aclose()

    async def test_context_validation_failure_and_cleanup(self):
        evaluator=Evaluator([result(3,'positive'),ValueError('private transcript must not appear'),result(english='false')])
        controller=BrodiaController(RoleplayConfig('park','neutral'),evaluator=evaluator)
        controller.observe('caller','First context turn')
        controller.observe('caller','Second context turn')
        controller.observe('character','Third')
        await controller.queue.join()
        self.assertEqual(controller.state.score,43)
        self.assertEqual(controller.diagnostics['evaluation_errors'],2)
        self.assertEqual(evaluator.payloads[1]['context'][0]['text'],'First context turn')
        await controller.aclose()
        self.assertTrue(controller.task.done())
        self.assertFalse(controller.history)

    async def test_bounded_queue_cancel_and_recovery_does_not_interrupt_new_user(self):
        class Slow:
            async def evaluate(self, payload): await asyncio.Event().wait()
        controller=BrodiaController(RoleplayConfig('park','neutral'),evaluator=Slow())
        for index in range(20): controller.observe('caller',f'Turn {index}')
        self.assertEqual(controller.queue.qsize(),16)
        self.assertEqual(controller.diagnostics['queue_dropped'],4)
        self.assertEqual(controller.state.score,40)
        await asyncio.wait_for(controller.aclose(),.5)
        self.assertEqual(controller.queue.qsize(),0)
        controller=BrodiaController(RoleplayConfig('park','neutral'),evaluator=Evaluator([]))
        generations=[]
        async def update(_): pass
        controller.model=NS(agent=NS(update_instructions=update),speaking=False,
                            last_caller_t=20,generate=generations.append)
        await controller.recover_language(observed_at=10)
        self.assertEqual(generations,[])
        await controller.aclose()

    async def test_worker_browser_metadata_to_actual_model_and_privacy(self):
        from facetime import worker, brodia_server
        from facetime.audio_out import CueBank
        class LiveKit:
            def __init__(self): self.agent_dispatch=NS(create_dispatch=self.dispatch);self.requests=[]
            async def dispatch(self,request): self.requests.append(request)
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
        fake=LiveKit()
        with patch.object(brodia_server.api,'LiveKitAPI',lambda:fake),patch.object(brodia_server,'mint',lambda *a,**k:'offline-token'),patch.dict(os.environ,{'LIVEKIT_URL':'wss://example.invalid','GEMINI_API_KEY':'offline-test-key'}),patch.object(VoiceLayer,'attach',lambda _:None):
            for scene in SCENARIOS:
                for stance in RECEPTIVITIES:
                    await brodia_server.create_session({'scenario':scene,'receptivity':stance})
                    args=worker.resolve_mode(worker.build_parser().parse_args(['--voice','gemini']))
                    args=worker.apply_brodia_dispatch(args,json.loads(fake.requests[-1].metadata))
                    job=object.__new__(worker.CoachJob)
                    job.a=args;job.player=NS(mix=NS(duck=.5));job.voice_mode=True;job.vision=None
                    layer=job.build_voice()
                    self.assertEqual(layer.model.controller.state.config,RoleplayConfig(scene,stance))
                    self.assertEqual(layer.model.voice,'Leda')
                    self.assertIsNone(layer.handlers)
                    self.assertIsNone(layer.say_now('One more squat'))
                    layer.on_event({'type':'session','state':'rest','exercise':'squat','count':10})
                    self.assertEqual(layer.n_context,0)
                    await layer.model.aclose()
        self.assertIsNone(CueBank.disabled().get('One more squat'))
        job=object.__new__(worker.CoachJob)
        job.a=NS(brodia_scenario='barista',log_caller=False,publish_data=True)
        job.per=None;job.t0=0;job.voice_seq=0;job.events=asyncio.Queue()
        job.event_writer=lambda _:self.fail('Transcript persisted without opt-in')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            job.emit_voice('caller','Secret caller words')
            job.emit_voice('coach','Secret character words')
        self.assertNotIn('Secret',output.getvalue())
        self.assertEqual(job.events.qsize(),2)
        self.assertFalse(FeedbackSession._ends('I walked by yesterday'))


if __name__=='__main__': unittest.main(verbosity=2)
