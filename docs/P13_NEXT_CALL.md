# P13: "Use for next FaceTime call" (demo-only fallback)

Status: **offline-tested only. Live behavior on the Chert line is ⚠️ unverified.**

## Why this exists

P01 (`docs/FACETIME_VIDEO_FEASIBILITY.md`) found no documented way to bind a web
selection to a specific inbound caller on the shared Chert line. So this is the
demo-only fallback: **one caller at a time**. The selector holds ONE pending
"next call" selection with a short TTL. The first real Chert caller job consumes it,
once. It is not a scalable or multi-user design, so do not present it as one.

## Design

- `facetime/next_call.py` stores the selection in `data/tmp/brodia_next_call.json`
  (gitignored; override with `BRODIA_NEXT_CALL_PATH`). The selector and worker are
  separate processes on one laptop, so they share it through a file:
  - **store**: validated with `RoleplayConfig`, written to a temp file and then
    `os.replace`d. This is atomic and replaces any older pending selection.
    The TTL is `BRODIA_NEXT_CALL_TTL_S` (default 120 s).
  - **consume**: `os.rename` to a unique claim name, so exactly one process wins.
    The file is then read and deleted. An expired or invalid selection is deleted
    and not used.
- `facetime/brodia_server.py`:
  - `POST /api/next-call {scenario, receptivity}` returns 201 with
    `{pending, id, scenario, receptivity, expires_in}`, or 400 when the selection
    is invalid.
  - `GET /api/next-call` returns the status (`{pending: false}` or the fields above).
  - `DELETE /api/next-call` clears the pending selection. No secrets are involved.
- `facetime/worker.py` `select_brodia()` runs at the start of each job. It picks the
  persona source in this priority order:
  1. Explicit `brodia` dispatch metadata (browser Start Practice). The pending
     selection is not touched.
  2. A real Chert caller job (metadata has `chert_call` and does not have
     `chert_warm`) consumes the pending selection if it has not expired.
  3. Otherwise the `--brodia-scenario/--brodia-receptivity` flags.
  4. Otherwise, for a `brodia*` agent, the default Brodia persona (Park + Neutral).
     It never falls back to the starter fitness coach. Invalid `brodia` metadata
     (not an object, or bad values) is logged and ignored; it never crashes the job.

  Warm and doctor jobs (`chert_warm`) never consume it. Every job logs one line:
  `[brodia] persona <scenario> + <receptivity> from <source>`.
- Knobs:
  - `BRODIA_NEXT_CALL=0` turns the feature off in the worker.
  - `BRODIA_NEXT_CALL_ANY_JOB=1` is an escape hatch. If live calls turn out to
    carry no `chert_call` key, it lets any non-warm job without `brodia`
    metadata consume the selection.
- `web/index.html` has a collapsed "FaceTime line (demo-only)" section with the
  **Use for next FaceTime call** button. Its copy says the feature is demo-only,
  handles one caller at a time, expires in N s, and is not yet proven to reach
  the call. The Start Practice flow is unchanged.

## Offline tests

```bash
.venv/bin/python scripts/test_brodia_next_call.py   # TTL, one-time, replace, invalid, warm, explicit wins, races, HTTP
node scripts/test_brodia_browser.cjs                # button POST + honest copy, plus the 9 browser-call variants
```

Tests never touch the real `data/tmp/brodia_next_call.json`. Each test script sets
`BRODIA_NEXT_CALL_PATH` to a temp file. `next_call.state_path()` also uses a
private temp file for any `test_*` script or pytest run that did not set it.

Selector POST endpoints accept only a local `Host` (`127.0.0.1:<port>` or
`localhost:<port>`), `Content-Type: application/json`, and a JSON object body
of 4 KB or less. Otherwise they return 403, 415, 400 or 413.

## Live test steps (⚠️ unverified; run on the laptop with `.env.local`)

1. Stop any other worker registered as `brodia`, because only one worker may
   take the line. Terminal 1:
   `LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off`
2. Terminal 2: `chert dev --agent brodia` (the shared line dispatches to our worker).
3. Terminal 3: `bash scripts/run.sh selector`, then open `http://127.0.0.1:8080`.
4. Pick **Barista + Interested**. Open "FaceTime line (demo-only)" and click
   **Use for next FaceTime call**. The selector logs
   `[selector] next-call selection <id>: barista + interested ...`.
   The status is available from `curl -s 127.0.0.1:8080/api/next-call`.
5. Within the TTL (120 s), FaceTime the shared line. Make sure **only one person
   calls**.
6. In the worker log, check the job's `metadata:` line (it should show
   `chert_call=...`). Then check for
   `[brodia] persona barista + interested from next-call selection (demo-only; consumed selection <id> ...)`.
   Say hello and confirm a barista who is receptive.
7. Hang up and call again **without clicking**. The log must say
   `... from worker flags (next-call: no pending selection)` or
   `Brodia default (next-call: no pending selection)` (Park + Neutral).
   It must NOT say barista + interested again.
8. Issue sequence: click **Street + Uninterested**, call, and confirm street +
   uninterested is used, with no stale barista selection.
9. Expiry: click, wait more than 120 s, then call. The log should say
   `next-call: pending selection <id> expired ... (discarded)`.

If step 6 shows a fallback source with `metadata: none` or no `chert_call`, the
live job carries no `chert_call` key. Restart the worker with
`BRODIA_NEXT_CALL_ANY_JOB=1` and repeat. If it still does not work, record the
P13 limitation: the frontend controls LiveKit browser calls, and FaceTime uses a
preselected demo configuration (`--brodia-scenario/--brodia-receptivity`).

Also unverified: a warm/prewarm job (`chert_warm`) does not eat the selection
before the real call. Offline tests cover this, but confirm it in the log: warm
jobs print `(warm job: next-call not consumed)`.

Attach the worker log lines from steps 6 to 8 as P13 evidence.
