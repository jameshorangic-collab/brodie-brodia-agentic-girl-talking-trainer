"""Brodia character video (facetime/brodia_avatar.py + worker --avatar), offline: no LiveKit server, no API calls.

 A. brodia-avatars.json parses; the adapter maps each partner's pixel centres onto the canvas; scenario -> character for all 9 combos
 B. each partner renders at 540x960 and 960x540; Jess (glassesBaked) and the others never load glasses.png
 C. mouth: speaking differs from resting; receptivity variants differ at rest; blinks happen every few seconds
 D. coach: the three pose files load; coach pixels are the scaled source unmodified (compared with an independent resize)
 E. CuePlayer.speaking(): an audible pushed frame -> True for ~150 ms; silence -> False
 F. worker --avatar --perception off (fake room): exactly ONE video track "brodia-avatar"; the mouth follows the player signal;
    partner -> Coach Brodie when FeedbackSession.finished; clean end on the caller's leave, no frames after, no leaked task
 G. worker --avatar --mirror: still ONE video track; the pose inset appears once caller video exists
 H. per-frame timing (partner, coach, partner + inset, + I420 conversion)
Sample renders go to $BRODIA_AVATAR_OUT (default data/tmp/avatars).

Run:  .venv/bin/python scripts/test_brodia_avatar.py
"""
import asyncio, json, os, sys, tempfile, time, types
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
os.environ['BRODIA_NEXT_CALL_PATH'] = os.path.join(tempfile.mkdtemp(prefix='brodia-test-'), 'next_call.json')
from PIL import Image
from livekit import rtc
from facetime import brodia_avatar as ba
from facetime import brodia_mirror as bm
from facetime.brodia import SCENARIOS, RECEPTIVITIES, FeedbackSession

OUT = os.environ.get('BRODIA_AVATAR_OUT', os.path.join(ROOT, 'data', 'tmp', 'avatars'))
PASS = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg, flush=True); PASS.append(bool(cond)); return cond


def save(img, name):
    os.makedirs(OUT, exist_ok=True); Image.fromarray(img).save(os.path.join(OUT, name))


def region(img, cx, cy, rx, ry):
    return img[int(cy - ry):int(cy + ry), int(cx - rx):int(cx + rx)].astype(int)


def test_spec():
    print('[A] JSON + adapter + scenario -> character', flush=True)
    spec = ba.load_spec()
    check(set(spec['characters']) == {'maya', 'jess', 'nadia'} and spec['characters']['jess']['glassesBaked'] is True, 'three partners; jess glassesBaked')
    f = ba.partner_features(spec['characters']['maya'], spec, 2.0, 10, 20)
    check(f['eyes'][0][:2] == (10 + 268 * 2, 20 + 232 * 2) and f['eyes'][0][2] == spec['sizes']['eye']['rx'] * 2 and f['mouth'][:2] == (10 + 310 * 2, 20 + 284 * 2),
          'adapter: pixel centres scaled and offset, sizes scaled')
    want = {'barista': 'jess', 'park': 'maya', 'street': 'nadia'}; got = {}
    for s in SCENARIOS:
        for r in RECEPTIVITIES:
            av = ba.CharacterAvatar(s, r, spec=spec); got[(s, r)] = av.name
    check(all(got[(s, r)] == want[s] for s in SCENARIOS for r in RECEPTIVITIES) and len(got) == 9, f'9 combos -> {sorted(set(got.values()))}')
    check(ba.character_for('unknown', spec) == 'maya', 'unknown scenario -> the park character')
    return spec


def test_partners(spec):
    print('[B] partners render; glasses never pasted', flush=True)
    opened = []; orig = Image.open
    def spy(fp, *a, **k): opened.append(os.path.basename(str(fp))); return orig(fp, *a, **k)
    Image.open = spy
    try:
        for s in SCENARIOS:
            for shape, (W, H) in ba.SIZES.items():
                av = ba.CharacterAvatar(s, 'neutral', (W, H), spec=spec); img = av.frame()
                check(img.shape == (H, W, 3) and img.dtype == np.uint8 and img.std() > 10, f'{av.name} {shape}: {W}x{H}')
        av = ba.CharacterAvatar('barista', 'neutral', spec=spec); av.phase = 'coach'; av.frame(); av.phase = 'partner'; av.frame()
    finally:
        Image.open = orig
    check('glasses.png' not in opened and 'brodia-jess.png' in opened, f'glasses.png never loaded (opened: {sorted(set(opened))})')
    check(not any(hasattr(av, k) for k in ('glasses', 'glasses_crop')), 'no glasses overlay attribute on the partner renderer')


def test_mouth_blink(spec):
    print('[C] mouth, receptivity, blink', flush=True)
    for s in SCENARIOS:
        av = ba.CharacterAvatar(s, 'neutral', spec=spec); now = av.t0 + 0.01
        cx, cy, w, h = av.feat['mouth']
        rest = av.frame(now=now, speaking=False, blink=False); talk = av.frame(now=now, speaking=True, blink=False)
        d = np.abs(region(rest, cx, cy + h, w, 2 * h) - region(talk, cx, cy + h, w, 2 * h)).sum()
        check(d > 1000, f'{av.name}: speaking mouth differs from resting ({d})')
        save(rest, f'{av.name}-resting.png'); save(av.frame(now=now, mouth='wide', blink=False), f'{av.name}-speaking.png')
    shapes = set(); av = ba.CharacterAvatar('park', 'neutral', spec=spec)
    for i in range(40): shapes.add(av.mouth_shape(True, av.t0 + i * 0.12))
    check(len(shapes) >= 3 and 'rest' not in shapes, f'open shapes cycle while speaking: {sorted(shapes)}')
    imgs = {}
    for r in RECEPTIVITIES:
        av = ba.CharacterAvatar('barista', r, spec=spec); imgs[r] = av.frame(now=av.t0 + 0.01, blink=False); save(imgs[r], f'jess-{r}.png')
    cx, cy, w, h = av.feat['mouth']; bx, by, bw, bh = av.feat['brows'][0]
    dm = np.abs(region(imgs['interested'], cx, cy, w, 2 * h) - region(imgs['uninterested'], cx, cy, w, 2 * h)).sum()
    db = np.abs(region(imgs['interested'], bx, by, bw, 3 * bh) - region(imgs['uninterested'], bx, by, bw, 3 * bh)).sum()
    check(dm > 500 and db > 500, f'receptivity changes the resting mouth ({dm}) and brows ({db})')
    import random
    av = ba.CharacterAvatar('street', 'neutral', spec=spec, rng=random.Random(3)); closed = 0
    for i in range(int(15 * 12)):
        now = av.t0 + i / 15; av.frame(now=now)
        if av.blinking(now): closed += 1
    check(av.blinks >= 2 and closed >= 2, f'{av.blinks} blinks in 12 s at 15 fps ({closed} closed frames)')
    ex, ey, rx, ry = av.feat['eyes'][0]; now = av.t0 + 0.01
    o = av.frame(now=now, blink=False); c = av.frame(now=now, blink=True); save(c, 'nadia-blink.png')
    check(np.abs(region(o, ex, ey, rx * 1.5, ry * 1.5) - region(c, ex, ey, rx * 1.5, ry * 1.5)).sum() > 1000, 'a blink closes the eyes')


def test_coach(spec):
    print('[D] coach poses, pixels unmodified', flush=True)
    for shape in ('portrait', 'landscape'):
        av = ba.CharacterAvatar('park', 'neutral', ba.SIZES[shape], spec=spec); av.phase = 'coach'
        for pose in ('default', 'hype', 'think'):
            img = av.frame(pose=pose, still=True)
            if shape == 'portrait': save(img, f'coach-{pose}.png')
            src = Image.open(os.path.join(ba.PARTS, spec['coach']['poses'][pose]['file'])).convert('RGBA')
            side = av.coach_box; x, y = av.coach_layout(0, 0)
            bg = Image.fromarray(av.coach_bg).convert('RGBA'); sprite = src.resize((side, side), Image.LANCZOS)
            want = np.array(Image.alpha_composite(bg.crop((x, y, x + side, y + side)), sprite).convert('RGB')).astype(int)
            H, W = img.shape[:2]; x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + side, W), min(y + side, H)
            got = img[y0:y1, x0:x1].astype(int); want = want[y0 - y:y1 - y, x0 - x:x1 - x]
            diff = np.abs(got - want)
            check(diff.max() <= 2, f'{shape} coach {pose}: sprite region equals the scaled source over the backdrop (max diff {diff.max()})')
    sp = av.frame(speaking=True, now=av.t0 + 0.3); id_ = av.frame(speaking=False, now=av.t0 + 0.3)
    check(sp.shape == id_.shape, 'coach animates while speaking (bob/scale) without errors')


def test_player_signal():
    print('[E] CuePlayer.speaking()', flush=True)
    from facetime.audio_out import CuePlayer, CueBank
    class Src:
        async def capture_frame(self, f): pass
        async def wait_for_playout(self): pass
    pl = CuePlayer(bank=CueBank.disabled(), source=Src())
    pl._frame(np.zeros(480, np.int16)); s0 = pl.speaking()
    pl._frame((np.sin(np.arange(480) / 5) * 8000).astype(np.int16)); s1 = pl.speaking()
    pl.last_voice_t -= 0.2; s2 = pl.speaking()
    check(not s0 and s1 and not s2, f'silence -> {s0}; voice frame -> {s1}; 200 ms later -> {s2}')


class RGBFrame:
    def __init__(self, v):
        self.width, self.height = 640, 360; self.type = rtc.VideoBufferType.RGB24
        self.data = np.full((360, 640, 3), v, np.uint8).tobytes()


class FakeVoice:
    def __init__(self): self.feedback = FeedbackSession(); self.closed = False; self.model = None; self.started = False
    async def run(self):
        while True: await asyncio.sleep(1)
    async def aclose(self): self.closed = True


async def run_worker(mirror):
    import test_worker_shutdown as tws
    from facetime import worker
    from facetime.perception import Config
    from test_brodia_mirror import fake_landmarks
    published = []
    class Local(tws.FakeLocal):
        async def publish_track(self, track, opts): published.append((track, opts))
    room = tws.FakeRoom(); room.local_participant = Local()
    ctx = tws.FakeCtx(room); ctx.job.metadata = json.dumps({'chert_call': 'fake'})
    elog = os.path.join(tempfile.mkdtemp(prefix='brodia-avatar-'), 'events.jsonl')
    job = tws.make_job(ctx, Config(plan='squats:3'), perception='off', event_log=elog)
    a = job.a; a.avatar = True; a.avatar_fps = 15.0; a.mirror = mirror; a.mirror_fps = 10.0; a.mirror_shape = 'portrait'
    a.brodia_scenario = 'barista'; a.brodia_receptivity = 'interested'
    poses = []
    def fake_pose(rgb, t): poses.append(t); return fake_landmarks(), None
    orig_loader = bm.load_pose; bm.load_pose = lambda variant='lite': fake_pose
    captured = []; orig_cap = rtc.VideoSource.capture_frame
    def cap(self, frame, *x, **k): captured.append((frame.width, frame.height)); return orig_cap(self, frame, *x, **k)
    rtc.VideoSource.capture_frame = cap
    insets = []; orig_frame = ba.CharacterAvatar.frame
    def spy(self, *x, **k): insets.append(k.get('inset') is not None); return orig_frame(self, *x, **k)
    ba.CharacterAvatar.frame = spy
    class Stream(tws.FakeVideoStream):
        async def __anext__(self):
            ev = await super().__anext__(); ev.frame = RGBFrame(60 + self.n % 100); return ev
    stream = Stream(fps=15.0); job.video_frames = lambda track: stream
    tag = '--avatar --mirror' if mirror else '--avatar'
    try:
        t = asyncio.create_task(job.run()); await asyncio.sleep(0.05)
        job.voice = FakeVoice()             # (voice off in these tests) the FeedbackSession the avatar watches
        await asyncio.sleep(0.75)
        vids = [(tr, o) for tr, o in published if isinstance(tr, rtc.LocalVideoTrack)]
        check(len(vids) == 1 and vids[0][0].name == ba.TRACK_NAME and vids[0][1].source == rtc.TrackSource.SOURCE_CAMERA,
              f'{tag}: exactly one video track {[tr.name for tr, _ in vids]}')
        av = job.avatar
        check(av is not None and av.name == 'jess' and av.phase == 'partner' and len(captured) >= 5 and all(c == (540, 960) for c in captured),
              f'{tag}: Jess (barista) at 540x960, {len(captured)} frames before caller video')
        check(not any(insets), f'{tag}: no inset before caller video')
        # the mouth follows the player's speaking signal
        job.player.last_voice_t = time.monotonic() + 0.5; await asyncio.sleep(0.4)
        talking = av._mouth_t > 0
        check(talking and ba.agent_speaking(job), f'{tag}: player speaking -> open mouth shapes ({av._mouth_i})')
        job.player.last_voice_t = -1e9
        job.on_track_subscribed(tws.FakeTrack(rtc.TrackKind.KIND_VIDEO), tws.FakePub('camera'), tws.P('chert-bridge-a1'))
        await asyncio.sleep(1.0)
        if mirror:
            check(any(insets[-5:]) and len(poses) >= 3 and job.mirror is not None, f'{tag}: caller video -> pose inset ({len(poses)} pose runs, inset in last frames)')
        else:
            check(not any(insets) and not poses, f'{tag}: no inset / no pose without --mirror')
        n = av.n
        job.voice.feedback.observe({'type': 'voice', 'role': 'caller', 'text': 'okay goodbye', 't': 3.0})
        await asyncio.sleep(0.3)
        check(job.voice.feedback.finished and av.phase == 'coach' and av.n > n, f'{tag}: feedback started -> Coach Brodie ({av.phase})')
        if mirror:
            img = orig_frame(av, inset=bm.compose(np.full((720, 1280, 3), 90, np.uint8), fake_landmarks(), None, av.inset_size(), True, tag=None), still=True)
            save(img, 'coach-with-mirror-inset.png')
        job.on_participant_disconnected(tws.P('chert-bridge-a1'))
        try: await asyncio.wait_for(t, 5); exc = None
        except Exception as e: exc = e
        check(exc is None and job.closed and job.end_reason == 'caller left' and job.avatar_task.done() and stream.closed,
              f'{tag}: job ended ({job.end_reason}), avatar task done, stream closed')
        n_end = len(captured); await asyncio.sleep(0.3)
        check(len(captured) == n_end, f'{tag}: no frames after the job ended')
        left = [x for x in asyncio.all_tasks() if x is not asyncio.current_task() and not x.done() and 'avatar' in x.get_name()]
        check(not left, f'{tag}: no leaked avatar task')
    finally:
        rtc.VideoSource.capture_frame = orig_cap; bm.load_pose = orig_loader; ba.CharacterAvatar.frame = orig_frame


def test_timing(spec):
    print('[H] per-frame timing', flush=True)
    from test_brodia_mirror import fake_landmarks
    caller = np.zeros((720, 1280, 3), np.uint8); caller[:] = np.linspace(40, 140, 1280, dtype=np.uint8)[None, :, None]
    for shape in ('portrait', 'landscape'):
        av = ba.CharacterAvatar('barista', 'neutral', ba.SIZES[shape], spec=spec)
        inset = bm.compose(caller, fake_landmarks(), None, av.inset_size(), True, tag=None)
        res = {}
        for name, kw, phase in (('partner', {}, 'partner'), ('coach', {}, 'coach'), ('partner+inset', dict(inset=inset), 'partner')):
            av.phase = phase; av.frame(speaking=True, **kw); t = time.perf_counter(); n = 40
            for i in range(n): av.frame(speaking=bool(i % 2), **kw)
            res[name] = (time.perf_counter() - t) / n * 1000
        av.phase = 'partner'; t = time.perf_counter()
        for i in range(20): bm.to_video_frame(av.frame(speaking=True, inset=inset))
        res['partner+inset+I420'] = (time.perf_counter() - t) / 20 * 1000
        print('        ' + shape + ': ' + ', '.join(f'{k} {v:.1f} ms' for k, v in res.items()), flush=True)
        check(max(res.values()) < 40, f'{shape}: every frame well under the 66 ms budget at 15 fps')
        if shape == 'portrait': save(av.frame(speaking=True, inset=inset, mouth='medium', blink=False), 'jess-with-mirror-inset.png')
        else: save(av.frame(inset=inset, blink=False), 'jess-landscape-inset.png')


async def main():
    spec = test_spec(); test_partners(spec); test_mouth_blink(spec); test_coach(spec); test_player_signal()
    print('[F] worker --avatar', flush=True); await run_worker(False)
    print('[G] worker --avatar --mirror', flush=True); await run_worker(True)
    test_timing(spec)
    print(f'        sample renders in {OUT}', flush=True)
    n = len(PASS); ok = sum(PASS); print(f'\n{ok}/{n} checks passed' + ('' if ok == n else '  <-- FAILURES'), flush=True)
    return 0 if ok == n else 1


if __name__ == '__main__':
    rc = asyncio.run(main()); sys.stdout.flush(); os._exit(rc)
