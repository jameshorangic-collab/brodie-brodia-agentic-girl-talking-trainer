# P15 QA matrix: failure modes, privacy and security

Branch `agent/taha-p15-failure-qa`, 2026-10-11. **PASS** means verified offline by an automated test in
this repo. It does not mean verified in a live LiveKit/Gemini call. **PENDING-MANUAL** cases need a human
with a browser, mic, camera and credentials. **FAIL** is a confirmed defect, with the suggested fix listed under Findings.

Offline suite (no credentials, no network except 127.0.0.1):

```bash
.venv/bin/python scripts/test_brodia_p15_failure_modes.py   # new: P15 cases below
.venv/bin/python scripts/test_brodia_live_engine.py
.venv/bin/python scripts/test_brodia_gemini.py
.venv/bin/python scripts/test_brodia_config.py
.venv/bin/python scripts/test_brodia_feedback.py
.venv/bin/python scripts/test_brodia_server.py
.venv/bin/python scripts/test_brodia_park_neutral.py
.venv/bin/python scripts/test_voice.py
.venv/bin/python scripts/test_vision_notes.py
node scripts/test_brodia_browser.cjs
# needs the non-git model bundle (data/models, models/*.task):
.venv/bin/python scripts/test_worker_shutdown.py
```

## Automated (offline) cases

| ID | Case | Result | Evidence / reproduction |
| --- | --- | --- | --- |
| A-01 | Second call gets its own config; no stale leak from call 1 (args, persona, rapport score, boundaries, history, feedback transcript) | PASS | `StaleStateAcrossCalls` runs the real `worker.entrypoint` twice (barista/uninterested, then park/interested) on shared prewarmed args. It checks that the args are deep-copied and the prewarm args are untouched. It then builds both voice layers, poisons call 1's state, and asserts call 2 starts fresh. |
| A-02 | No-video path: feedback is voice-only and says visual evaluation was unavailable | PASS (after fix F-1) | `NoVideoFeedback`: an unverified `no caller video received` note is ignored. The prompt says "voice-only" and asks the coach to say once that visual cues were not evaluated, with no body-language claims. VoiceLayer speaks feedback exactly once. |
| A-03 | Zero/short transcript feedback is honest | PASS | `test_zero_transcript_feedback_is_honest`; `test_brodia_feedback.py` (goodbye alone is evidence). |
| A-04 | Graceful exit/disconnect cleanup (connect failure, room deleted, caller leaves; idempotent `aclose`) | PASS | `test_brodia_live_engine.py::test_brodia_shutdown_without_research_assets`, `test_worker_shutdown.py` (21/21 with model bundle), `test_vision_notes.py` caller-leave. Controller `aclose` clears history/queue/dedupe ids (`test_context_validation_failure_and_cleanup`, A-01). |
| A-05 | Browser "End call" disconnects and clears media | PASS (mocked DOM/LiveKit) | `node scripts/test_brodia_browser.cjs` |
| A-06 | Invalid scenario/receptivity, missing fields, bad JSON, empty body, bad Content-Length, NUL/array values are rejected, with no stack trace and no dispatch | PASS | `SelectorServerHardening.test_malformed_inputs_rejected_without_stack_traces` drives the real HTTP handler on an ephemeral port. Non-object JSON (`[]`, `null`, `"x"`) returns 400 since the S-02 fix in PR #17. No traceback and no dispatch. |
| A-07 | Unknown routes 404; path traversal to `.env.local`, source, `.git/config` gets 404 | PASS | `test_unknown_routes_and_traversal` (raw request line, no client normalisation). Static serving is confined to `web/`. |
| A-08 | Token hygiene: TTL 600 s, room-scoped `roomJoin` only (no admin/create/list/record), secret not in token or response | PASS | `TokenAndBinding.test_token_is_short_lived_and_room_scoped` (verified with `livekit.api.TokenVerifier`, fixture key), `test_valid_session_returns_only_room_url_token` (response keys exactly room/url/token/scenario/receptivity). |
| A-09 | Secrets never in the browser page; no CORS headers on page or API | PASS | `test_secrets_never_reach_browser_page`; `Access-Control-Allow-Origin` absent. |
| A-10 | Selector binds 127.0.0.1 only | PASS | `test_selector_binds_localhost_only` (`brodia_server.main`). |
| A-11 | No keys/tokens in tracked files or in git history | PASS | `test_no_secret_like_strings_tracked` (Google `AIza…`, `sk-…`, JWT `eyJ…`, PEM private keys); manual `git log --all -p` scan found 0 matches; only `.env.example` (placeholders) is tracked. |
| A-12 | Transcripts not persisted by default (Brodia) | PASS | `test_brodia_transcripts_not_written_by_default` and the existing privacy test: caller and character text reach memory only, with no JSONL, stdout or data channel. `--log-caller` is an explicit opt-in for both sides. |
| A-13 | Event/cue logs and recordings are gitignored | PASS | `test_default_logs_and_media_are_gitignored` (`git check-ignore`): `data/tmp/worker_events.jsonl`, `data/tmp/worker_cues.jsonl`, `.env.local`, wav/mp4/jpg/pcm/jsonl and, after F-2, webm/mov/m4a/ogg/vtt. |
| A-14 | Repeated social request cannot reroll; uncertain/garbled speech never scores; uninterested character can exit | PASS | `test_brodia_live_engine.py` dialogue A–I fixtures (plumbing only, not Gemini's live judgment). |

### What the worker still writes to disk (by design, gitignored)

- `data/tmp/worker_events.jsonl` (`--event-log` / `RTCOACH_EVENT_LOG`) is appended per job. Each line holds room name, job id, call_id, `session`/`status` events and, with `--vision-notes`, `vision_note` text such as "turned away from the camera". It holds **no transcripts, frames or audio** unless `--log-caller`.
- `data/tmp/worker_cues.jsonl` holds cue-player records. Brodia uses a disabled cue bank, so this is normally empty.
- Neither file is cleaned up automatically. Delete `data/tmp/` after demo day if room names matter to you.
- The evaluator sends bounded dialogue to Google (or the configured relay). Provider retention is outside this app.

## Manual cases (must be run in a browser)

Setup: two terminals from the repo root.
`LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off` (add `--vision --vision-fps 1 --vision-notes` to exercise video), and `bash scripts/run.sh selector`. Then open `http://127.0.0.1:8080`.

| ID | Case | Result | Steps | Expected |
| --- | --- | --- | --- | --- |
| M-01 | Mic denied | PENDING-MANUAL | Block the microphone for 127.0.0.1 in site settings, pick any scenario, then Start. | Status shows an error and the call ends cleanly, with no hung "Creating…" state. The worker log shows the job ends within about 30 s of LiveKit closing the empty room. Start works again after allowing the mic. |
| M-02 | Camera denied (voice-only must still work) | PENDING-MANUAL (W-1 fixed in PR #17; mocked browser test passes) | Allow the mic and block the camera, then Start. | Should connect voice-only, with feedback saying visual cues were not evaluated. Code review: `enableCameraAndMicrophone()` requests both in one getUserMedia call, so a camera denial or missing camera aborts the **whole call** (web/index.html:15). See W-1. |
| M-03 | No camera device / camera in use by another app | PENDING-MANUAL (W-1 fixed in PR #17) | Same as M-02, with the camera unplugged or in use in another app. | Same as M-02. |
| M-04 | Close tab mid-call | PENDING-MANUAL | Start a call, talk for about 10 s, then close the tab. | The worker prints `caller left and nobody rebound within 2 s: leaving`, then `job … done`, with no traceback and no further Gemini usage. livekit-client disconnects on page leave by default. |
| M-05 | Second call, different scenario | PENDING-MANUAL | Run Barista + Uninterested, say "end practice", hear feedback, click End call. Without reloading, pick Park + Interested and Start. | A new room name appears in the worker log, and the character is a park-goer who starts warm. There is no barista reference and no carried-over refusal. Feedback quotes only call-2 words. |
| M-06 | Network drop | PENDING-MANUAL | Mid-call, disable Wi-Fi for about 5 s and then re-enable it, using DevTools offline. Also try about 30 s. | Short drop: LiveKit reconnects and audio resumes. Long drop: the page shows "Call ended." and the worker leaves (leave grace / room disconnected), and a new Start works. |
| M-07 | Hangup via End call before speaking | PENDING-MANUAL | Start, then click End call immediately. | The worker job ends and no feedback is spoken to an empty room. |
| M-08 | Low frame rate / poor video | PENDING-MANUAL | Start with `--vision --vision-notes`, cover the camera, then throttle the network in DevTools. | No invented visual claims. Feedback is voice-only or mentions only a verified note. |
| M-09 | User knows video is used | PASS (notice added in PR #17; W-2) | Read the selector page. | The page should say that the camera and mic are sent to the AI partner for this call and are not recorded. Currently it says nothing (W-2). |
| M-10 | Uninterested character departs; interrupted speech | PENDING-MANUAL | Barista + Uninterested: keep pressing after a refusal, and talk over the character. | The character politely ends and does not reroll. Barge-in stops audio without a stall. |

## Findings

Severity: H = can break the demo; M = privacy/robustness; L = hardening.

### Fixed on this branch

- **F-1 (M)** `facetime/brodia.py` `FeedbackSession.feedback_prompt`: the no-video line used to tell the coach *not to mention* video. Feedback on a camera-denied call silently omitted the visual part. It now says the feedback is voice-only and asks the coach to state once that visual cues were not evaluated, without guessing body language.
- **F-2 (L)** `.gitignore`: added `*.webm *.mov *.m4a *.ogg *.mkv *.vtt *.srt` so browser or screen call recordings and caption transcripts cannot be committed by accident.
- **Tests**: `scripts/test_brodia_p15_failure_modes.py` (13 tests). It is listed in `docs/BRODIA_LIVE_ENGINE.md`.

### Fixed in PR #17 (P13 branch); original findings kept for the record

All items below were fixed in `web/index.html`, `facetime/brodia_server.py` and `facetime/worker.py` by PR #17 and are
covered by `scripts/test_brodia_server.py`, `scripts/test_brodia_next_call.py`, `scripts/test_brodia_live_engine.py` and
`node scripts/test_brodia_browser.cjs`. K-01 was fixed differently from the suggestion below: a `brodia` agent job with no
valid selection falls back to worker flags, then the Park + Neutral default, never the fitness coach; invalid metadata is
logged and ignored. Camera-denied behaviour (M-02/M-03) still needs a real-browser check.

- **W-1 (H) web/index.html:15**: `await room.localParticipant.enableCameraAndMicrophone()` fails the whole call on camera denial or missing camera. Fix:
  `await room.localParticipant.setMicrophoneEnabled(true); try { await room.localParticipant.setCameraEnabled(true) } catch { status.textContent = 'Camera unavailable: voice-only practice (visual cues won\'t be evaluated).' }`.
  The browser test mock (`scripts/test_brodia_browser.cjs`) would need `setMicrophoneEnabled` and `setCameraEnabled` stubs.
- **W-2 (M) web/index.html:4**: there is no notice that the camera and mic stream to the AI partner (Gemini). Add one sentence: "Your camera and microphone are streamed to the AI partner for this call only; nothing is recorded."
- **S-01 (M) facetime/brodia_server.py:17-20**: the agent dispatch is created *before* `LIVEKIT_URL` is read and the token is minted. A missing `LIVEKIT_URL` returns **400 with body `'LIVEKIT_URL'`** (a config name and the wrong status) and leaves an orphan dispatch. Fix: compute `url = os.environ['LIVEKIT_URL']` and `token = mint(...)` first, then dispatch. Map config errors to a generic 500.
- **S-02 (L) facetime/brodia_server.py:14**: non-object JSON (`[]`, `null`, `"x"`) raises AttributeError and returns 502 instead of 400. Fix: `if not isinstance(data, dict): raise ValueError('expected a JSON object')`.
- **S-03 (M) facetime/brodia_server.py:20 + facetime/mint_token.py:15**: with missing API key or secret, `mint` raises `SystemExit`, which `except Exception` does not catch. The connection drops with no response, after a dispatch was already created. Fix in the server: mint before dispatch and catch `SystemExit` as a 500. `mint_token.py` was left as is because `coach_agent.py` relies on SystemExit semantics.
- **S-04 (L) facetime/brodia_server.py:29**: no Content-Length cap. Fix: reject `n > 4096` with 413.
- **S-05 (L) facetime/brodia_server.py:26**: there is no Content-Type, Origin or Host check. Any website open in the user's browser can POST a `text/plain` body (a CORS "simple request", verified to return 201) and dispatch Gemini worker jobs (denial of wallet). It cannot read the token, because there are no CORS headers. A DNS-rebinding page could read it, because Host is not checked. Fix: require `Content-Type: application/json` and `Host` in `{127.0.0.1:PORT, localhost:PORT}`.
- **K-01 (M) facetime/worker.py:217-228 / 266-267**: a job dispatched to `brodia` with missing or unparseable metadata (and no `--brodia-*` flags) falls back to the **starter fitness coach** persona and plan. `metadata={"brodia": "x"}` raises AttributeError at :219/:224. Fix: when the agent name is `brodia` and the job is not `chert_warm`, refuse the job unless a valid `brodia` object is present. Require `isinstance(selected, dict)`.

### Not issues (checked)

- Rooms are unguessable (`brodia-` plus 10 bytes urlsafe). The token identity is fixed (`brodia-browser`), but each room is unique.
- No secret is printed. `mint_token.py` prints a token only in its CLI. The worker prints `GEMINI_BASE_URL` (a relay URL, not a key) and evaluator errors log only the exception class.
- The worker has no module-level mutable state that is shared across jobs (only constants and the `CONSUMERS` registry).
- `vision_notes` stores text only: no frames, thumbnails or landmarks.
