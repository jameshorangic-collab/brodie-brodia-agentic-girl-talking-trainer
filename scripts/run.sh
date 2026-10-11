#!/usr/bin/env bash
# Load .env.local and run the coach, browser selector, or mint a phone link.
#   bash scripts/run.sh coach [gemini|openai|off] [worker flags...]   # voice defaults to VOICE or Gemini; add --mirror for the pose-mirror video track, --avatar for the character video
#   bash scripts/run.sh selector                                      # serves the browser call UI at http://127.0.0.1:8080
#   bash scripts/run.sh link [room]                                   # room defaults to try-<time>
#   bash scripts/run.sh chert [dev|doctor] [chert flags...]           # real FaceTime on the shared Chert line (start the worker with LINE=1 first)
# The coach joins your own rooms (empty agent name); set LINE=1 to use AGENT_NAME from .env.local for the call line.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env.local; set +a
PY=.venv/bin/python

case "${1:-}" in
    coach)
        shift
        case "${1:-}" in gemini|openai|off) VOICE=$1; shift ;; esac
        agent=(); [ "${LINE:-}" = 1 ] || agent=(--agent-name "")
        exec "$PY" -m facetime.worker --voice "${VOICE:-gemini}" "${agent[@]}" "$@" dev ;;
    selector)
        exec "$PY" -m facetime.brodia_server ;;
    chert)
        # Default: `chert doctor --agent` (a real test job), then `chert dev --agent` until Ctrl+C. `dev` skips the doctor.
        shift
        command -v chert >/dev/null || { echo "chert not found: npm install -g @trychert/facetime (Node 22.12+, 24 or 26), then chert login"; exit 1; }
        agent_name=${AGENT_NAME:?set AGENT_NAME in .env.local (the worker registers under it with LINE=1)}
        step=all; case "${1:-}" in dev|doctor) step=$1; shift ;; esac
        for f in "$@"; do [ "$f" = --takeover ] && { echo "--takeover is refused here: it kicks another team off the line. Ask the organizers."; exit 1; }; done
        [ "$step" = dev ] || chert doctor --agent "$agent_name" "$@"
        [ "$step" = doctor ] || exec chert dev --agent "$agent_name" "$@" ;;
    link)
        exec "$PY" -m facetime.mint_token --room "${2:-try-$(date +%H%M%S)}" --url ;;
    *)
        sed -n '2,6p' "$0"; exit 1 ;;
esac
