"""facetime/vision_notes.py (Neil P08/P09) without LiveKit or a phone.

 A. classify() on synthetic landmarks: facing, head in profile, back to the camera, nobody, and the abstain band.
 B. Observer: a state becomes a note only after STABLE_N agreeing samples; a one-sample flicker makes no note; all-unclear
    samples make no note and the summary says video was received but not judged.
 C. Frame-change counters (P08 proof shape): identical frames count 0 changes, alternating frames count each change,
    a repeated frame sequence number is not a new frame.
 D. attach_utterances(): the nearest caller line within 5 s, nothing outside it.
 E. run_for_job() with a fake job: real rtc.VideoFrame RGB24 frames in job.latest, an injected pose; the facing -> turned change
    is emitted as vision_note events; a bound caller with no video gets ONE source_verified=false note and the unavailable summary.
 F. The worker parser accepts --vision-notes / --vision-notes-fps.
 H. The real worker CoachJob (--perception off --vision-notes, events only; scripts/test_worker_shutdown.py's fake room) binds a
    fake caller whose real rtc.VideoFrames change halfway: vision_note events reach the job's sinks, job.vision_observer is set,
    and the caller's leave still ends the job within the grace. Needs the data bundle (as test_worker_shutdown.py).
 G. (optional, --images DIR) the real MediaPipe pose lite model on DIR/portrait.jpg (frontal: facing_camera) and DIR/pose.jpg
    (head in profile: turned_away), then a deliberate change sequence portrait x4 -> profile x4 gives exactly those two notes.
    Needs models/pose_landmarker_lite.task. The two test images are MediaPipe's public assets:
      curl -sSfLO https://storage.googleapis.com/mediapipe-assets/portrait.jpg
      curl -sSfLO https://storage.googleapis.com/mediapipe-assets/pose.jpg

Run:  .venv/bin/python scripts/test_vision_notes.py [--images DIR]
"""
import argparse, asyncio, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import os as _os, tempfile as _tempfile; _os.environ['BRODIA_NEXT_CALL_PATH'] = _os.path.join(_tempfile.mkdtemp(prefix='brodia-test-'), 'next_call.json')  # never touch a real pending P13 selection
import numpy as np
from facetime import vision_notes as vn

PASS = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg, flush=True); PASS.append(bool(cond)); return cond


def lm(nose_x=0.5, ears=(0.45, 0.55), shoulders=(0.35, 0.65), vis=1.0, nose_vis=None, ear_vis=None):
    a = np.zeros((33, 5), np.float32); a[:, 3] = 0.0
    a[vn.NOSE, 0] = nose_x; a[vn.NOSE, 3] = vis if nose_vis is None else nose_vis
    for i, x in zip((vn.L_EAR, vn.R_EAR), ears): a[i, 0] = x; a[i, 3] = vis if ear_vis is None else ear_vis
    for i, x in zip((vn.L_SH, vn.R_SH), shoulders): a[i, 0] = x; a[i, 3] = vis
    return a


FACING = lm()
PROFILE = lm(nose_x=0.58, ears=(0.50, 0.52))           # yaw = 0.07 / 0.01 = 7
MIDDLE = lm(nose_x=0.53)                                # yaw 0.6: the abstain band


def test_classify():
    print('A. classify')
    check(vn.classify(FACING)[0] == 'facing_camera', 'frontal -> facing_camera')
    check(vn.classify(PROFILE)[0] == 'turned_away', 'head in profile -> turned_away')
    check(vn.classify(MIDDLE)[0] == 'unknown', 'half-turned (yaw 0.6) -> unknown (abstain)')
    check(vn.classify(None)[0] == 'out_of_frame', 'no pose -> out_of_frame')
    check(vn.classify(lm(nose_vis=0.1, ear_vis=0.1))[0] == 'turned_away', 'shoulders, no face -> turned_away (back to camera)')
    check(vn.classify(lm(ear_vis=0.1))[0] == 'facing_camera', 'ears hidden: shoulder fallback, centred nose -> facing_camera')
    check(vn.classify(lm(ear_vis=0.1, nose_x=0.6))[0] == 'unknown', 'ears hidden, nose off-centre in the band -> unknown')
    check(vn.classify(lm(ear_vis=0.1, shoulders=(0.49, 0.52)))[0] == 'unknown', 'tiny/far person, no ears -> unknown')


def test_observer():
    print('B. observer stability and abstention')
    o = vn.Observer()
    notes = [o.observe(None, t, seq=t, lm=FACING) for t in range(4)]
    check([n is not None for n in notes] == [False, False, True, False], 'facing becomes a note on the 3rd agreeing sample, once')
    check(notes[2].observed_at == 0.0 and notes[2].source_verified and notes[2].certainty == 'clear', 'observed_at is the first agreeing sample; 3 clear samples -> clear')
    flick = [o.observe(None, t, seq=t, lm=PROFILE if t == 5 else FACING) for t in range(4, 9)]
    check(all(n is None for n in flick), 'a one-sample turn (flicker) makes no note')
    turned = [o.observe(None, t, seq=t, lm=PROFILE) for t in range(9, 14)]
    got = [n for n in turned if n is not None]
    check(len(got) == 1 and got[0].signal == 'turned_away' and got[0].observed_at == 9.0, 'a held turn -> one turned_away note at t=9')
    s = o.summary()
    check('0:00 facing the camera' in s and '0:09 turned away from the camera' in s, f'summary lists both notes: {s[:110]}...')
    m = vn.Observer(); got = [m.observe(None, t, seq=t, lm=lmk) for t, lmk in enumerate([MIDDLE, PROFILE, PROFILE, PROFILE])]
    check(got[3] is not None and got[3].certainty == 'uncertain', 'an unclear sample in the window -> the note is uncertain')
    u = vn.Observer()
    for t in range(10): u.observe(None, t, seq=t, lm=MIDDLE)
    check(not u.notes and 'never clear enough' in u.summary(), 'all-unclear samples: no note, summary says not judged')
    check(vn.Observer().summary() == vn.UNAVAILABLE, 'no samples at all: the unavailable line')


def test_frames():
    print('C. frame-change counters')
    o = vn.Observer(); a = np.zeros((72, 128, 3), np.uint8); b = np.full((72, 128, 3), 200, np.uint8)
    for i in range(5): o.observe(a, i, seq=i, lm=FACING)
    check(o.frame_stats() == dict(samples=5, new_frames=5, changed=0), f'5 identical frames: 0 changed {o.frame_stats()}')
    o2 = vn.Observer()
    for i in range(6): o2.observe(a if i % 2 else b, i, seq=i, lm=FACING)
    check(o2.frame_stats()['changed'] == 5, f'alternating frames: every sample after the first changed {o2.frame_stats()}')
    o3 = vn.Observer()
    for i in range(4): o3.observe(a, i, seq=7, lm=FACING)
    check(o3.frame_stats()['new_frames'] == 1, 'a stalled stream (same seq) counts one new frame')


def test_utterances():
    print('D. attach_utterances')
    notes = [vn.VisionNote(10.0, True, 'facing the camera', 'clear'), vn.VisionNote(40.0, True, 'turned away from the camera', 'clear'),
             vn.VisionNote(12.0, False, 'no caller video received', 'clear')]
    vn.attach_utterances(notes, [(8.5, 'hey, is this seat taken?'), (60.0, 'anyway, bye')])
    check(notes[0].optional_nearby_utterance == 'hey, is this seat taken?', 'line 1.5 s away attached')
    check(notes[1].optional_nearby_utterance is None, 'nothing within 5 s -> None')
    check(notes[2].optional_nearby_utterance is None, 'unverified notes get no utterance')


class FakeJob:
    def __init__(self):
        self.closed = False; self.bound = None; self.latest = None; self.per = None; self.t0 = time.monotonic()
        self.emitted = []; self.vision_observer = None
    def emit(self, type_, **f): self.emitted.append((type_, f))


class FakePose:
    """Returns the landmarks the test put on the frame's first pixel value: 0 -> facing, 255 -> profile."""
    def __call__(self, rgb, t_ms): return (FACING if rgb[0, 0, 0] == 0 else PROFILE), None
    def close(self): pass


async def test_job():
    print('E. run_for_job with a fake job')
    from livekit import rtc
    real = vn.load_pose; vn.load_pose = lambda variant='lite': FakePose()
    def frame(v): return rtc.VideoFrame(64, 36, rtc.VideoBufferType.RGB24, bytes([v]) * (64 * 36 * 3))
    job = FakeJob(); task = asyncio.create_task(vn.run_for_job(job, fps=2.0))
    await asyncio.sleep(0.6); job.bound = 'chert-bridge-test'
    for i in range(14):
        job.latest = (frame(0 if i < 7 else 255), 0, time.monotonic(), time.time(), i + 1)
        await asyncio.sleep(0.5)
    job.closed = True; await asyncio.sleep(0.6); task.cancel()
    kinds = [f['signal'] for t, f in job.emitted if t == 'vision_note']
    check(kinds == ['facing_camera', 'turned_away'], f'deliberate change -> vision_note events {kinds}')
    check(all(f['source_verified'] for t, f in job.emitted), 'every note from real frames is source_verified')
    check(job.vision_observer is not None and job.vision_observer.frame_stats()['changed'] >= 1, f'frame change seen {job.vision_observer.frame_stats()}')
    saved = vn.NO_VIDEO_S; vn.NO_VIDEO_S = 0.6
    job2 = FakeJob(); job2.bound = 'chert-bridge-audio-only'; task = asyncio.create_task(vn.run_for_job(job2, fps=2.0))
    await asyncio.sleep(2.0); job2.closed = True; await asyncio.sleep(0.6); task.cancel(); vn.NO_VIDEO_S = saved
    notes = [f for t, f in job2.emitted if t == 'vision_note']
    check(len(notes) == 1 and notes[0]['source_verified'] is False, 'camera off / audio-only: one unverified no-video note')
    check(job2.vision_observer.summary() == vn.UNAVAILABLE, 'and the summary says visual evaluation unavailable')
    vn.load_pose = real


def test_parser():
    print('F. worker flags')
    from facetime import worker
    a = worker.build_parser().parse_args(['--perception', 'off', '--voice', 'gemini', '--vision-notes', '--vision-notes-fps', '0.5'])
    check(a.vision_notes is True and a.vision_notes_fps == 0.5, '--vision-notes parsed')
    check(worker.build_parser().parse_args([]).vision_notes is False, 'off by default')


async def test_worker_job():
    print('H. worker CoachJob with --vision-notes')
    from livekit import rtc
    import test_worker_shutdown as tws
    from facetime.perception import Config
    real = vn.load_pose; vn.load_pose = lambda variant='lite': FakePose()
    class Ev:
        def __init__(self, f): self.frame = f; self.timestamp_us = int(time.time() * 1e6)
    class Stream:
        def __init__(self): self.closed = False; self.n = 0
        def __aiter__(self): return self
        async def __anext__(self):
            await asyncio.sleep(0.1); self.n += 1
            if self.closed: raise StopAsyncIteration
            v = 0 if self.n < 40 else 255                                  # 4 s facing, then turned away
            return Ev(rtc.VideoFrame(64, 36, rtc.VideoBufferType.RGB24, bytes([v]) * (64 * 36 * 3)))
        async def aclose(self): self.closed = True
    ctx = tws.FakeCtx(tws.FakeRoom()); ctx.job.metadata = '{"chert_call": "fake"}'
    job = tws.make_job(ctx, Config(plan='squats:3'), events_only=True, perception='off')
    job.a.vision_notes = True; job.a.vision_notes_fps = 2.0
    stream = Stream(); job.video_frames = lambda track: stream
    seen = []; orig = job._deliver; job._deliver = lambda ev: (seen.append(ev), orig(ev))
    t = asyncio.create_task(job.run()); await asyncio.sleep(0.3)
    job.on_track_subscribed(tws.FakeTrack(rtc.TrackKind.KIND_VIDEO), tws.FakePub('facetime-remote-video'), tws.P('chert-bridge-h1'))
    await asyncio.sleep(8.5)
    notes = [e for e in seen if e['type'] == 'vision_note']
    check([n['signal'] for n in notes] == ['facing_camera', 'turned_away'], f'vision_note events through the job sinks: {[n["signal"] for n in notes]}')
    check(all(n['source_verified'] and 't' in n and n['observed_at'] <= n['t'] for n in notes), 'notes carry the event clock t; observed_at precedes emission')
    check(job.vision_observer is not None and job.vision_observer.frame_stats()['changed'] >= 1, f'job.vision_observer frame stats {job.vision_observer and job.vision_observer.frame_stats()}')
    t0 = time.monotonic(); job.on_participant_disconnected(tws.P('chert-bridge-h1'))
    try: await asyncio.wait_for(t, 5); exc = None
    except Exception as e: exc = e
    check(exc is None and job.end_reason == 'caller left' and time.monotonic() - t0 < 1.6, f'caller leave still ends the job ({job.end_reason!r}, {exc!r})')
    vn.load_pose = real


def test_images(d):
    print(f'G. real pose lite on {d}')
    import cv2
    from rtcoach.pose import Pose
    still = Pose('lite', video=False); pose = lambda im, t: still(im, t)   # IMAGE mode: unrelated stills, no timestamps
    rgb = {k: cv2.cvtColor(cv2.imread(os.path.join(d, f)), cv2.COLOR_BGR2RGB) for k, f in (('front', 'portrait.jpg'), ('profile', 'pose.jpg'))}
    for k, want in (('front', 'facing_camera'), ('profile', 'turned_away')):
        for flip in (False, True):
            im = rgb[k][:, ::-1].copy() if flip else rgb[k]
            got = vn.classify(pose(im, 0)[0])[0]
            check(got == want, f'{k}{" mirrored" if flip else ""} -> {got}')
    check(vn.classify(pose(np.zeros_like(rgb['front']), 0)[0])[0] == 'out_of_frame', 'black frame -> out_of_frame')
    o = vn.Observer(pose); notes = []
    seq = [rgb['front']] * 4 + [rgb['profile']] * 4
    for i, im in enumerate(seq):
        n = o.observe(im, float(i), seq=i)
        if n: notes.append(n)
    check([n.signal for n in notes] == ['facing_camera', 'turned_away'], f'deliberate change sequence -> {[n.signal for n in notes]}')
    print('  summary:', o.summary())


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--images'); a = ap.parse_args()
    test_classify(); test_observer(); test_frames(); test_utterances(); asyncio.run(test_job()); test_parser()
    if os.path.exists(os.path.join(ROOT, 'data', 'models', 'clf_pose.pt')):
        sys.path.insert(0, os.path.join(ROOT, 'scripts')); asyncio.run(test_worker_job())
    else: print('H. skipped (no data bundle)')
    if a.images: test_images(a.images)
    print(f'{sum(PASS)}/{len(PASS)} passed'); return 0 if all(PASS) else 1


if __name__ == '__main__':
    sys.exit(main())
