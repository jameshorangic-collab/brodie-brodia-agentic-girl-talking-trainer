"""Tests for the conversational layer (facetime/voice.py) and the cue player's mixer input (facetime/audio_out.py), no room needed.

1. Floor gating with a fake model and an injected clock: wait/rest/done open the floor (caller audio forwarded), active closes it
   (audio dropped, the reply in flight interrupted, the sink cut), ask_voice while closed is queued and fires at the next opening,
   a gesture or probe opens a 4 s window outside a set (never during active; a probe only when armed), the window's expiry is seen
   on any event, the queue is capped, a queued ask older than 15 s is dropped at the opening and the queue is dropped when a set starts.
2. SetSummary: the context text at the rest names the exercise, the count, the corrections spoken and the next item; never per rep;
   nothing at wait.
3. VoiceLayer with a fake model: context is fed at rest/done only, handlers get say_now/ask_voice, the sink is bound to the Floor;
   the default starter/handlers.py asks at rest and done and nowhere else.
4. Mixer ducking with a real-time fake source (WavSource-style: capture_frame paces 20 ms per frame): a 440 Hz model stream, a
   silent count clip and a tone clip from a fake bank. Asserts the count is pushed within 60 ms of say(), its frames are contiguous
   (the pump never interleaves), the model stream under the clip is about 10 dB down, the stream is continuous (no sample lost) and
   back to full level after the hold.
5. MixerAudioOutput (the AgentSession sink) segment accounting: flush -> playback_finished once drained; clear_buffer -> interrupted;
   the hard cut: a floor close clears the mixer and every later frame is dropped (and a reply that starts closed is interrupted);
   a clear_buffer during the hand-over between two replies finalizes both (no playback_finished is ever owed).
6. Default path: a CuePlayer without attach_mixer() pushes the clip bytes unchanged (byte identity with the demo path).
7. `python -m facetime.worker --voice gemini --help` (and the plain --help) exit 0 and list the voice and probe flags.
8. --live (needs GEMINI_API_KEY and the Live API): one text-in audio-out turn through VoiceLayer's own model object (GeminiModel +
   AgentSession, no room) into the mixer sink; prints the time to the first audio frame and the model's RMS level.
9. The open floor (Floor(always_open=True), the worker's --floor open / --perception off): open from the start, never closes on
   active, asks fire at once, a gesture or probe changes nothing, no interrupt and no cut ever; the VoiceLayer's on_caller
   enables the model input and the vision tee; the synthetic session open event reaches the handlers.
10. The vision tee (VideoTee, --vision): a fake 10 fps frame source for 3 s yields about 1 forwarded frame per second to a fake
   model with push_video (through the same loop the framework runs), none before the tee is enabled (the model session), none
   when nothing is offered (a warm job); the fps is capped at 2; aclose() ends the forward loop.
11. --live-vision (needs GEMINI_API_KEY): the model session started with the tee as session.input.video accepts one pushed
   1280x720 frame (JPEG through the plugin's push_video) and still answers a text turn afterwards.

Run:  .venv/bin/python scripts/test_voice.py [--live] [--live-vision] [--model gemini-3.8-live]
"""
import argparse, asyncio, os, subprocess, sys, time
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import os as _os, tempfile as _tempfile; _os.environ['BRODIA_NEXT_CALL_PATH'] = _os.path.join(_tempfile.mkdtemp(prefix='brodia-test-'), 'next_call.json')  # never touch a real pending P13 selection
from facetime import SAMPLE_RATE, FRAME_SAMPLES
from facetime.audio_out import CuePlayer, MixInput
from facetime.voice import Floor, SetSummary, VoiceLayer, MixerAudioOutput, GeminiModel, VideoTee, OPEN_STATES, DEFAULT_PERSONA, load_handlers, HANDLERS_PATH, ASK_TTL_S

PASS = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg, flush=True); PASS.append(bool(cond))
    return cond


def ev(type_, **kw):
    d = dict(v='1', t=0.0, t_wall=time.time(), seq=0, type=type_, frame=0); d.update(kw); return d


def session(state, exercise='squats', target=10, count=0, item=0, done=False):
    return ev('session', state=state, exercise=exercise, target=target, count=count, item=item, done=done, mode='plan')


class FakeModel:
    def __init__(self):
        self.input = None; self.generated = []; self.interrupts = 0; self.context = []; self.started = True; self.model_id = 'fake'; self.voice = 'Puck'
    def set_input_enabled(self, on): self.input = bool(on)
    def generate(self, prompt): self.generated.append(prompt)
    def interrupt(self): self.interrupts += 1
    async def add_context(self, text): self.context.append(text)
    async def aclose(self): pass


# ---------------- 1. floor ----------------
def test_floor():
    print('[1] floor gating', flush=True)
    now = [0.0]; m = FakeModel(); f = Floor(m, window_s=4.0, queue_max=3, now=lambda: now[0])
    check(f.on_event(session('init')) is None and not f.open and m.input is None, 'init: floor closed, model untouched')
    check(f.on_event(session('wait')) == 'open' and f.open and m.input is True, 'wait: floor opens, caller audio forwarded')
    check(f.on_event(ev('rep', exercise='squats', n=1)) is None and f.open, 'a rep event changes nothing')
    check(f.on_event(session('active')) == 'close' and not f.open and m.input is False and m.interrupts == 1, 'active: floor closes, audio dropped, reply interrupted')
    check(f.ask('comment') == 'queued' and m.generated == [], 'ask_voice during a set is queued, not spoken')
    check(f.on_event(session('rest', count=10)) == 'open' and m.input is True and m.generated == ['comment'], 'rest: floor opens and the queued ask fires')
    check(f.ask('answer me') == 'spoken' and m.generated[-1] == 'answer me', 'ask_voice during a rest is spoken at once')
    check(f.on_event(session('wait', exercise='pushups', item=1)) is None and f.open, 'rest -> wait stays open')
    check(f.on_event(session('active', exercise='pushups', item=1)) == 'close' and m.interrupts == 2, 'next set closes again')
    now[0] = 10.0
    check(f.on_event(ev('gesture', name='tpose')) is None and not f.open and m.input is False and f.n_ignored == 1, 'a T-pose DURING A SET opens no window (logged, not acted on)')
    check(f.on_event(ev('probe', arms_up=True)) is None and not f.open and f.n_ignored == 2, 'a probe during a set opens no window')
    check(f.on_event(session('rest', count=8)) == 'open' and f.n_open == 3, 'the rest opens it')
    # windows outside a set: a closed, non-active state (init / detect) is where they matter
    g = FakeModel(); w = Floor(g, window_s=4.0, queue_max=3, now=lambda: now[0]); w.on_event(session('init'))
    check(w.on_event(ev('gesture', name='tpose')) == 'open' and w.open and g.input is True, 'a T-pose while the session is not active opens a 4 s window')
    now[0] = 12.0; check(w.tick() is None and w.open, 'window still open after 2 s')
    now[0] = 14.5; check(w.on_event(ev('rep', exercise='squats', n=3)) == 'close' and not w.open and g.input is False, 'window expiry is seen on a rep event, not only on the idle tick')
    now[0] = 20.0
    check(w.on_event(ev('probe', arms_up=True)) == 'open' and w.open, 'an armed probe opens a window')
    now[0] = 24.1; check(w.tick() == 'close' and not w.open, 'probe window closes')
    h = FakeModel(); u = Floor(h, probe=False, now=lambda: now[0]); u.on_event(session('init'))
    check(u.on_event(ev('probe', arms_up=True)) is None and not u.open and u.n_ignored == 1, 'probe=False (worker without --latency-probe): a probe opens nothing')
    check(u.on_event(ev('gesture', name='tpose')) == 'open' and u.open, 'but a T-pose still does')
    # the queue: capped, aged out at the opening, dropped when a set starts
    for i in range(4): w.ask(f'q{i}')
    check([p for _, p in w.queue] == ['q1', 'q2', 'q3'] and w.n_dropped_asks == 1, 'queue capped at 3, oldest dropped')
    now[0] = 30.0
    check(w.on_event(session('done', done=True)) == 'open' and g.generated[-1] == 'q1\nq2\nq3', 'done opens the floor and fires the joined queue (6 s old, kept)')
    check(w.on_event(session('active')) == 'close' and w.ask('late') == 'queued', 'ask while active: queued')
    now[0] = 30.0 + ASK_TTL_S + 1
    n_gen = len(g.generated)
    check(w.on_event(session('rest', count=10)) == 'open' and len(g.generated) == n_gen and w.queue == [] and w.n_dropped_asks == 2, f'a queued ask {ASK_TTL_S + 1:.0f} s old is dropped at the opening, nothing generated')
    w.on_event(session('init')); w.ask('stale by the set'); n_gen = len(g.generated)
    check(w.on_event(session('active')) is None and w.queue == [] and w.n_dropped_asks == 3, 'the next set start drops every queued ask')
    check(w.on_event(session('rest', count=10)) == 'open' and len(g.generated) == n_gen, 'and nothing fires at the following rest')
    check(f.n_open == 3 and f.n_close == 2 and w.n_open == 5 and w.n_close == 4, f'transitions: {f.n_open}/{f.n_close} and {w.n_open}/{w.n_close}')


# ---------------- 2. summary ----------------
def test_summary():
    print('[2] set summary context', flush=True)
    s = SetSummary('squats:10,pushups:8,jumping jacks:20')
    s.on_event(session('wait')); s.on_event(session('active'))
    for n in range(1, 8): s.on_event(ev('rep', exercise='squats', n=n))
    s.on_event(ev('fault', label='squats - shallow', cue_text='Sink lower', p=0.6)); s.on_event(ev('cue', text='Sink lower', intent='correction'))
    s.on_event(ev('fault', label='squats - shallow', cue_text='Sink lower', p=0.7))
    s.on_event(ev('cue', text="That's seven, nice work", intent='milestone', why='set timeout 75.0s'))
    s.on_event(session('rest', exercise=None, count=7))
    t = s.text('rest'); print('   ', t)
    check('squats' in t and '7 of 10' in t and 'Sink lower' in t and 'pushups x 8' in t and 'shallow x2' in t, 'rest summary: exercise, count, correction, next item, fault count')
    check(s.reps == 0 and s.cues == [] and s.sets == [('squats', 7)], 'the set is closed and remembered')
    s.on_event(session('wait', exercise='pushups', target=8, item=1))
    check(s.text('wait') is None, 'wait context: none (a line there was heard under the first counts on 10-09)')
    s.on_event(session('active', exercise='pushups', target=8, item=1)); s.on_event(ev('rep', exercise='pushups', n=4))
    s.on_event(session('done', exercise=None, count=4, item=1, done=True))
    t3 = s.text('done'); check('squats 7 reps' in t3 and 'pushups 4 reps' in t3 and 'Close the session' in t3, 'done summary lists every set')


# ---------------- 3. VoiceLayer with a fake model ----------------
class FakeJob:
    def __init__(self):
        self.events = asyncio.Queue(); self.player = None; self.voice_events = []
    def emit_voice(self, role, text): self.voice_events.append((role, text))


async def test_layer():
    print('[3] VoiceLayer with a fake model and handlers', flush=True)
    job = FakeJob(); m = FakeModel(); seen = []
    def handler(e, say_now, ask_voice):
        seen.append(e['type'])
        if e['type'] == 'session' and e['state'] == 'rest': seen.append(ask_voice('one sentence'))
        if e['type'] == 'session' and e['state'] == 'active': seen.append(ask_voice('later'))
    now = [0.0]
    v = VoiceLayer(job, model=m, plan='squats:10,pushups:8', handlers=handler, now=lambda: now[0])
    for e in (session('init'), session('wait'), session('active'), ev('rep', exercise='squats', n=1), ev('rep', exercise='squats', n=2),
              ev('cue', text='Two', intent='count'), session('rest', exercise=None, count=2)):
        v.on_event(e)
    await asyncio.sleep(0.05)
    check(seen.count('session') == 4 and 'later' not in m.generated[:0] and seen[-1] == 'spoken' and 'queued' in seen, 'handlers ran on every event; ask at active queued, at rest spoken')
    check(m.generated == ['later', 'one sentence'], f'queued ask fired at the rest, then the rest ask: {m.generated}')
    check(len(m.context) == 1 and 'squats, 2 of 10' in m.context[0] and 'Next up: pushups x 8' in m.context[0], f'context fed at the rest only (nothing at wait): {len(m.context)}')
    check(v.say_now('One') is None, 'say_now without a player returns None (events-only)')
    # the sink is bound to the Floor when a player is there
    job2 = FakeJob(); job2.player = CuePlayer(bank=FakeBank({}), source=FakeSource()); m2 = FakeModel()
    v2 = VoiceLayer(job2, model=m2, plan='squats:10', handlers=None, now=lambda: now[0]); mix2 = v2.attach()
    check(mix2 is job2.player.mix and v2.sink.floor is v2.floor and v2.floor.sink is v2.sink, 'attach(): the sink reads the Floor and the Floor cuts through the sink')
    job2.player.stop()
    # the default starter/handlers.py: one ask at each rest and at done, nothing else
    fn = load_handlers(HANDLERS_PATH); m3 = FakeModel(); job3 = FakeJob()
    v3 = VoiceLayer(job3, model=m3, plan='squats:10,pushups:8', handlers=fn, now=lambda: now[0])
    for e in (session('init'), session('wait'), session('active'), ev('rep', exercise='squats', n=1), ev('cue', text='One', intent='count'),
              ev('fault', label='squats - shallow', cue_text='Sink lower', p=0.6), ev('visibility', state='partial', paused=True, no_pose_s=0.0)):
        v3.on_event(e)
    check(fn is not None and m3.generated == [], 'default handler: silent at init, wait, active, rep, cue, fault, visibility')
    v3.on_event(session('rest', exercise=None, count=10))
    check(len(m3.generated) == 1 and 'ONE short sentence' in m3.generated[0] and 'comes next' in m3.generated[0], f'default handler asks at the rest: {m3.generated[-1][:60]!r}')
    v3.on_event(session('wait', exercise='pushups', target=8, item=1)); v3.on_event(session('active', exercise='pushups', target=8, item=1))
    v3.on_event(session('done', exercise=None, count=8, item=1, done=True))
    check(len(m3.generated) == 2 and 'close it warmly' in m3.generated[1], f'default handler asks at done: {m3.generated[-1][:60]!r}')
    # without a model the default handler is harmless: ask_voice returns None (one notice), say_now still works
    v4 = VoiceLayer(FakeJob(), model=None, plan='squats:10', handlers=fn); v4.on_event(session('rest', count=10)); v4.on_event(session('done', count=10, done=True))
    check(v4.floor is None and v4.ask_voice('x') is None and v4._warned_no_model, 'no model: ask_voice returns None')


# ---------------- 4. mixer ducking ----------------
class FakeSource:
    """CuePlayer sink that paces 20 ms per frame and records every push (push time, samples)."""
    def __init__(self): self.pushes = []; self.cleared = 0
    async def capture_frame(self, chunk):
        self.pushes.append((time.monotonic(), np.asarray(chunk, np.int16).copy())); await asyncio.sleep(len(chunk) / SAMPLE_RATE)
    async def wait_for_playout(self): pass
    def clear_queue(self): self.cleared += 1


def tone(hz, s, amp):
    t = np.arange(int(s * SAMPLE_RATE)) / SAMPLE_RATE
    return (np.sin(2 * np.pi * hz * t) * amp).astype(np.int16)


class FakeBank:
    def __init__(self, clips): self.clips = clips
    def get(self, text): return self.clips.get(text)
    def duration(self, text): return len(self.clips[text]) / SAMPLE_RATE if text in self.clips else None


def rms_db(x):
    x = np.asarray(x, np.float32) / 32768.0; r = float(np.sqrt(np.mean(x * x)) + 1e-9); return 20 * np.log10(r)


async def test_mixer():
    print('[4] mixer: the voice holds under clips (no ducked overlap) and count timing with a real-time fake source', flush=True)
    src = FakeSource(); bank = FakeBank({'One': np.zeros(int(0.4 * SAMPLE_RATE), np.int16), 'Two': tone(3000, 0.3, 8000)})
    recs = []; p = CuePlayer(bank=bank, source=src, on_record=recs.append, queue_ms=60)
    mix = p.attach_mixer(duck_db=-10.0, hold_ms=150)
    task = asyncio.create_task(p.run())
    model = tone(440, 3.0, 8000); mix.write(model)                       # 3 s of model speech, -12 dBFS
    await asyncio.sleep(0.5); t_say1 = time.monotonic(); r1 = p.say('One', 'count')
    await asyncio.sleep(0.7); t_say2 = time.monotonic(); r2 = p.say('Two', 'count')
    await asyncio.sleep(1.3)
    p.stop(); await asyncio.gather(task, return_exceptions=True)
    one = next(r for r in recs if r['text'] == 'One'); two = next(r for r in recs if r['text'] == 'Two')
    check(one['status'] == 'played' and two['status'] == 'played', 'both counts played')
    # push delay measured on the monotonic clock: the record's t_push is wall time, so compare through the source's push log
    first_one = next(t for t, c in src.pushes if t >= t_say1 and len(c) == FRAME_SAMPLES and not np.any(c))   # the silent clip's first frame: pure clip, nothing mixed under it
    lag1 = 1000 * (first_one - t_say1)
    check(lag1 < 60, f'count pushed {lag1:.0f} ms after say() with the model stream running (limit 60)')
    frames_one = [(t, c) for t, c in src.pushes if one['t_push'] - 0.001 <= time.time() - (time.monotonic() - t) <= one['t_done'] + 0.001]
    span_one = 1000 * (frames_one[-1][0] - frames_one[0][0]) if len(frames_one) > 1 else 0
    # 20 frames of 20 ms; the fake source's sleeps overshoot about 1 ms per frame on a loaded box (402 to 425 ms seen), an interleaved pump frame would add 20 ms (440+)
    check(18 <= len(frames_one) <= 21 and span_one < 0.435 * 1000, f'the clip\'s frames are contiguous: {len(frames_one)} frames over {span_one:.0f} ms (pump did not interleave)')
    # hold (2026-10-10): the silent clip's output is silence, nothing of the model stream is mixed under a clip
    before = [c for t, c in src.pushes if t_say1 - 0.25 < t < t_say1 - 0.02]
    during = [c for t, c in frames_one[2:-1]]
    check(not np.any(np.concatenate(during)), 'nothing mixed under the count (the voice holds)')
    # the stream resumes at full level after the hold (150 ms) + ramp
    t_done1 = frames_one[-1][0] + 0.02
    after = [c for t, c in src.pushes if t_done1 + 0.3 < t < t_done1 + 0.5]
    check(abs(rms_db(np.concatenate(after)) - rms_db(np.concatenate(before))) < 1.0, 'model stream resumes at full level 300 ms after the clip')
    # the tone clip plays at full level on top of the ducked stream
    frames_two = [c for t, c in src.pushes if two['t_push'] - 0.001 <= time.time() - (time.monotonic() - t) <= two['t_done'] + 0.001]
    x = np.concatenate(frames_two[1:-1]).astype(np.float32); n = len(x); tt = np.arange(n) / SAMPLE_RATE
    a3k = 2 * abs(np.sum(x * np.exp(-2j * np.pi * 3000 * tt))) / n; a440 = 2 * abs(np.sum(x * np.exp(-2j * np.pi * 440 * tt))) / n
    check(abs(a3k - 8000) < 800 and a440 < 300, f'under "Two": clip 3 kHz at {a3k:.0f} (8000), model 440 Hz at {a440:.0f} (held, expect about 0)')
    check(mix.n_read + mix.pending == mix.n_written and mix.n_cleared == 0, f'stream continuous: read {mix.n_read} + pending {mix.pending} = written {mix.n_written}')
    total = sum(len(c) for _, c in src.pushes); check(total >= int(2.0 * SAMPLE_RATE), f'{total / SAMPLE_RATE:.2f} s pushed in 2.5 s wall (stream + clips; the hold after each clip is silence, no stall)')
    # say_now (the latency probe) still cuts: it is pushed at once and the source queue is cleared
    src2 = FakeSource(); recs2 = []; p2 = CuePlayer(bank=FakeBank({'[beep]': tone(1000, 0.08, 16000), 'Ten': tone(500, 1.0, 8000)}), source=src2, on_record=recs2.append)
    mix2 = p2.attach_mixer(); task2 = asyncio.create_task(p2.run()); mix2.write(tone(440, 2.0, 8000))
    await asyncio.sleep(0.2); p2.say('Ten', 'count'); await asyncio.sleep(0.3); p2.say_now('[beep]', 'probe'); await asyncio.sleep(0.4)
    p2.stop(); await asyncio.gather(task2, return_exceptions=True)
    st = {r['text']: r['status'] for r in recs2}
    check(st.get('Ten') == 'cut' and st.get('[beep]') == 'played' and src2.cleared >= 1, f'say_now cuts the clip and clears the queue with the mixer on: {st}')


# ---------------- 5. the sink ----------------
async def test_sink():
    print('[5] MixerAudioOutput segment accounting', flush=True)
    from livekit import rtc
    src = FakeSource(); p = CuePlayer(bank=FakeBank({}), source=src); mix = p.attach_mixer(); task = asyncio.create_task(p.run())
    sink = MixerAudioOutput(mix, lead_s=0.02)
    for i in range(10): await sink.capture_frame(rtc.AudioFrame(tone(300, 0.02, 6000).tobytes(), SAMPLE_RATE, 1, FRAME_SAMPLES))
    sink.flush(); t0 = time.monotonic(); evt = await asyncio.wait_for(sink.wait_for_playout(), 2.0)
    check(not evt.interrupted and abs(evt.playback_position - 0.2) < 0.03 and 0.15 < time.monotonic() - t0 < 0.5, f'segment 1 drained: position {evt.playback_position:.2f} s, interrupted {evt.interrupted}')
    for i in range(50): await sink.capture_frame(rtc.AudioFrame(tone(300, 0.02, 6000).tobytes(), SAMPLE_RATE, 1, FRAME_SAMPLES))
    sink.flush(); await asyncio.sleep(0.15); sink.clear_buffer(); evt2 = await asyncio.wait_for(sink.wait_for_playout(), 2.0)
    check(evt2.interrupted and 0.08 < evt2.playback_position < 0.4 and mix.pending == 0, f'segment 2 interrupted at {evt2.playback_position:.2f} s, buffer cleared')
    p.stop(); await asyncio.gather(task, return_exceptions=True)
    check(sink.n_segments == 2 and sink.captured_playout_segments == 2, 'two segments captured and finished')
    # the hard cut: a reply streaming when the set starts, and a reply that starts while the floor is closed
    print('    hard cut through the Floor', flush=True)
    now = [0.0]; m = FakeModel(); f = Floor(m, now=lambda: now[0]); f.on_event(session('rest', count=10))
    src = FakeSource(); p = CuePlayer(bank=FakeBank({}), source=src); mix = p.attach_mixer(); task = asyncio.create_task(p.run())
    sink = MixerAudioOutput(mix, lead_s=0.02, floor=f); f.sink = sink
    frame = lambda: rtc.AudioFrame(tone(300, 0.02, 6000).tobytes(), SAMPLE_RATE, 1, FRAME_SAMPLES)
    for i in range(40): await sink.capture_frame(frame())                  # 0.8 s of a reply, the mixer still has most of it unread
    await asyncio.sleep(0.1); written = mix.n_written; pend = mix.pending
    change = f.on_event(session('active'))                                  # the set starts: Floor -> model.interrupt() + sink.cut()
    check(change == 'close' and m.interrupts == 1 and mix.pending == 0 and mix.n_cleared >= pend - FRAME_SAMPLES and pend > 0.3 * SAMPLE_RATE,
          f'floor close cleared the mixer at once ({pend / SAMPLE_RATE:.2f} s unread dropped), model interrupted')
    for i in range(10): await sink.capture_frame(frame())                  # the tail of the same reply still arrives: dropped, nothing written
    check(mix.n_written == written and sink.n_dropped == 10 and mix.pending == 0 and m.interrupts == 1, 'frames after the close are dropped, not written (no second interrupt for the same reply)')
    sink.flush(); sink.clear_buffer()                                       # the framework's order after its interrupt: the forwarder's finally flushes, then clears
    evt3 = await asyncio.wait_for(sink.wait_for_playout(), 2.0)
    check(evt3.interrupted and 0.05 < evt3.playback_position < 0.5 and sink.n_segments == 1, f'the cut reply reports interrupted at {evt3.playback_position:.2f} s (what was heard)')
    for i in range(5): await sink.capture_frame(frame())                   # a new reply starting while the floor is closed
    check(mix.n_written == written and sink.n_dropped == 15 and m.interrupts == 2 and sink.n_cut == 2, 'a reply that starts closed: every frame dropped and the model interrupted once')
    sink.flush(); evt4 = await asyncio.wait_for(sink.wait_for_playout(), 2.0)
    check(evt4.interrupted and evt4.playback_position == 0 and sink.n_segments == 2, 'it reports interrupted at 0 s')
    f.on_event(session('rest', count=10))
    for i in range(5): await sink.capture_frame(frame())
    sink.flush(); evt5 = await asyncio.wait_for(sink.wait_for_playout(), 2.0)
    check(mix.n_written == written + 5 * FRAME_SAMPLES and not evt5.interrupted and abs(evt5.playback_position - 0.1) < 0.03, 'the floor reopened: frames flow again, the segment drains normally')
    # the hand-over: reply A flushed with audio still playing out, reply B's first frame waits for it, an interrupt lands in between
    for i in range(50): await sink.capture_frame(frame())
    sink.flush(); b = asyncio.create_task(sink.capture_frame(frame())); await asyncio.sleep(0.05)
    sink.clear_buffer(); t0 = time.monotonic()
    try: evt6 = await asyncio.wait_for(sink.wait_for_playout(), 2.0); hang = False
    except asyncio.TimeoutError: evt6 = None; hang = True
    await asyncio.gather(b, return_exceptions=True)
    check(not hang and evt6.interrupted and sink.n_segments == sink.captured_playout_segments == 5 and mix.pending == 0 and b.done(),
          f'clear_buffer during the hand-over: both replies finished in {1000 * (time.monotonic() - t0):.0f} ms, {sink.n_segments} segments, nothing owed, no hang')
    p.stop(); await asyncio.gather(task, return_exceptions=True)


# ---------------- 6. default path ----------------
async def test_default_path():
    print('[6] default path without a mixer: bytes unchanged', flush=True)
    clip = tone(700, 0.3, 9000); src = FakeSource(); recs = []
    p = CuePlayer(bank=FakeBank({'Five': clip}), source=src, on_record=recs.append); task = asyncio.create_task(p.run())
    p.say('Five', 'count'); await asyncio.sleep(0.5); p.stop(); await asyncio.gather(task, return_exceptions=True)
    out = np.concatenate([c for _, c in src.pushes])
    check(p.mix is None and p._pump_task is None and out.tobytes() == clip.tobytes() and recs[0]['status'] == 'played', 'no mixer, no pump, output == clip bytes')


# ---------------- 7. --help ----------------
def test_help():
    print('[7] python -m facetime.worker --voice gemini --help', flush=True)
    r = subprocess.run([sys.executable, '-m', 'facetime.worker', '--voice', 'gemini', '--help'], cwd=ROOT, capture_output=True, text=True, timeout=120)
    ok = r.returncode == 0 and all(s in r.stdout for s in ('--voice', '--persona', '--handlers', '--leave-grace-s', '--latency-probe', 'RTCOACH_LATENCY_PROBE', '--log-caller'))
    ok = ok and 'dev (hot reload' not in r.stdout
    check(ok, f'exit {r.returncode}, {len(r.stdout)} chars of help, probe and caller flags listed, dev not sold as hot reload' + ('' if ok else f'\n{r.stdout[-800:]}\n{r.stderr[-800:]}'))
    r2 = subprocess.run([sys.executable, '-m', 'facetime.worker', '--help'], cwd=ROOT, capture_output=True, text=True, timeout=120)
    check(r2.returncode == 0 and '--latency-probe' in r2.stdout, f'plain --help exits {r2.returncode}')
    r3 = subprocess.run([sys.executable, '-m', 'facetime.worker', '--perception', 'off', '--vision', '--voice', 'gemini', '--help'], cwd=ROOT, capture_output=True, text=True, timeout=120)
    ok3 = r3.returncode == 0 and all(s in r3.stdout for s in ('--perception', '--vision', '--vision-fps', '--floor', '{gated,open}'))
    check(ok3, f'--perception off --vision --voice gemini --help exits {r3.returncode}, perception/vision/floor flags listed' + ('' if ok3 else f'\n{r3.stdout[-600:]}\n{r3.stderr[-600:]}'))


# ---------------- 9. the open floor ----------------
async def test_open_floor():
    print('[9] the open floor (--floor open / --perception off)', flush=True)
    now = [0.0]; m = FakeModel(); f = Floor(m, always_open=True, now=lambda: now[0])
    check(f.open and f.opened_by == 'always' and m.interrupts == 0, 'open from the start, nothing interrupted')
    check(f.ask('greet') == 'spoken' and m.generated == ['greet'], 'an ask before any event is spoken at once')
    check(f.on_event(session('active')) is None and f.open and m.interrupts == 0 and f.n_close == 0, 'a session active event does not close it')
    check(f.ask('mid-set') == 'spoken' and m.generated[-1] == 'mid-set' and f.queue == [], 'an ask during "active" is spoken, not queued')
    check(f.on_event(ev('gesture', name='tpose')) is None and f.on_event(ev('probe', arms_up=True)) is None and f.open and f.n_ignored == 0 and f.n_open == 0, 'a gesture or probe changes nothing')
    now[0] = 100.0
    check(f.tick() is None and f.open and f.on_event(session('rest', count=3)) is None and f.on_event(session('done', done=True)) is None, 'ticks and rest/done change nothing either')
    check(f.on_event(ev('session', state='open', exercise=None, count=0, mode='voice')) is None and f.state == 'open' and f.open, 'the synthetic session open event is recorded as the state, floor still open')
    check(m.input is None and m.interrupts == 0 and f.n_close == 0 and f.n_dropped_asks == 0, 'never a set_input_enabled(False), interrupt or dropped ask')
    # the VoiceLayer: on_caller enables the model input and the tee; the handler greets on the synthetic session event
    class StartModel(FakeModel):
        def __init__(self): super().__init__(); self.started = False; self.start_kw = None
        async def start(self, sink, room=None, participant_identity=None, video=None): self.started = True; self.start_kw = dict(room=room, identity=participant_identity, video=video)
    job = FakeJob(); sm = StartModel(); tee = VideoTee(fps=1.0); asked = []
    def handler(e, say_now, ask_voice):
        if e['type'] == 'session' and e.get('state') == 'open' and e.get('mode') == 'voice': asked.append(ask_voice('Greet the caller and ask what is on the counter.'))
    v = VoiceLayer(job, model=sm, plan=None, handlers=handler, floor_open=True, vision=tee, now=lambda: now[0])
    check(v.floor.always_open and v.floor.open and not tee.enabled, 'layer built with the open floor and the tee (disabled until the session starts)')
    ok_start = await v.on_caller('chert-bridge-x', room=None)
    check(ok_start is True and sm.started and sm.start_kw['video'] is tee and sm.start_kw['identity'] == 'chert-bridge-x' and sm.input is True and tee.enabled,
          'on_caller: model started with the tee as its video input, caller audio enabled, tee enabled')
    v.on_event(ev('session', state='open', exercise=None, count=0, mode='voice'))
    check(asked == ['spoken'] and sm.generated[-1].startswith('Greet the caller'), f'the handler\'s greeting on the session open event is spoken at once: {asked}')
    v.on_event(ev('status', fps_recv=15.0, state='open', exercise=None, count=0, mode='voice', vision_frames=3))
    check(len(sm.generated) == 1 and sm.interrupts == 0 and len(sm.context) == 0, 'a status event asks nothing and feeds no set summary')
    await v.aclose(); check(tee.closed, 'aclose() closes the tee')


# ---------------- 10. the vision tee ----------------
class FakeVisionModel:
    def __init__(self): self.frames = []
    def push_video(self, frame): self.frames.append((time.monotonic(), frame))


class Frame:
    width = 1280; height = 720
    def __init__(self, i): self.i = i


async def test_vision_tee():
    print('[10] the vision tee: 10 fps in, about 1 fps out, nothing before the session', flush=True)
    tee = VideoTee(fps=1.0); model = FakeVisionModel(); pump = asyncio.create_task(tee.pump(model))
    t0 = time.monotonic()
    for i in range(5): tee.offer(Frame(i)); await asyncio.sleep(0.1)                     # a warm job / before the bind: the tee is not enabled
    await asyncio.sleep(0.05)
    check(tee.n_offered == 5 and tee.n_early == 5 and tee.n_queued == 0 and model.frames == [], 'before the model session: 5 frames offered, none queued, none pushed')
    tee.enable(True); n0 = tee.n_offered
    while time.monotonic() - t0 < 3.6: tee.offer(Frame(tee.n_offered)); await asyncio.sleep(0.1)    # about 3 s at 10 fps
    await asyncio.sleep(0.05)
    offered = tee.n_offered - n0; sent = len(model.frames)
    gaps = [b - a for (a, _), (b, _) in zip(model.frames, model.frames[1:])]
    check(28 <= offered <= 34 and 3 <= sent <= 4 and tee.n_sent == sent and tee.n_queued == sent, f'{offered} frames offered in about 3 s, {sent} pushed to the model (about 1 per second)')
    check(all(0.9 <= g <= 1.15 for g in gaps), f'gaps between pushed frames {[round(g, 2) for g in gaps]} s')
    check(tee.size == (1280, 720) and model.frames[0][1].i == 5, 'frame size recorded; the first pushed frame is the first one after enable')
    tee2 = VideoTee(fps=5.0); check(tee2.fps == 2.0 and abs(tee2.interval - 0.5) < 1e-9, '--vision-fps is capped at 2')
    m2 = FakeVisionModel(); p2 = asyncio.create_task(tee2.pump(m2)); tee2.enable(True)
    for i in range(20): tee2.offer(Frame(i)); await asyncio.sleep(0.1)
    await tee2.aclose()
    try: await asyncio.wait_for(p2, 1.0); ended = True
    except asyncio.TimeoutError: ended = False
    check(3 <= len(m2.frames) <= 5 and ended and tee2.closed and not tee2.offer(Frame(99)), f'at 2 fps: {len(m2.frames)} frames in 2 s; aclose() ends the forward loop and later offers are refused')
    await tee.aclose()
    try: await asyncio.wait_for(pump, 1.0); ended = True
    except asyncio.TimeoutError: ended = False
    check(ended, 'the 1 fps pump ended on aclose()')
    # the worker's frames are RGB24 (Perception's format) and the plugin's JPEG encoder cannot convert RGB24: the tee hands over RGBA
    from livekit import rtc
    from livekit.agents.utils import images
    from livekit.plugins.google.realtime.realtime_api import DEFAULT_IMAGE_ENCODE_OPTIONS
    w, h = 1280, 720; rgb = np.zeros((h, w, 3), np.uint8); rgb[..., 1] = 180
    raw = rtc.VideoFrame(w, h, rtc.VideoBufferType.RGB24, rgb.tobytes())
    try: images.encode(raw, DEFAULT_IMAGE_ENCODE_OPTIONS); raw_fails = False
    except Exception: raw_fails = True
    tee3 = VideoTee(fps=1.0); m3 = FakeVisionModel(); p3 = asyncio.create_task(tee3.pump(m3)); tee3.enable(True)
    t0 = time.monotonic(); tee3.offer(raw); t_conv = 1000 * (time.monotonic() - t0); await asyncio.sleep(0.05)
    out = m3.frames[0][1] if m3.frames else None
    try: jpeg = images.encode(out, DEFAULT_IMAGE_ENCODE_OPTIONS) if out is not None else b''
    except Exception as e: jpeg = b''; print(f'  encode of the tee frame failed: {e}')
    check(raw_fails and out is not None and out.type == rtc.VideoBufferType.RGBA and out.width == w and out.height == h and jpeg[:2] == b'\xff\xd8' and len(jpeg) > 1000,
          f'an RGB24 frame (the plugin cannot encode it) leaves the tee as RGBA and encodes to a {len(jpeg)} byte JPEG; conversion {t_conv:.1f} ms')
    await tee3.aclose(); await asyncio.gather(p3, return_exceptions=True)


# ---------------- 11. live vision ----------------
async def test_live_vision(model_id):
    print(f'[11] live: model session with the tee as session.input.video, one 1280x720 frame pushed, then a text turn; model {model_id or "default"}', flush=True)
    if not (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')):
        print('  skip: GEMINI_API_KEY MISSING'); return
    from livekit import rtc
    errors = []; turns = []; src = FakeSource(); p = CuePlayer(bank=FakeBank({}), source=src); mix = p.attach_mixer(); ptask = asyncio.create_task(p.run())
    sink = MixerAudioOutput(mix); tee = VideoTee(fps=1.0)
    gm = GeminiModel(DEFAULT_PERSONA + '\n\nYou can see the caller\'s camera.', model=model_id, on_turn=lambda role, text: turns.append((role, text)))
    t0 = time.monotonic(); await gm.start(sink, video=tee); t_start = time.monotonic() - t0
    gm.session.on('error', lambda e: errors.append(str(getattr(e, 'error', e))))
    check(gm.session.input.video is tee and gm.session._video_sampler is None, 'session.input.video is the tee, the framework sampler is off (the tee samples)')
    gm.set_input_enabled(True); tee.enable(True)
    w, h = 1280, 720; rgb = np.zeros((h, w, 3), np.uint8); rgb[..., 0] = 230; rgb[..., 1] = 40; rgb[..., 2] = 30            # a plain red picture, as the worker's RGB24 stream delivers it
    rgb[h // 3: 2 * h // 3, w // 3: 2 * w // 3] = (250, 250, 250)                                                             # with a white square in the middle
    frame = rtc.VideoFrame(w, h, rtc.VideoBufferType.RGB24, rgb.tobytes())
    kept = tee.offer(frame)
    for _ in range(100):
        if tee.n_sent >= 1: break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.5)                                                # the plugin encodes and sends it on its own task
    fwd = getattr(gm.session, '_forward_video_atask', None)                 # an encode error ends the framework's forward task (the first live run died here on RGB24)
    check(kept and tee.n_sent == 1 and not errors and fwd is not None and not fwd.done(),
          f'one RGB24 frame pulled by the framework and handed to push_video (JPEG); forward task alive {fwd is not None and not fwd.done()}; session errors {errors}')
    t1 = time.monotonic(); hnd = gm.generate('In one short sentence, say hello and name the main colour of the picture you see and the shape in its middle.')
    first = None
    while time.monotonic() - t1 < 15:
        if sink.t_first_frame is not None: first = sink.t_first_frame - t1; break
        await asyncio.sleep(0.005)
    if hnd is not None:
        try: await asyncio.wait_for(hnd, 20)
        except Exception as e: print(f'  speech handle: {type(e).__name__}: {e}')
    await asyncio.sleep(0.3)
    print(f'  session start {t_start:.2f} s; first audio {("%.0f ms" % (1000 * first)) if first is not None else "NONE"} after generate(); {mix.n_written / SAMPLE_RATE:.2f} s of audio; '
          f'tee offered {tee.n_offered} sent {tee.n_sent}; errors {errors}; turns {turns}', flush=True)
    check(first is not None and first < 8.0 and not errors, 'the session still answers after the pushed frame (first audio within 8 s, no error)')
    await gm.aclose(); p.stop(); await asyncio.gather(ptask, return_exceptions=True)


# ---------------- 8. live ----------------
async def test_live(model_id):
    print(f'[8] live turn through GeminiModel + AgentSession (no room) -> mixer sink; model {model_id or "default"}', flush=True)
    if not (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')):
        print('  skip: GEMINI_API_KEY MISSING'); return
    turns = []; src = FakeSource(); p = CuePlayer(bank=FakeBank({}), source=src); mix = p.attach_mixer(); ptask = asyncio.create_task(p.run())
    sink = MixerAudioOutput(mix); gm = GeminiModel(DEFAULT_PERSONA, model=model_id, on_turn=lambda role, text: turns.append((role, text)))
    t0 = time.monotonic(); await gm.start(sink); t_start = time.monotonic() - t0
    gm.set_input_enabled(True)                                              # the floor is open for this test
    t1 = time.monotonic(); h = gm.generate('Say hello in one short sentence.')
    first = None
    while time.monotonic() - t1 < 15:
        if sink.t_first_frame is not None: first = sink.t_first_frame - t1; break
        await asyncio.sleep(0.005)
    if h is not None:
        try: await asyncio.wait_for(h, 20)
        except Exception as e: print(f'  speech handle: {type(e).__name__}: {e}')
    await asyncio.sleep(0.3)
    pushed = np.concatenate([c for _, c in src.pushes]) if src.pushes else np.zeros(1, np.int16)
    print(f'  session start {t_start:.2f} s; first audio frame {("%.0f ms" % (1000 * first)) if first is not None else "NONE"} after generate(); '
          f'{mix.n_written / SAMPLE_RATE:.2f} s of model audio, level {rms_db(pushed):.1f} dBFS RMS (bank target -18); turns logged: {turns}', flush=True)
    check(first is not None and first < 6.0, 'first audio within 6 s through the real AgentSession and the mixer sink')
    check(any(r == 'coach' and t for r, t in turns), 'the model turn was logged as a voice event (coach, text)')
    await gm.aclose(); p.stop(); await asyncio.gather(ptask, return_exceptions=True)


async def main(a):
    test_floor(); test_summary(); await test_layer(); await test_mixer(); await test_sink(); await test_default_path(); test_help()
    await test_open_floor(); await test_vision_tee()
    if a.live: await test_live(a.model)
    if a.live_vision: await test_live_vision(a.model)
    n = len(PASS); ok = sum(PASS)
    print(f'\n{ok}/{n} checks passed' + ('' if ok == n else '  <-- FAILURES'), flush=True)
    return 0 if ok == n else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--live', action='store_true'); ap.add_argument('--live-vision', action='store_true'); ap.add_argument('--model', default=None)
    sys.exit(asyncio.run(main(ap.parse_args())))
