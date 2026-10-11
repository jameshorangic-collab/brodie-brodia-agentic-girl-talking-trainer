# Testing Brodia on real FaceTime without the shared line

Uses Chert's open-source connector ([cherthq/chert-facetime-opensource](https://github.com/cherthq/chert-facetime-opensource), npm `@trychert/facetime-opensource@0.1.2`). A Chrome window on this laptop joins **your own FaceTime link** as a browser guest and bridges it to a LiveKit room where the `brodia` worker is waiting. No Chert slot is needed, and nothing has to be released afterwards.

```text
iPhone (FaceTime link) <-> Chrome guest + connector (laptop) <-> LiveKit room brodia-ft-* <-> brodia worker
```

## Needs

- Node 22.22+ and `npx`
- **Google Chrome** (the connector launches Playwright's `chrome` channel; Chromium does not count). On Fedora: `sudo dnf install https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm`
- An iPhone with FaceTime, and the repo's usual `.env.local` and `.venv`

## Run

Terminal A, the worker registered under its dispatch name:

```bash
LINE=1 bash scripts/run.sh coach
```

Terminal B, one practice call (scenario and receptivity default to `park neutral`):

```bash
bash scripts/run.sh facetime barista uninterested
```

Terminal B dispatches `brodia` into a fresh room with the selection as metadata (the same `{"brodia": {...}}` contract the web selector uses). It then waits for the agent to join, writes a one-hour connector token to `.local/facetime-oss.json` (mode 0600, gitignored) and runs the connector.

1. On the iPhone, open FaceTime, tap **Create Link** and copy it. Paste it at the hidden prompt.
2. Click **Join** in the Chrome window, then admit the guest on the iPhone.
3. Press **Enter** in Terminal B. Say hello.
4. To finish, press Enter in Terminal B (or **Stop test** in Chrome). The worker ends the job about 2 s after the guest leaves. Run Terminal B again for each new call.

`--no-launch` writes the config and prints the `npx` command without opening Chrome.

## Limits on this path

- **Caller video does not reach the worker.** The connector publishes only the caller's audio (`facetime-caller`), so feedback is voice-only and vision notes stay empty. Do not present this as FaceTime Video analysis.
- The agent publishes no video, so the iPhone sees the connector's waiting graphic.
- The connector is experimental and tested by Chert on macOS only. Linux is unverified until we complete a call.

## Verified so far (2026-10-11, Linux)

- Dispatch with metadata reaches the worker, which builds the `facetime.brodia` persona.
- A simulated `facetime-guest` audio participant gets bound, and a Gemini session starts for it.
- The connector's view of the agent is exactly one audio track (`coach-audio`).
- **Not yet done:** a real iPhone call through Chrome.
