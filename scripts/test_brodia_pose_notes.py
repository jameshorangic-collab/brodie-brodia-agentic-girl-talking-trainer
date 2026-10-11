"""P17-B: the extra pose channels in facetime/vision_notes.py and how the end-of-call feedback cites them. No model files needed.

 A. classify_framing / classify_arms / classify_lean on synthetic landmarks: clear positive, clear negative, low visibility or
    off-frame landmarks -> abstain ('unknown'), and nothing extra is judged while the caller is turned away.
 B. Observer: a held problem state becomes ONE note; a one-sample flicker makes none; baseline states (framing_ok,
    arms_uncrossed, upright) are not noted on their own but ARE noted when they end a problem; an extra channel that loses its
    landmarks for a whole window forgets its state; the original orientation notes are unchanged.
 C. stats(): judged counts, shares and the longest stable stretch per label; aspect-ratio handling for the size thresholds.
 D. FeedbackSession: at most 2 verified visual lines (one strength, one improvement with duration, time and the nearby caller
    words), unverified notes and summaries are never used, short stretches are not cited, voice-only when nothing verified.

Run:  .venv/bin/python scripts/test_brodia_pose_notes.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from facetime import vision_notes as vn
from facetime.brodia import FeedbackSession

PASS = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg, flush=True); PASS.append(bool(cond)); return cond


def body(face=0.16, wrists=None, hips=None, vis=1.0, arm_vis=None, hip_vis=None, ear_vis=None, cx=0.5):
    """A frontal head-and-torso pose (image coords, x unmirrored: the person's left side at larger x). face: ear-to-ear width.
    wrists: (left_x, right_x) at y 0.75, elbows below the shoulders; None leaves the arms invisible. hips: (dx, y) hip-midpoint
    offset from the shoulder midpoint and hip height; None leaves the hips invisible."""
    a = np.zeros((33, 5), np.float32)
    def put(i, x, y, v): a[i, 0] = x; a[i, 1] = y; a[i, 3] = v
    put(vn.NOSE, cx, 0.30, vis)
    put(vn.L_EYE, cx + face * 0.2, 0.27, vis); put(vn.R_EYE, cx - face * 0.2, 0.27, vis)
    ev = vis if ear_vis is None else ear_vis
    put(vn.L_EAR, cx + face / 2, 0.29, ev); put(vn.R_EAR, cx - face / 2, 0.29, ev)
    put(vn.L_SH, cx + 0.15, 0.50, vis); put(vn.R_SH, cx - 0.15, 0.50, vis)
    if wrists is not None:
        av = vis if arm_vis is None else arm_vis
        put(vn.L_ELB, cx + 0.17, 0.68, av); put(vn.R_ELB, cx - 0.17, 0.68, av)
        put(vn.L_WR, wrists[0], 0.75, av); put(vn.R_WR, wrists[1], 0.75, av)
    if hips is not None:
        hv = vis if hip_vis is None else hip_vis
        put(vn.L_HIP, cx + 0.10 + hips[0], hips[1], hv); put(vn.R_HIP, cx - 0.10 + hips[0], hips[1], hv)
    return a


OK = body()
CROSSED = body(wrists=(0.40, 0.60))            # left wrist on the right shoulder's side and vice versa, at torso height
OPEN = body(wrists=(0.70, 0.30))
UPRIGHT = body(hips=(0.0, 0.85))
LEANING = body(hips=(0.15, 0.85))              # ~23 degrees from vertical at aspect 1
CLOSE = body(face=0.45)
FAR = body(face=0.04)
TURNED = body(face=0.16, cx=0.5); TURNED[vn.NOSE, 0] = 0.62   # yaw 1.5 -> turned_away


def test_classifiers():
    print('A. classifiers')
    check(vn.classify_all(OK)['framing'][0] == 'framing_ok', 'face 0.16 of the frame -> framing_ok')
    check(vn.classify_all(CLOSE)['framing'][0] == 'too_close', 'face 0.45 -> too_close')
    check(vn.classify_all(FAR)['framing'][0] == 'too_far', 'face 0.04 -> too_far')
    check(vn.classify_all(body(face=0.34))['framing'][0] == 'unknown', 'face 0.34 (between the bands) -> abstain')
    big = body(face=0.9, ear_vis=1.0); big[vn.L_EAR, 0] = 1.2; big[vn.R_EAR, 0] = -0.2   # ears off-frame, eyes 0.36 apart
    check(vn.classify_all(big)['framing'][0] == 'too_close', 'ears off-frame, eyes far apart -> too_close (eye fallback)')
    check(vn.classify_framing(OK, 16 / 9, facing=True)[0] == 'framing_ok' and vn.classify_framing(body(face=0.30), 16 / 9, facing=True)[0] == 'too_close',
          'landscape aspect scales the size (0.30 of the width at 16:9 is 0.40 of sqrt(area))')
    check(vn.classify_all(CROSSED)['arms'][0] == 'arms_crossed', 'wrists past the midline at torso height -> arms_crossed')
    check(vn.classify_all(OPEN)['arms'][0] == 'arms_uncrossed', 'wrists on their own side -> arms_uncrossed')
    check(vn.classify_all(body(wrists=(0.40, 0.60), arm_vis=0.3))['arms'][0] == 'unknown', 'low wrist/elbow visibility -> abstain')
    check(vn.classify_all(body(wrists=(0.40, 0.60)))['arms'][0] == 'arms_crossed' and vn.classify_all(OK)['arms'][0] == 'unknown',
          'no arm landmarks (head-and-torso framing) -> abstain')
    off = body(wrists=(0.40, 0.60)); off[vn.L_WR, 1] = 1.1
    check(vn.classify_all(off)['arms'][0] == 'unknown', 'a wrist below the frame edge -> abstain')
    check(vn.classify_all(body(wrists=(0.40, 0.30)))['arms'][0] == 'unknown', 'one hand across, one at the side -> abstain')
    face_touch = body(wrists=(0.40, 0.60)); face_touch[vn.L_WR, 1] = face_touch[vn.R_WR, 1] = 0.35
    check(vn.classify_all(face_touch)['arms'][0] == 'unknown', 'wrists crossed above the shoulders (hands at the face) -> not arms_crossed')
    mir = CROSSED.copy(); mir[:, 0] = 1.0 - mir[:, 0]
    check(vn.classify_all(mir)['arms'][0] == 'arms_crossed', 'a mirrored frame gives the same answer')
    check(vn.classify_all(UPRIGHT)['lean'][0] == 'upright', 'hips under the shoulders -> upright')
    check(vn.classify_all(LEANING)['lean'][0] == 'leaning', 'hips 23 degrees off vertical -> leaning')
    check(vn.classify_all(body(hips=(0.07, 0.85)))['lean'][0] == 'unknown', '~12 degrees (between the bands) -> abstain')
    check(vn.classify_all(body(hips=(0.15, 0.85), hip_vis=0.2))['lean'][0] == 'unknown', 'hips not visible (phone framing) -> abstain')
    check(vn.classify_all(body(hips=(0.15, 1.05)))['lean'][0] == 'unknown', 'hips below the frame edge -> abstain')
    t2 = TURNED.copy()
    t2[:, :] = body(wrists=(0.40, 0.60), hips=(0.15, 0.85)); t2[vn.NOSE, 0] = 0.62
    a2 = vn.classify_all(t2)
    check(a2['orientation'][0] == 'turned_away' and all(a2[c][0] == 'unknown' for c in vn.EXTRA_CHANNELS), 'turned away: no extra channel is judged')
    check(vn.classify_all(None) == dict(orientation=('out_of_frame', 1.0), framing=('unknown', 0.0), arms=('unknown', 0.0), lean=('unknown', 0.0)),
          'no pose: out_of_frame, extras abstain')


def run(o, seq, t0=0):
    out = []
    for i, lmk in enumerate(seq): out += o.observe_all(None, t0 + i, seq=t0 + i, lm=lmk)
    return out


def test_observer():
    print('B. observer')
    o = vn.Observer()
    got = run(o, [OPEN] * 6)
    check([n.signal for n in got] == ['facing_camera'], f'baseline arms_uncrossed/framing_ok are not noted on their own: {[n.signal for n in got]}')
    got = run(o, [OPEN, CROSSED, OPEN, OPEN, OPEN], 6)
    check(got == [], 'a one-sample arms cross (flicker) makes no note')
    got = run(o, [CROSSED] * 20, 11)
    check([n.signal for n in got] == ['arms_crossed'] and got[0].observed_at == 11.0 and got[0].certainty == 'clear',
          f'held crossed arms -> one arms_crossed note at t=11: {[(n.signal, n.observed_at) for n in got]}')
    check(got[0].observable_description == 'arms crossed in front of the body' and got[0].source_verified, 'plain description, verified')
    got = run(o, [OPEN] * 5, 31)
    check([n.signal for n in got] == ['arms_uncrossed'], 'uncrossing after a crossed stretch IS a note (the change back)')
    st = o.stats()['channels']['arms']
    check(st['longest']['arms_crossed'] == dict(seconds=19.0, start=11.0, end=30.0), f'longest crossed stretch 11..30 s: {st["longest"]["arms_crossed"]}')
    check(st['counts'] == {'arms_uncrossed': 15, 'arms_crossed': 21} and st['judged'] == 36, f'counts {st["counts"]}')
    check(st['share']['arms_crossed'] == 0.58, f'share of judged samples {st["share"]}')
    # losing the arm landmarks for a whole window forgets the state; crossing again is a fresh note
    p = vn.Observer(); run(p, [CROSSED] * 5)
    run(p, [OK] * 5, 5)
    check(p.states['arms'] is None, 'arms out of view for a whole window -> the crossed state is forgotten')
    got = run(p, [CROSSED] * 4, 10)
    check([n.signal for n in got] == ['arms_crossed'], 'crossed again after that -> a new note')
    check(p.stats()['channels']['arms']['longest']['arms_crossed']['seconds'] == 4.0, 'stretches end at the last agreeing sample, not at the gap')
    # framing: too close, then back
    f = vn.Observer(); got = run(f, [CLOSE] * 4 + [OK] * 4)
    check([n.signal for n in got] == ['facing_camera', 'too_close', 'framing_ok'], f'too_close then back -> two framing notes: {[n.signal for n in got]}')
    # low visibility everywhere: only orientation can speak; all-abstain makes no extra note
    lv = vn.Observer(); got = run(lv, [body(wrists=(0.4, 0.6), hips=(0.15, 0.85), arm_vis=0.2, hip_vis=0.2)] * 6)
    check([n.signal for n in got] == ['facing_camera'] and lv.stats()['channels']['arms']['judged'] == 0, 'invisible arms/hips -> no arms/lean notes, 0 judged')
    lean = vn.Observer(); got = run(lean, [LEANING] * 5)
    check([n.signal for n in got] == ['facing_camera', 'leaning'], 'held lean -> one leaning note')
    m = vn.Observer(); got = run(m, [CROSSED, OK, CROSSED, OK, CROSSED, OK, CROSSED])
    check([n.signal for n in got] == ['facing_camera'], 'arms alternating with not-visible (never STABLE_N of WINDOW_N) -> no arms note')
    # the original contract
    r = vn.Observer(); n = r.observe(None, 0, lm=OK); n = r.observe(None, 1, lm=OK); n = r.observe(None, 2, lm=OK)
    check(n is not None and n.signal == 'facing_camera' and set(n.as_dict()) == {'observed_at', 'source_verified', 'observable_description', 'certainty',
          'optional_nearby_utterance', 'signal', 'frame_seq', 'samples'}, 'observe() still returns the orientation VisionNote with the same fields')
    check('arms: arms_crossed' in o.summary() or 'arms:' in o.summary(), 'summary() text mentions the arms channel counts')


def test_aspect():
    print('C. stats and aspect')
    o = vn.Observer(); rgb = np.zeros((90, 160, 3), np.uint8)       # 16:9
    for i in range(4): o.observe_all(rgb, i, seq=i, lm=body(face=0.30))
    check(o.states['framing'] == 'too_close', 'a 16:9 frame: face 0.30 of the width is too_close')
    p = vn.Observer(); rgb = np.zeros((160, 90, 3), np.uint8)       # 9:16 portrait phone
    for i in range(4): p.observe_all(rgb, i, seq=i, lm=body(face=0.30))
    check(p.states['framing'] == 'framing_ok', 'a 9:16 frame: face 0.30 of the width is a comfortable distance')
    s = o.stats()
    check(s['samples'] == 4 and s['first_t'] == 0 and s['last_t'] == 3 and set(s['channels']) == set(vn.CHANNELS), 'stats shape')


def ev_voice(t, text): return {'type': 'voice', 'role': 'caller', 'text': text, 't': t}


def summary_event(o): return dict(type='vision_summary', source_verified=True, **o.stats())


def test_feedback():
    print('D. feedback')
    o = vn.Observer(); notes = run(o, [OPEN] * 20 + [CROSSED] * 21 + [OPEN] * 10, 100)
    fs = FeedbackSession()
    fs.observe(ev_voice(99.0, 'hey, is this seat taken?'))
    for n in notes: fs.observe(dict(type='vision_note', **n.as_dict()))
    fs.observe(ev_voice(121.5, 'so what do you do?'))
    fs.observe(summary_event(o))
    fs.observe(dict(type='vision_note', source_verified=False, observable_description='turned away from the camera', signal='turned_away'))
    fs.observe(dict(type='vision_summary', source_verified=False, channels={'orientation': {'judged': 99, 'counts': {'turned_away': 99},
                                                                                           'share': {'turned_away': 1.0}, 'longest': {'turned_away': {'seconds': 90, 'start': 0, 'end': 90}}}}))
    prompt = fs.observe(ev_voice(160.0, 'ok, bye'))
    vis = fs.visual_observations()
    print('   ', vis)
    check(prompt is not None and len(vis) == 2, 'two verified visual lines')
    check('two strengths, two improvements' in prompt and 'one next-attempt tip' in prompt, 'still 2 strengths, 2 improvements, 1 next-try')
    check(vis[0].startswith('Strength') and 'faced the camera for most of the call' in vis[0], 'strength: faced the camera most of the call')
    check(vis[1].startswith('Improvement') and 'arms crossed for about 20 s' in vis[1] and '0:21 into the call' in vis[1]
          and '"so what do you do?"' in vis[1], 'improvement: arms crossed ~20 s, time from the call start, nearby words')
    check('turned away' not in prompt and '90 s' not in prompt, 'unverified note and unverified summary are never used')
    check('%' not in prompt, 'no percentages in the prompt')
    check(prompt.count('(verified on camera)') == 2, 'exactly the two verified observations are in the prompt')
    # a short problem stretch is not cited (the summary's strength still is); without a summary the verified notes are cited
    o2 = vn.Observer(); notes2 = run(o2, [OK] * 3 + [CROSSED] * 3 + [OPEN] * 3)
    f2 = FeedbackSession()
    for n in notes2: f2.observe(dict(type='vision_note', **n.as_dict()))
    f2.observe(summary_event(o2)); p2 = f2.observe(ev_voice(10, 'end practice'))
    v2 = f2.visual_observations()
    check(len(v2) <= 2 and not any(v.startswith('Improvement') for v in v2), f'a 2 s cross is not cited as an improvement: {v2}')
    check(v2 and v2[0].startswith('Strength') and 'arms crossed' not in p2, f'only the strength is cited: {v2}')
    f5 = FeedbackSession()
    for n in notes2: f5.observe(dict(type='vision_note', **n.as_dict()))
    f5.observe(ev_voice(4.0, 'nice place')); p5 = f5.observe(ev_voice(10, 'end practice')); v5 = f5.visual_observations()
    check(len(v5) == 1 and 'arms crossed in front of the body' in v5[0] and '"nice place"' in v5[0] and v5[0] in p5,
          f'no summary: the latest verified problem note is cited with nearby words: {v5}')
    # no verified video: voice-only
    f3 = FeedbackSession(); f3.observe(dict(type='vision_note', source_verified=False, observable_description='no caller video received', signal='no_video'))
    p3 = f3.observe(ev_voice(5, 'end practice'))
    check('No verified visual observation is available' in p3 and 'voice-only' in p3 and f3.visual_observations() == [], 'no video -> voice-only line')
    # stretch starting on an uncertain note is not cited
    o4 = vn.Observer()
    notes4 = run(o4, [OPEN] * 10 + [body(wrists=(0.40, 0.60))] * 10)
    f4 = FeedbackSession()
    for n in notes4:
        d = n.as_dict()
        if d['signal'] == 'arms_crossed': d['certainty'] = 'uncertain'
        f4.observe(dict(type='vision_note', **d))
    f4.observe(summary_event(o4))
    check(not any(v.startswith('Improvement') for v in f4.visual_observations()), 'a stretch that began on an uncertain note is not cited')


def main():
    test_classifiers(); test_observer(); test_aspect(); test_feedback()
    ok = sum(PASS); print(f'{ok}/{len(PASS)} passed'); return 0 if ok == len(PASS) else 1


if __name__ == '__main__':
    sys.exit(main())
