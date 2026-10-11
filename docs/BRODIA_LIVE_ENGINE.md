# Brodia Gemini conversation engine

## Root causes and wiring

The starter remains a fitness app: `starter/persona.md`, `starter/plan.txt`,
`starter/handlers.py`, `SetSummary`, and prerecorded Puck banks are its defaults.
The previous persona fix correctly specialized browser dispatch metadata, but
Gemini still inherited `GEMINI_VOICE`/Puck and `GEMINI_LANGUAGE`. Brodia's interested
stance prohibited contact/meetings, and there was no application rapport state.
Caller transcripts were also dropped before feedback when logging was disabled.

The browser sends `brodia: {scenario, receptivity}` through explicit LiveKit
dispatch. `apply_brodia_dispatch` validates and isolates each job, and disables
the starter plan, perception-driven coaching and handlers. The controller builds
the **same** `facetime.brodia.build_prompt` plus Python-owned private behavior
state. Both Gemini's initial `RealtimeModel(instructions=...)` and
`Agent(instructions=..., tools=...)` receive it. Tests inspect the installed
plugin's actual outbound `LiveConnectConfig.system_instruction`, speech config,
transcription settings, and blocking function declarations—not just a variable.

An empty per-session cue bank preserves the existing single streaming audio
track/mixer but cannot play fitness clips. Brodia's VoiceLayer also ignores
legacy summaries, cue calls and handlers, even if a stray fitness event arrives.
Video capture, tee forwarding, vision-note feedback and interruptions remain.

## Language, voice and timing

Brodia explicitly selects Leda at creation. `BRODIA_GEMINI_VOICE` can intentionally
select Aoede, Achernar or Zephyr; any other voice fails instead of silently falling
back. Legacy `GEMINI_VOICE` and `GEMINI_LANGUAGE` cannot override it. Identity is
fixed for the lifetime of the session, including feedback.

Native-audio Gemini Live does not support a hard language-code constraint.
American-English-only instructions are applied at initial setup; unsupported
`speech_config.language_code` is omitted. Final output transcripts receive a
contextual language assessment. Unexpected non-English speech increments a
diagnostic counter and restores English instructions; a brief English restatement
is requested only if idle, not ending, and no newer caller input has arrived.
At most two corrective generations occur per session. Detection happens **after**
the output, can fail if evaluation is unavailable, and cannot unspeak audio.

The installed LiveKit Gemini adapter finalizes input transcription in
`_mark_current_generation_done`, after generated audio. Ordinary final-transcript
scoring therefore influences **subsequent** responses, never an already spoken
reply. High-impact requests instead use a synchronous Python decision inside the
registered `decide_social_outcome` tool. Its declaration explicitly sets
`Behavior.BLOCKING` (3.8 Live otherwise defaults to nonblocking). The tool returns
the decision and current behavior before Gemini continues its answer. Extended
Thinking models are rejected because they do not support blocking calls.

Gemini is instructed to call the tool for every contact/date/meet-again/continue
request, and `record_social_boundary` before another explicit refusal or exit.
Native Live does not support forcing a named/required tool choice. Thus blocking
is guaranteed **once a call is made**, not a mathematical guarantee that the model
will classify every request or never skip a call. Python never rerolls a resolved
request; live tests must detect any model bypass. Strict prevention of arbitrary
model speech would require a gated transcription-first generation path with
additional latency, rather than claiming asynchronous scoring can fix past audio.

## Rapport and outcomes

`facetime/rapport.py` owns each call's ephemeral score (0–100), configured starting
values (65/40/15), changes capped at ±4, exact turn-ID deduplication and adjacent
positive repetition suppression. Three-point hysteresis smooths five behavior
bands. State and scenarios are never shared between jobs. Scores are simulation
tuning, not measurements of real attraction or confidence, and are not spoken.

`facetime/brodia_live.py` evaluates final caller transcripts asynchronously using
structured Gemini JSON. It supplies scene, stance, eight recent contextual turns,
explicit boundaries and resolved requests—not keyword-only scoring. Character
transcripts are evaluated for language and missed explicit boundaries, not rapport.
Python rejects malformed values; uncertain/unreliable turns, timeouts, unavailable
models and queue overflow produce no score change. A bounded 16-item queue and
four-second per-evaluation deadline prevent blocking streaming. Interim transcripts
never score. The model cannot infer true recognition confidence from transcript
text alone: plausible but incorrect ASR still requires real audio evaluation.

The default evaluator is `gemini-3.5-flash-lite`, configurable independently. One
structured request per final caller/character transcript adds normal token usage;
no new dependency or provider is introduced. If a configured relay only proxies
Live WebSockets, it must also support `generateContent` for this evaluator.

Outcome probability is smoothly interpolated through
`(0,.02),(20,.02),(40,.12),(60,.40),(80,.70),(100,.90)`; difficulty multiplies by
1/.85/.55. Contact/date/meet-again also use scene multipliers .75/.45/1 for
barista/street/park. Conversation history influences the score, appropriateness
and permanent boundaries. `RapportSettings` exposes these starting tuning
parameters/curve (scene modifiers are code defaults). No score guarantees consent.

A decision and random draw are atomic with no await. Accepted decisions are
cached; refusals permanently block rerolls, including date/meet-again synonyms.
Later explicit boundaries override earlier acceptance. Uncertain requests clarify
without a draw; inappropriate requests decline without a draw. All agreements are
fictional; contact uses only `brodia@example.invalid`, never a real number.
Respectful exits can score positively but stop new outcomes and trigger existing
grounded feedback once. Positive rapport never cancels an explicit refusal.

## Audio and privacy

The browser requests mono audio, echo cancellation, noise suppression and automatic
gain control; devices may not honor every preference. It reports actual sampling
and processing settings in DevTools, without device IDs or conversation content.
Local preview is muted (no microphone loopback). Remote playback calls `startAudio`.
No selector/layout redesign, fixed microphone device or unsupported 16 kHz browser
constraint was added: the browser/LiveKit negotiate capture, and the installed
Gemini plugin resamples to mono PCM16 16 kHz with 50 ms input chunks. Gemini output
remains 24 kHz PCM through the existing 20 ms mixer frames/audio queue.

Gemini automatic VAD is explicit: 100 ms prefix padding, 500 ms silence threshold,
and speech-start interruptions. These are provisional tradeoffs, not a claim that
recognition or endpointing is fixed. Test quiet, noisy, Bluetooth and mobile inputs.

Brodia retains raw transcripts in memory for evaluator/feedback, not JSONL,
stdout or the data channel by default. `--log-caller` explicitly opts **both**
sides into transcript logs (and data publishing if enabled). Do not use this for
private real conversations. API evaluation necessarily sends bounded dialogue to
Google or the configured relay; provider retention is separate from local logging.
Consumer tasks are cancelled and history cleared on close. Optional OpenAI voice
fallback remains functional with the shared persona/mixer/feedback; the Gemini
rapport controller is not attached to OpenAI in this change.

## Pose mirror (optional agent video)

`--mirror` (or `BRODIA_MIRROR=1`) makes the worker publish a video track named
`brodia-mirror` (camera source) next to its audio track. Chert's docs say a FaceTime
video call expects the agent to publish audio **and** video; without `--mirror` the
worker is audio-only. The track shows the caller's own newest camera frame,
mirrored like a selfie, with their live MediaPipe pose skeleton (lite model), the
scenario label (e.g. "Park · Neutral") and a small "pose preview" tag. There is no
score, rep count or coaching text. Before any caller video arrives the track shows a
calm "Waiting for your camera" frame; if the video stalls for 3 s it shows "Camera
paused". If the pose model is missing or fails, the raw frame is shown.

```bash
LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off --mirror                 # browser
LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off --mirror --mirror-fps 8  # lighter
```

Flags: `--mirror-fps` (default 10, env `BRODIA_MIRROR_FPS`; pose runs at most once per
output frame, on the newest frame only), `--mirror-shape portrait|landscape` (default
portrait 540x960 for FaceTime; landscape 960x540; env `BRODIA_MIRROR_SHAPE`). It works with
`--perception off`, reads the same received frames as `--vision` / `--vision-notes`,
runs pose and drawing in a worker thread (never on the audio path), and stops when the
job ends. Measured offline on this laptop CPU: about 15–20 ms per frame (pose lite about 12 ms
plus drawing and I420 conversion) from a 1280x720 source, so 10 fps uses about 15–20% of one core.
The browser page shows the agent's video large with your self-view small.

Privacy: mirror frames are processed in memory only. No frame, landmark or composed
image is written to disk or logged; the composed frame goes only to the caller's own
room as the agent's video track.

Offline check: `.venv/bin/python scripts/test_brodia_mirror.py [--video clip.mp4]`
(real-pose check skipped when no video or model is present). Live browser rendering and
whether the FaceTime connector shows the agent's video to the iPhone are not yet tested.

## Character video (`--avatar`)

`--avatar` (or `BRODIA_AVATAR=1`) publishes ONE video track, `brodia-avatar` (camera source),
rendered by `facetime/brodia_avatar.py`:

- **Roleplay:** the partner for the job's scenario from `assets/avatar/brodia-avatars.json`
  (barista = Jess, park = Maya, street = Nadia) on a calm scenario-tinted gradient. The app draws
  her eyes (blink every 2.8–5.5 s), brows and mouth (one dark rounded shape). The mouth cycles
  open shapes while the agent's audio is actually going out (`CuePlayer.speaking()`: a pushed
  frame with real energy within 150 ms, covering the Gemini voice mixed into the cue track) and
  rests in a smile otherwise. Receptivity tweaks the resting face: interested a little warmer,
  uninterested flatter. Jess's glasses are baked into her render; no glasses overlay is ever drawn.
  A small "Jess · Barista" label sits top-left.
- **Feedback:** when the roleplay ends (`FeedbackSession.finished`, the moment the grounded feedback
  is requested) the track switches to Coach Brodie (`brodie-coach.png`, default pose) with a gentle
  idle bob, a livelier bob and small scale pulse while speaking, and a "Coach Brodie" label. The
  coach images are only scaled and positioned, never drawn on. The hype/think poses are loaded and
  selectable (`avatar.coach_pose`), but the worker holds the default pose: the feedback is one
  model response whose transcript only arrives after the audio, so which section (strength vs
  improvement) is being spoken is not known cheaply.
- **With `--mirror`:** the caller's pose mirror (pose lite on the newest caller frame, at most
  `--mirror-fps`) is a rounded inset at the bottom right (~28 % of the width) of the same track;
  no `brodia-mirror` track is published. No inset until caller video arrives or while it is
  stalled. `--mirror` alone is unchanged.

Flags: `--avatar-fps` (default 15, env `BRODIA_AVATAR_FPS`); the shape follows `--mirror-shape`
(portrait 540x960 default, landscape 960x540). One loop per job; rendering and I420 conversion run
in a worker thread, never on the audio path. Measured offline: partner frame ~0.2 ms, coach ~3.5 ms,
partner + inset + I420 ~1 ms (plus pose lite ~12 ms per caller frame with `--mirror`).

Recommended demo command:

```bash
LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off --avatar --mirror --vision-notes
```

Offline: `.venv/bin/python scripts/test_brodia_avatar.py` (sample renders go to
`$BRODIA_AVATAR_OUT`, default `data/tmp/avatars`); `.venv/bin/python -m facetime.brodia_avatar [dir]`
writes a sheet. Live browser/FaceTime rendering of this track is not yet tested.

## Restart and test

Stop the existing worker/selector in their terminals with Ctrl-C. Do not launch
another competing worker under the same dispatch name. From the repository root,
with locally configured credentials, run in two separate terminals:

```bash
LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off
bash scripts/run.sh selector
```

Open `http://127.0.0.1:8080`, select **Barista + Uninterested**, start a fresh room,
allow microphone/camera, and say “Hi, how's your day going?” First reply should be
a brief, reserved barista response in English/Leda, with no fitness coaching.
The named worker is important: the selector creates an explicit `brodia` dispatch.
Optional video-to-Gemini: append `--vision --vision-fps 1`. FaceTime dispatch can
use the same metadata, or supply both `--brodia-scenario` and `--brodia-receptivity`.

FaceTime line, demo-only (P13): the page's **Use for next FaceTime call** stores one
pending selection (120 s TTL) that the next real Chert caller job consumes once. Explicit
browser metadata still wins, and warm jobs never consume it. Live behavior is ⚠️ unverified.
See `docs/P13_NEXT_CALL.md` for the design and the exact live test steps.

Keep the existing keys local. Optional nonsecret settings in `.env.local`:

```bash
BRODIA_GEMINI_VOICE=Leda
BRODIA_EVALUATOR_MODEL=gemini-3.5-flash-lite
BRODIA_RAPPORT_INITIAL='{"interested":65,"neutral":40,"uninterested":15}'
```

Offline checks:

```bash
.venv/bin/python scripts/test_brodia_live_engine.py
.venv/bin/python scripts/test_brodia_gemini.py
.venv/bin/python scripts/test_brodia_config.py
.venv/bin/python scripts/test_brodia_feedback.py
.venv/bin/python scripts/test_brodia_server.py
.venv/bin/python scripts/test_brodia_next_call.py
.venv/bin/python scripts/test_brodia_park_neutral.py
.venv/bin/python scripts/test_brodia_p15_failure_modes.py   # P15 failure/privacy matrix: docs/P15_QA_MATRIX.md
.venv/bin/python scripts/test_voice.py
.venv/bin/python scripts/test_vision_notes.py
.venv/bin/python scripts/test_brodia_mirror.py
.venv/bin/python scripts/test_brodia_avatar.py              # character video (--avatar)
.venv/bin/python scripts/test_brodia_pose_notes.py         # P17-B pose channels + feedback citations
node scripts/test_brodia_browser.cjs
```

The new engine suite includes asset-free voice-only shutdown checks. The legacy
`test_worker_shutdown.py` additionally needs the non-git research model bundle
(`data/models/clf_pose.pt` etc.); its missing fixtures are not a Brodia failure.
Dialogue A–I tests use semantic-evaluation fixtures: they validate plumbing/rules,
not Gemini's live semantic judgment or naturalness.

Opt-in real API smoke test (normal API usage; synthetic audio is macOS-only):

```bash
set -a; source .env.local; set +a
.venv/bin/python scripts/test_brodia_live_smoke.py --synthetic
```

This tests actual input audio, streaming output, evaluator requests, contact-tool
invocation and no reroll without persisting dialogue. It does **not** traverse a
browser/LiveKit room or prove human recognition, voice identity or naturalness.
Use `--wav` with mono 16-bit 16 kHz human audio for a single greeting on other OSes.

Observed in the development runs: Barista + Uninterested and Park + Interested synthetic audio passed,
three final caller turns, zero detected language failures, contact-tool invocation
and no reroll; initial audio arrived approximately 1.1 seconds after the synthetic
greeting's nominal end for Barista (1.4 seconds for Park). Leda was selected in the actual connection configuration.
These are synthetic smoke results, not a human voice-quality or latency
benchmark. No private transcript or recording was retained.

## Pose-based body-language notes (P17-B)

`facetime/vision_notes.py` (worker `--vision-notes`, ~1 fps, MediaPipe pose lite)
judges four coarse channels per sample. Each abstains (`unknown`) when its
landmarks are not visible enough (MediaPipe visibility ≥ 0.6, arms ≥ 0.5) or
are outside the frame, and a state becomes a note only when it holds for 3 of
the last 4 samples (one note per change). The extra channels are judged only
while the orientation sample is `facing_camera`. Sizes are measured in units of
sqrt(frame width × height), so landscape and portrait frames agree.

| Channel | Signals | Rule |
| --- | --- | --- |
| orientation (unchanged) | `facing_camera`, `turned_away`, `out_of_frame` | head yaw ≤ 0.4 facing, ≥ 1.0 turned; shoulder fallback |
| framing | `too_close`, `framing_ok`, `too_far` | ear-to-ear ≥ 0.38 close, 0.08–0.30 ok, ≤ 0.05 far; eye fallback for close (eyes ≥ 0.15), shoulders ≤ 0.12 far |
| arms | `arms_crossed`, `arms_uncrossed` | both elbows and wrists visible and in frame; both wrists ≥ 0.2 half-shoulder-widths past the midline at torso height = crossed, both ≥ 0.2 on their own side = uncrossed |
| lean (sideways only) | `leaning`, `upright` | both hips visible and in frame; shoulder→hip line ≤ 8° upright, ≥ 15° leaning |

Phone framing usually shows only the head and torso. In that framing the
`lean` channel and often the `arms` channel abstain, which is the intended
behaviour. Baseline states (`framing_ok`, `arms_uncrossed`, `upright`) are
counted but noted only when they end a problem state. If an extra channel sees
no sample of its current state for a whole window, it drops that state.

Every 5 samples the worker emits a `vision_summary` event (`Observer.stats()`:
judged sample counts and shares per label, plus the longest stable stretch per
label). `FeedbackSession` (facetime/brodia.py) cites at most two verified lines:

- one strength: facing the camera ≥ 70 %, arms uncrossed ≥ 90 % or framing OK
  ≥ 80 % of at least 8 judged samples.
- one improvement: the longest problem stretch of at least 5 s, given with its
  duration, its time into the call and the nearest caller words.

The prompt states counts, not percentages. With no summary it falls back to
the latest verified notes. When there is no verified video, the feedback is
voice-only and says so. Unverified notes and summaries are never used.

**Not inferred:** emotion, mood, attraction, interest, confidence,
personality, gaze or eye contact, facial expression, and forward slouch (a
front camera cannot see it). The thresholds are first estimates. Only the
synthetic-landmark tests check them; nobody has validated them on real
callers yet.

## Live-call acceptance matrix (pending human testing)

Run every scenario × stance in a fresh room; repeat on desktop and mobile with
quiet/headset and noisy/speaker input. Do not publish recordings without consent.

| Scenario | Interested | Neutral | Uninterested |
| --- | --- | --- | --- |
| Barista | A: compliment, B: contact | C: awkward introduction | D: pressure after refusal |
| Street | Brief introduction/contact | Respect transit/time boundary | F: respectful exit |
| Park | E: reciprocal banter | G: jokes/light flirting | Short, low-interest responses |

For **each cell** record 20 known spoken turns and recognized final transcripts;
word-error rate and meaning-changing errors; user-speech end to first audio p50/p95;
barge-in to silence latency; naturalness (human 1–5); voice/accent consistency;
non-English turns; scenario/stance adherence; tool invoked before each social
decision; repeat refusal consistency; feedback grounding and absence of fitness.
Include H: garbled/quiet speech and I: Spanish input/output recovery in every cell.
Target zero unauthorized agreements/rerolls, zero fitness coaching, all-English
output, no score changes on known unclear speech, and interruptions without stalls.
Compare latency/recognition against the previous build; set measured targets before
claiming improvement. Audition Aoede/Achernar/Zephyr only in **new** sessions.

## Official references checked

- [Google Live capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities): audio format, native language control, VAD and blocking calls.
- [Google Live best practices](https://ai.google.dev/gemini-api/docs/live-api/best-practices): low-latency/audio/transcription considerations.
- [Live API reference](https://ai.google.dev/api/live.md): setup and function-call protocol.
- [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite): configurable structured evaluator.
- [LiveKit Gemini plugin](https://docs.livekit.io/agents/models/realtime/plugins/gemini/): session integration.
- [LiveKit microphone options](https://docs.livekit.io/reference/client-sdk-js/interfaces/AudioCaptureOptions.html): WebRTC capture preferences.
