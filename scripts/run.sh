#!/usr/bin/env bash
# Load .env.local and run the coach, browser selector, or mint a phone link.
#   bash scripts/run.sh coach [gemini|openai|off] [worker flags...]   # voice defaults to VOICE or Gemini; add --mirror for the pose-mirror video track, --avatar for the character video
#   bash scripts/run.sh selector                                      # serves the browser call UI at http://127.0.0.1:8080
#   bash scripts/run.sh link [room]                                   # room defaults to try-<time>
#   bash scripts/run.sh facetime [scenario] [receptivity]             # real FaceTime via the open-source connector (worker: LINE=1)
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
    facetime)
        shift; exec "$PY" -m facetime.facetime_oss "$@" ;;
    link)
        exec "$PY" -m facetime.mint_token --room "${2:-try-$(date +%H%M%S)}" --url ;;
    *)
        sed -n '2,6p' "$0"; exit 1 ;;
esac
