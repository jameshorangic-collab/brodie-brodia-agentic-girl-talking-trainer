# Real FaceTime on the shared Chert line

Uses Chert's FaceTime CLI ([docs](https://docs.trychert.com/facetime-cli/quickstart), npm `@trychert/facetime`, beta `0.1.0-beta.4`). The `brodia` worker runs on this laptop. `chert dev` claims our project's FaceTime line, keeps a waiting room with the worker in it, and hands each inbound call to that room.

```text
Caller (FaceTime Audio) <-> Chert line <-> LiveKit room (chert-bridge-<call_id>) <-> brodia worker
```

The CLI does **not** start the worker. Start the worker first, then the CLI.

## Once per laptop

- Node 22.12+ (22.x), 24.x or 26.x. Use the same Node version in every terminal.
- Install and sign in, choosing the shared hackathon project:

  ```bash
  npm install -g @trychert/facetime
  chert --version     # chert 0.1.0-beta.4
  chert login         # chert login --device in a remote shell
  chert whoami
  ```

- Use the repo's usual `.env.local` and `.venv` (`bash scripts/install.sh`). Set `AGENT_NAME=brodia`. The worker registers under this name and `chert dev --agent` must match it exactly (it is case sensitive), in the same LiveKit project.

## Run (only inside our slot)

Terminal A, the worker under its dispatch name:

```bash
LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off
```

Terminal B, connect the line:

```bash
bash scripts/run.sh chert          # chert doctor --agent brodia, then chert dev --agent brodia
bash scripts/run.sh chert dev      # skip the doctor (it runs a real agent job each time)
bash scripts/run.sh chert doctor   # doctor only
```

`run.sh` loads `.env.local`, so the CLI picks up the same `LIVEKIT_*` values as the worker. Extra flags go to `chert` (for example `--no-prewarm`). It refuses `--takeover`.

Before you call, wait for both of these lines:

```text
Connected to Chert. Call readiness is reported separately.
"brodia" joined a waiting room. Media readiness is not verified.
```

Then place a **FaceTime Audio** call to the address the organizers gave us and say hello.

## Picking the scenario

Chert dispatches the worker itself, so it cannot carry the selector's `brodia` metadata. Use one of these:

1. **Worker flags.** These set the scenario for every call until you restart the worker:
   `LINE=1 bash scripts/run.sh coach gemini --agent-name brodia --perception off --brodia-scenario barista --brodia-receptivity uninterested`
2. **"Use for next FaceTime call"** in the selector (`bash scripts/run.sh selector`, under "FaceTime line (demo-only)"). It holds one selection for 120 s, and the next real Chert caller job uses it once. See [P13_NEXT_CALL.md](P13_NEXT_CALL.md).
3. Neither set: Park + Neutral.

Each job logs `[brodia] persona <scenario> + <receptivity> from <source>`. Check that line to confirm which one you got.

## Releasing the line (required)

1. Hang up and wait for `Call ended: room removed.`
2. Press Ctrl+C in Terminal B and wait for `Stopped. The line no longer routes to this agent.`
3. Stop the worker in Terminal A and tell the next team that the line is free.

Hanging up does not release the slot. Never use `--takeover` without the organizers. If cleanup stays pending, keep `~/.chert` and ask the organizers. Do not delete it.

After you change code, restart both terminals, so a prepared room does not keep running old code.

## Limits on this path

- Start with FaceTime Audio. FaceTime Video on the hackathon line is undocumented, and the agent may need to publish video as well ([FACETIME_VIDEO_FEASIBILITY.md](FACETIME_VIDEO_FEASIBILITY.md), P12 in [NEIL_CALL_TESTS.md](NEIL_CALL_TESTS.md)).
- A waiting room or a passed `doctor --agent` only shows that the agent joined. A test counts only after a real two-way conversation.
- **Not yet done:** a real call through `chert dev --agent brodia`.
