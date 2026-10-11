# P01: FaceTime Video feasibility and web-selection linkage

Owner: Neil · Researched 2026-10-10 from Chert's public docs and the pinned SDK source · Status: **research done; nothing here is call-tested.** Items marked ⚠️ need Gary/Chert or a live slot to confirm.

## Short answer

| Question | Answer | Evidence |
|---|---|---|
| Does the hackathon CLI path (`chert dev --agent`) carry FaceTime **Video**? | **Not for our purposes yet.** Documented as audio-first. Video needs a separate integration and line validation. | CLI overview: *"Start with inbound FaceTime Audio; video and avatars require a separate integration and line validation."* Workshop guide: *"Video/avatars require separate development and validation."* |
| If video is enabled, does caller video reach our worker? | **Yes, per the BYOR docs.** It arrives as a LiveKit video track named `facetime-remote-video`. | BYOR: *"For enabled inbound video calls, Chert bridges audio and video in both directions."* FaceTime intro: *"Your agent receives the caller's microphone and camera as LiveKit tracks."* |
| Must the agent publish **outgoing video** for a video call? | **Yes.** It must publish audio and video. Our worker currently publishes **audio only** (the cue-player track). | BYOR: the agent's video goes back to the caller through its published video track. Open-source connector README: *"For video, your agent must publish a video track as well as audio."* Brodie's `--avatar` / `--mirror` exist only in `facetime/coach_agent.py`, not in `facetime/worker.py`. |
| Is video available on the **shared hackathon line**? | ⚠️ **Unknown. Ask Gary.** The CLI has no video flag (`chert dev` flags: `--agent --env-file --project --takeover --no-prewarm --muse --backend --relay-origin`). | CLI commands page. The create-room adapter says *"It supports audio only"* and is private preview. |
| Can a web selection be tied to a **specific** inbound FaceTime caller? | **No documented way on the shared line.** The worker sees a bridge identity `chert-bridge-<call_id>` and job metadata `chert_call`/`media`, but nothing a web page knows beforehand. BYOR's `call.incoming` webhook has `call_id`, `line_id`, `media`, `from_handle_hash` (null in the example). | BYOR page; `facetime/worker.py` header (bridge identity, job metadata). The BYOR/create-room paths are private preview and need Chert access. |
| Does our model see the frames that reach the worker? | **Gemini: yes.** The `livekit-plugins-google` 1.8.5 `push_video` sends JPEG realtime input. **OpenAI (`--voice openai`): yes, but costly.** In 1.8.5 `push_video` adds **one `conversation.item.create` image message per forwarded frame**, so the context grows by one image per forwarded frame. | Source read in the pinned venv: `livekit/agents/llm/_realtime/openai.py:1706` and `livekit/plugins/google/realtime/realtime_api.py:824`. |

## Recommendation (fallbacks we commit to)

1. **FaceTime Audio first (P11).** This is the only path Chert documents for the hackathon CLI.
2. **Caller vision is proven over LiveKit browser/phone video (P08/P09)** with `--vision-notes`. It is labeled as browser video in the demo, never as FaceTime Video.
3. **FaceTime Video (P12) only if Gary confirms** that our line is validated for video. Even then we must publish an outgoing video track. The cheapest option is a static image or a simple rendered frame, which needs a small `rtc.VideoSource` publisher in the worker (James's file, so coordinate first). If any piece is missing, P12 stays **BLOCKED (external)**.
4. **Web → FaceTime selection (H6 to Taha, for P13):** the answer is **no proven API on the shared line.** Use the demo-only workaround: one active caller at a time, and the server holds a single "next call" selection with a short TTL, consumed by the first `chert-bridge-*` bind. It must be labeled demo-only. BYOR/`call.incoming` webhooks could do it properly but are private preview.
5. **With `--voice openai`, keep `--vision-fps` at 0.5 or lower,** or prefer `--voice gemini` for the vision demo. Do not claim the OpenAI model "watches continuously".

## Questions for Gary / Chert (H7)

1. Is our assigned line enabled and validated for **inbound FaceTime Video** through `chert dev`? If yes, what flag or setting enables it?
2. On a video call, is the caller track named `facetime-remote-video`, and what resolution and frame rate does it arrive at?
3. Does the caller see a black tile, or does the call fail, if the agent publishes no video track?
4. Is anything in job metadata (`chert_call`) or bridge identity available **before** the call, so a web page could pre-bind settings? Can hackathon teams get BYOR or webhook access?

## Sources

- https://docs.trychert.com/facetime-cli/overview
- https://docs.trychert.com/facetime-cli/commands
- https://docs.trychert.com/facetime-cli/workshop
- https://docs.trychert.com/facetime-cli/byor
- https://docs.trychert.com/facetime-cli/create-room
- https://docs.trychert.com/facetime/introduction
- https://docs.trychert.com/facetime/bring-your-own-room
- https://github.com/cherthq/chert-facetime-opensource
