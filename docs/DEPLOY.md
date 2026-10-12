# Deploying the Brodia worker to LiveKit Cloud

The worker runs as a LiveKit Cloud agent. Nothing has to stay running on a laptop. Its dispatch name is still `brodia`, so the browser selector and `chert dev --agent brodia` reach it the same way they reach a local worker.

- `Dockerfile`: Python 3.12, CPU-only torch, `requirements-worker.txt` (what the worker imports for a Brodia call) and MediaPipe's pose models for `--vision-notes` and `--mirror`. It runs as an unprivileged user. Flags: `--voice gemini --agent-name brodia --perception off --avatar --mirror --vision-notes start`.
- `.dockerignore` keeps `.env*`, `data/`, `models/`, `.venv/`, `landing/`, `docs/` and `scripts/` out of the build context.
- LiveKit Cloud injects `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`. Do not set them as secrets.

## Build and test locally (optional)

```bash
podman build -t brodia-worker .        # or docker build
podman run --rm -v "$PWD/scripts:/app/scripts:ro,Z" -e GEMINI_API_KEY=dummy brodia-worker python scripts/test_brodia_config.py
```

Offline tests that pass inside the image: config, gemini, live_engine, feedback, avatar, mirror, pose_notes, next_call and vision_notes. These are expected to fail inside the image: `test_worker_shutdown` (it needs the starter's fitness pose classifier, which the Brodia image leaves out) and four `p15` repo-hygiene checks (they need `git` and `web/`).

## Deploy

```bash
lk cloud auth                          # once: links the CLI to our LiveKit Cloud project (opens a browser)
lk agent create --secrets-file .env.local
```

`create` uploads the build context, builds on LiveKit Cloud (the limit is 10 min) and writes `livekit.toml`. Commit `livekit.toml`. The CLI skips the `LIVEKIT_*` lines in the secrets file. The worker needs `GEMINI_API_KEY`; the `BRODIA_*` and `GEMINI_*` settings are optional.

After that:

```bash
lk agent deploy                        # ship a new version (rolling)
lk agent status                        # replicas and state
lk agent logs                          # live tail: look for "[worker] agent 'brodia'" and "registered worker"
lk agent update-secrets --secrets "GEMINI_API_KEY=..."
```

## Things to know

- **One dispatch name, one place.** A laptop worker started with `LINE=1` also registers as `brodia`, and LiveKit spreads jobs across both. Stop the local worker, or run it under another `AGENT_NAME`, while the cloud one is live.
- **Build plan limits:** at most 5 concurrent agent sessions. The agent may scale to zero when idle, which adds 10 to 20 s before it joins the next call. `chert dev` keeps a waiting room ready, which covers most of that on the FaceTime line.
- **Costs:** every call uses Gemini Live and the evaluator model on our key. The image sets `BRODIA_MAX_CALL_S=600`, so each call ends 10 minutes after the caller joins, whether or not the camera is on. The public site's `/api/session` adds per-IP and site-wide limits ([landing/README.md](../landing/README.md#practice-calls)).
- **Not yet verified:** a real call against the deployed agent, and CPU headroom for `--mirror` (pose at the mirror frame rate) on LiveKit Cloud's instance size. If calls stutter, drop `--mirror` from `CMD` first.
