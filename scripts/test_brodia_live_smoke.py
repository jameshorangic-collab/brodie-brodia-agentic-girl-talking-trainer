"""Opt-in real Gemini audio test, no room or browser. Incurs normal API usage.

macOS: source .env.local, then python scripts/test_brodia_live_smoke.py --synthetic
Other platforms: --wav /path/to/16khz-mono-s16.wav for the initial greeting.
No recordings/transcripts are persisted or printed. Synthetic speech is NOT a
human microphone, recognition benchmark, or browser/LiveKit-network test.
"""
import argparse
import asyncio
from collections import deque
import logging
from pathlib import Path
import random
import sys
import tempfile
import time
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from livekit import rtc
from livekit.agents.voice.io import AudioInput
from facetime.audio_out import CueBank, CuePlayer
from facetime.brodia import RoleplayConfig, SCENARIOS, RECEPTIVITIES
from facetime.brodia_live import BrodiaController
from facetime.voice import GeminiModel, MixerAudioOutput


class Audio(AudioInput):
    def __init__(self):
        super().__init__(label='brodia-test-pcm')
        self.frames=deque()
    async def __anext__(self):
        await asyncio.sleep(.02)
        return rtc.AudioFrame(self.frames.popleft() if self.frames else bytes(640),16000,1,320)
    def feed(self,path):
        with wave.open(str(path),'rb') as recording:
            if (recording.getnchannels(),recording.getsampwidth(),recording.getframerate())!=(1,2,16000):
                raise ValueError('WAV must be mono 16-bit PCM at 16 kHz')
            pcm=recording.readframes(recording.getnframes())
        for offset in range(0,len(pcm),640): self.frames.append(pcm[offset:offset+640].ljust(640,b'\0'))
        return len(pcm)/32000


class Source:
    queued_duration=0
    def __init__(self): self.frames=0
    async def capture_frame(self,frame): self.frames+=1
    def clear_queue(self): pass


class RandomSource:
    def __init__(self): self.rng=random.Random(71);self.draws=0
    def random(self): self.draws+=1;return self.rng.random()


async def synth(path,text):
    process=await asyncio.create_subprocess_exec('say','--file-format=WAVE','--data-format=LEI16@16000',
        '-o',str(path),text,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
    if await process.wait()!=0: raise RuntimeError('macOS synthetic audio generation failed')


async def run(args):
    controller=BrodiaController(RoleplayConfig(args.scenario,args.receptivity),rng=RandomSource())
    turns=[];errors=[];source=Source();audio=Audio()
    player=CuePlayer(bank=CueBank.disabled(),source=source)
    mix=player.attach_mixer();sink=MixerAudioOutput(mix)
    pump=asyncio.create_task(player.run())
    model=GeminiModel(controller.instructions(),controller=controller,on_turn=lambda role,text:turns.append((role,text)))
    try:
        await asyncio.wait_for(model.start(sink),20)
        model.session.on('error',lambda ev:errors.append(type(getattr(ev,'error',ev)).__name__))
        model.session.input.audio=audio;model.set_input_enabled(True)
        with tempfile.TemporaryDirectory(prefix='brodia-audio-test-') as directory:
            wav=Path(args.wav) if args.wav else Path(directory)/'greeting.wav'
            if args.synthetic: await synth(wav,'Hi, could I get a coffee please?')
            started=time.monotonic();duration=audio.feed(wav)
            async def wait_reply(count):
                while len([t for role,t in turns if role=='coach'])<count and not errors:
                    await asyncio.sleep(.05)
                if errors: raise RuntimeError('Gemini session error')
            await asyncio.wait_for(wait_reply(1),30)
            await asyncio.wait_for(controller.queue.join(),12)
            first=sink.t_first_frame-started-duration if sink.t_first_frame else None
            spoken=[text.lower() for role,text in turns if role=='coach']
            if not spoken or any(word in text for text in spoken for word in ('squats','push-ups','workout')):
                raise AssertionError('Missing reply or fitness leakage')
            if args.synthetic:
                # A real spoken social request must invoke the registered blocking
                # function before the resulting answer, then remain consistent.
                request=Path(directory)/'request.wav'
                await synth(request,'Could I get your phone number?')
                before=len(spoken);audio.feed(request)
                await asyncio.wait_for(wait_reply(before+1),30)
                if 'contact' not in controller.state.outcomes:
                    raise AssertionError('Gemini answered a contact request without the decision tool')
                draws=controller.state.rng.draws
                audio.feed(request)
                await asyncio.wait_for(wait_reply(before+2),30)
                if controller.state.rng.draws!=draws:
                    raise AssertionError('Repeated contact request rerolled')
                await asyncio.wait_for(controller.queue.join(),12)
            if controller.diagnostics['evaluation_errors']:
                raise AssertionError('Structured evaluator failed')
            print({'result':'PASS','scenario':args.scenario,'receptivity':args.receptivity,
                   'voice':model.voice,'first_audio_after_input_ms':round(first*1000) if first is not None else None,
                   'audio_frames':source.frames,'final_caller_turns':controller.diagnostics['caller_finals'],
                   'language_failures':controller.diagnostics['language_failures'],
                   'contact_tool_invoked':'contact' in controller.state.outcomes})
    finally:
        await model.aclose();player.stop();await asyncio.gather(pump,return_exceptions=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--synthetic',action='store_true');inputs.add_argument('--wav')
    parser.add_argument('--scenario',choices=SCENARIOS,default='barista')
    parser.add_argument('--receptivity',choices=RECEPTIVITIES,default='uninterested')
    args=parser.parse_args()
    # API failures can contain request details. Print only sanitized diagnostics.
    logging.getLogger('livekit').setLevel(logging.CRITICAL)
    logging.getLogger('google').setLevel(logging.CRITICAL)
    try: asyncio.run(run(args))
    except Exception as exc:
        print('Live smoke test failed:',type(exc).__name__,'(details intentionally not printed)')
        sys.exit(1)
