# Neil's live tests: P08, P09, P11, P12

These need a person, a phone and (for P11/P12) the shared Chert line in our slot. The code side is in `facetime/vision_notes.py`, enabled with `--vision-notes`. **A test passes only from real call evidence, never from registration or generated code.** Paste the log lines named below into the GitHub issue. Never paste keys, tokens, FaceTime links or video.

Setup (once): `bash scripts/install.sh`, then `.env.local` from `.env.example`. Before every terminal: `source .venv/bin/activate && set -a && source .env.local && set +a`

Offline check first (no LiveKit, laptop webcam, 20 s): `python -m facetime.vision_notes --camera 0 --seconds 20`. Face the camera, then turn your head fully sideways for about 5 s. It should print `facing the camera`, then `turned away from the camera`.

Unit tests: `python scripts/test_vision_notes.py` (add `--images DIR` with MediaPipe's `portrait.jpg` and `pose.jpg` to also test the real pose model).

## P08: real caller frames reach the worker (needs James P02)

Terminal A (use James's confirmed P02 command and add the vision flags):
```
python -m facetime.worker --perception off --voice openai --vision --vision-fps 0.5 --vision-notes dev
```
Terminal B: `python -m facetime.mint_token --room neil-p08-try1 --url`. Open the third line on a phone and allow the camera.

**PASS when the log shows:**
- `[worker] bound to ...` and `[worker] first frame WxH`
- `[vision-notes] N samples: N new frames, K visibly changed` with **K > 0 after you deliberately move or cover the camera**, and K close to 0 while the phone sits still
- `[vision] forwarding video to the model at ... fps`
- the deliberate-change test: ask the agent "what am I holding up?" before and after holding up an object. The answer must change correctly. Record what you held and what it said.

**Camera denial:** rejoin a new room, deny the camera, and talk. PASS when `[vision-notes] no caller video 10 s after the bind: visual evaluation unavailable` appears and the voice still works.

## P09: one truthful observation and one abstention (after P08)

Same setup. On camera: face the phone for 10 s, turn your head fully away for 10 s, then step out of frame for 10 s.
- **PASS:** in order, `vision_note` lines for `facing the camera`, `turned away from the camera`, `not visible in the frame`, each about 3 s after the change. The end line `[vision-notes] end: ... summary: ...` lists the same.
- **Abstention test:** turn your head only halfway (about 45°) for 10 s. **PASS** when no new note appears and the `unknown` count rises in the 10-sample status line.
- Repeat once to show it is repeatable. Note any wrong label honestly; the thresholds come from two still images, not real calls.

**H5 handoff to James (P10):** read `job.vision_observer.summary()` at the end of the round, or collect `vision_note` events in the handlers (`event['type'] == 'vision_note'`, fields `observed_at, source_verified, observable_description, certainty, optional_nearby_utterance`). Use `vision_notes.attach_utterances(notes, [(t, text), ...])` with the caller transcript, which runs on the same clock as event `t`. If `job.vision_observer` is None or the summary starts with "Visual evaluation unavailable", feedback is voice-only and must say so.

## P11: real FaceTime Audio (needs James P02 and our slot)

Only inside our assigned slot. Never use `--takeover`.
```
# Terminal A: the worker FIRST, with the exact dispatch name
AGENT_NAME=brodia python -m facetime.worker --perception off --voice openai dev
# Terminal B
chert whoami && chert doctor && chert dev --agent brodia
```
Call the shared address with **FaceTime Audio** and hold a real two-way conversation (at least 3 turns, and interrupt the agent once).
**PASS:** the conversation was heard both ways, `[worker] bound to 'chert-bridge-...'` appeared, and the job ended cleanly after hangup.
**Release (required):** hang up → wait for "Call ended" → Ctrl+C in the chert terminal → wait for `Stopped` → tell the next team and our group chat.

## P12: real FaceTime Video (needs P01 + P08 + P11 and Gary's go-ahead)

Do this only if Gary confirms the line is video-enabled (see `docs/FACETIME_VIDEO_FEASIBILITY.md`). Run the P11 commands with `--vision --vision-fps 0.5 --vision-notes` added, then call with **FaceTime Video**.
- **PASS:** a video track from `chert-bridge-*` binds (`[worker] bound ... video 'facetime-remote-video' ...`), the frame counters change when you move, a correct `vision_note` appears, **and** the caller sees whatever the agent must publish.
- Our worker publishes no outgoing video track today. If Chert requires one, P12 is **BLOCKED** until James and Neil agree on a small `rtc.VideoSource` publisher. If anything external blocks it, mark P12 BLOCKED honestly and keep the browser-video demo as the vision proof.
