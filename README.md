# Brodia

**Practice approaching a stranger on a live call, then get coaching grounded in what you actually said.**

Built at IvyHacks 2026 (Penn, Oct 10–11) for the "Beat Muse" prompt: a realtime video AI agent that lives on
FaceTime, with no app to download, built on Chert and the Brodie SDK.

## Why

Advice about approaching people is usually text you read. You can't rehearse your delivery that way, and rehearsing
on real strangers puts them on the spot. Instead of a general-purpose call agent, Brodia focuses on one vertical,
practising social approaches:

- **No download.** Pick a scene on a small web page, then talk over a browser call or a FaceTime call.
- **Realistic, bounded counterpart.** The AI plays a fictional adult with a setting, a mood and boundaries. Being
  persistent never wins: a refusal is permanent for the rest of the call.
- **Grounded feedback.** When you end the round, the coach gives 2 strengths, 2 improvements and 1 thing to try next
  time, quoting your own words. It mentions visible presentation only when a verified video observation exists.

## The 3×3 grid

Pick one scenario and one receptivity. Each of the nine combinations is a separate, validated configuration
(`facetime/brodia.py`).

| Scenario | Interested | Neutral | Uninterested |
| --- | --- | --- | --- |
| **Barista**: at work; friendly, but her job and time come first | warm, open to a short chat | polite, cautious | reserved, brief; may end it |
| **Street**: an adult passerby in transit; very brief | warm, open to a short chat | polite, cautious | reserved, brief; may end it |
| **Park**: relaxing, with time for low-pressure small talk | warm, open to a short chat | polite, cautious | reserved, brief; may end it |

Receptivity changes how much she reciprocates, not whether you "win". For "uninterested", the best outcome is a
respectful exit, and the coach gives credit for it.

## How it works

```text
 web/index.html (selector, 127.0.0.1:8080)
        |  POST /api/session {scenario, receptivity}
        v
 facetime/brodia_server.py ── explicit LiveKit dispatch: agent "brodia",
        |                     metadata {"brodia": {scenario, receptivity}}
        |                     + short-lived room token for the browser
        v
 LiveKit room brodia-*  <──── browser (mic/camera)  or  FaceTime via Chert connector
        |
        v
 facetime/worker.py (agent "brodia")
   ├─ Gemini Live roleplay (voice Leda, American English), persona from facetime/brodia.py
   ├─ facetime/brodia_live.py: async evaluator scores each caller turn (structured JSON)
   ├─ facetime/rapport.py: per-call rapport 0–100, behavior bands, request decisions
   │     └─ blocking tools decide_social_outcome / record_social_boundary
   └─ on "end practice" / "goodbye": FeedbackSession -> 2 strengths, 2 improvements, 1 next try
```

1. **Selector.** `web/index.html` shows the grid. `facetime/brodia_server.py` creates a fresh room, dispatches the
   `brodia` agent into it with the selection as job metadata, and returns a 10-minute token. LiveKit credentials stay
   on the server and never reach the browser.
2. **Per-call setup.** The worker validates the metadata and switches off the starter's fitness plan, perception
   coaching, handlers and cue clips for that job. The same prompt goes into both the Gemini session setup and the agent.
3. **Roleplay.** Gemini Live voices the character. After each final caller transcript, a separate structured Gemini
   call (`gemini-3.5-flash-lite` by default) rates the turn in context. Python then moves the rapport score by at most
   ±4 per turn. Duplicates and repeated compliments are ignored. Uncertain turns, timeouts and evaluator errors
   change nothing. The score shapes the character's tone and is never spoken.
4. **Social decisions.** Requests for contact, a date, meeting again or continuing go through a **blocking** tool.
   Python makes the decision (based on rapport, receptivity and scene) before Gemini continues speaking. Refusals are
   cached, so rephrasing the same ask doesn't get a second roll. Any fictional "contact" is `brodia@example.invalid`.
5. **Feedback.** When the caller ends the round, the agent switches once into a coach voice, quotes the caller's last
   lines, and abstains from anything visual unless the video-notes module marked an observation as verified.

Engine details, tuning curves and known limits are in [docs/BRODIA_LIVE_ENGINE.md](docs/BRODIA_LIVE_ENGINE.md).

## Setup

You need macOS or Linux, Python 3.12, [uv](https://docs.astral.sh/uv/), a LiveKit Cloud project and a Gemini API key
with Live access.

```bash
bash scripts/install.sh          # venv (Python 3.12), CPU torch, requirements, starter models and data bundle
cp .env.example .env.local       # then fill it in; .env.local is gitignored
```

Variables in `.env.example` (names only; keep values in `.env.local`):

| Variable | Purpose |
| --- | --- |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | your LiveKit Cloud project |
| `AGENT_NAME` | dispatch name of the worker (`brodia`) |
| `GEMINI_API_KEY`, `GEMINI_LIVE_MODEL` | Gemini Live access and model |
| `GEMINI_VOICE` | starter voice; Brodia ignores it |
| `BRODIA_GEMINI_VOICE` | Brodia's voice: Leda (default), Aoede, Achernar or Zephyr |
| `BRODIA_EVALUATOR_MODEL` | model for per-turn rapport evaluation |
| `BRODIA_RAPPORT_INITIAL` | starting rapport per receptivity (default 65/40/15) |
| `OPENAI_API_KEY` | optional fallback voice only |

`scripts/run.sh` loads `.env.local` for every command below.

## Run it

### Browser practice

Two terminals:

```bash
LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off   # worker
bash scripts/run.sh selector                                                   # selector UI
```

Open <http://127.0.0.1:8080>, pick a scenario and receptivity, press **Start practice**, and allow the microphone
and camera. Say "end practice" or "goodbye" to get feedback. Use a fresh room for each try (the selector does this
for you). To send video to Gemini as well, add `--vision --vision-fps 1` to the worker command.
Optional: add `--mirror` to the worker command to make the partner publish a video track showing your own camera with your
live pose skeleton (a pose preview; frames are not stored). See [docs/BRODIA_LIVE_ENGINE.md](docs/BRODIA_LIVE_ENGINE.md#pose-mirror-optional-agent-video).
Optional: add `--avatar` (env `BRODIA_AVATAR=1`) to publish the partner's character video instead: Jess (barista),
Maya (park) or Nadia (street), blinking and talking in sync with the agent's audio, then Coach Brodie for the feedback.
With `--avatar --mirror` your pose mirror becomes a small inset in that one video track. Recommended demo command:

```bash
LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off --avatar --mirror --vision-notes
```

See [docs/BRODIA_LIVE_ENGINE.md](docs/BRODIA_LIVE_ENGINE.md#character-video---avatar).

### Real FaceTime on the shared Chert line

This path uses Chert's [FaceTime CLI](https://docs.trychert.com/facetime-cli/quickstart) (`@trychert/facetime`). Run it
only inside our slot. Install it once with `npm install -g @trychert/facetime && chert login` (Node 22.12+, 24 or 26).

```bash
LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off   # Terminal A: worker first
bash scripts/run.sh chert                                                      # Terminal B: doctor, then chert dev --agent brodia
```

Wait for `"brodia" joined a waiting room`, then call the shared address with FaceTime Audio. To pick the scenario,
add `--brodia-scenario barista --brodia-receptivity uninterested` to the worker, or use **Use for next FaceTime call**
in the selector. To release the line: hang up, wait for `Call ended`, press Ctrl+C in Terminal B, and wait for
`Stopped`. Full steps are in [docs/FACETIME_CHERT.md](docs/FACETIME_CHERT.md).

### Offline checks (no API calls)

```bash
.venv/bin/python scripts/test_brodia_live_engine.py
.venv/bin/python scripts/test_brodia_gemini.py
.venv/bin/python scripts/test_brodia_config.py
.venv/bin/python scripts/test_brodia_feedback.py
.venv/bin/python scripts/test_brodia_server.py
node scripts/test_brodia_browser.cjs
```

The complete list is in the engine guide. One opt-in smoke test does call the real API:
`scripts/test_brodia_live_smoke.py --synthetic` (synthetic audio is macOS-only).

## Status (as of 2026-10-11)

| Area | State | Evidence |
| --- | --- | --- |
| 9 configurations, prompt, selector dispatch contract, feedback prompt, rapport and decision rules | Tested offline | unit tests above; tests inspect the real outbound Gemini config |
| Gemini Live engine against the real API | Synthetic smoke test passed | Barista + Uninterested and Park + Interested: English, Leda, contact tool called, no reroll ([engine guide](docs/BRODIA_LIVE_ENGINE.md)) |
| Browser call with a human, all 9 cells | **Pending** | acceptance matrix in the engine guide is not yet filled in |
| Shared Chert line (`bash scripts/run.sh chert`) | **Pending** | runbook in [FACETIME_CHERT.md](docs/FACETIME_CHERT.md); a real call is not done yet |
| Visual feedback from caller video | Code merged, **not live-verified** | `--vision-notes` labels facing / turned away / out of frame; thresholds come from still images |

Known limits:

- FaceTime Video on the shared Chert line is undocumented for the hackathon CLI
  ([feasibility notes](docs/FACETIME_VIDEO_FEASIBILITY.md)). There is also no documented way to tie a web selection
  to one specific shared-line caller.
- Language and boundary checks run after a reply has been spoken. They correct the next turn, not the one already
  said. Blocking decisions apply only once Gemini actually calls the tool.

## Responsible design

- **Fictional adults only.** Every character is an adult, the prompt forbids playing a minor or claiming to be a real
  person, and contact details are always fake (`brodia@example.invalid`).
- **Boundaries hold.** Refusals and explicit boundaries are permanent for the call. Positive rapport never cancels
  them. Inappropriate requests are declined without a roll. No score guarantees consent.
- **No emotion or attraction inference.** The rapport score is simulation tuning, not a measure of anyone's feelings.
  It is never spoken. Visual notes describe only what is observable (for example, "turned away from the camera").
- **No stored conversations by default.** Transcripts stay in memory for evaluation and feedback and are cleared when
  the call ends. They are not written to logs, stdout or the data channel unless you pass `--log-caller`. Nothing is
  recorded. Note that dialogue is sent to the Gemini API for the roleplay and the evaluator. One exception: on a browser
  call, the game review (your own scored lines, the rapport path, outcomes, verified camera notes and Coach Brodie's
  words) goes over the data channel to that caller only, never to a FaceTime bridge. The page shows it after the call
  and keeps nothing ([facetime/brodia_report.py](facetime/brodia_report.py)).
- **It's practice.** It's for rehearsal, not for getting live advice while you approach real people.

## Built on Brodie

Brodia is a fork of [seraphimlabs-dev/brodie-starter](https://github.com/seraphimlabs-dev/brodie-starter), a
real-time video fitness coach. We reuse its LiveKit worker, audio mixer, Gemini Live voice layer and vision forwarding,
and add explicit `brodia` dispatch, the roleplay persona, the rapport engine and the feedback step. The starter's own
docs are preserved:

- [docs/STARTER_README_ORIGINAL.md](docs/STARTER_README_ORIGINAL.md): the starter's quick-start README as it was before this rewrite
- [docs/STARTER_README.md](docs/STARTER_README.md): full starter setup, troubleshooting, Chert lines
- [docs/STARTER_EVENTS.md](docs/STARTER_EVENTS.md) and [docs/BUILD_ON_BRODIE.md](docs/BUILD_ON_BRODIE.md)

## Credits

- [Brodie starter](https://github.com/seraphimlabs-dev/brodie-starter) by Seraphim Labs
- [Chert](https://docs.trychert.com) for FaceTime connectivity through its FaceTime CLI
- [LiveKit](https://livekit.io) Agents and Cloud
- [Gemini Live API](https://ai.google.dev/gemini-api/docs/live-api/capabilities)

Team: James, Taha, Neil.

## License

The source code in this repository is available under the [MIT License](LICENSE).

The starter's models and thresholds (`clf_pose.pt`, `trigger_lr.json`, `src/rtcoach/thresholds_e3c.json`,
`src/rtcoach/cue_prior.json`) are under a research evaluation licence. They may be used for this hackathon only and
must not be redistributed.
