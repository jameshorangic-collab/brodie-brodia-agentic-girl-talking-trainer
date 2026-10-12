# Brodia landing page

Vite + React. The waitlist posts to a Val Town HTTP val (`waitlist-val.ts`), which stores signups in that val's SQLite database.

## Run locally

```bash
cd landing
npm install
npm run dev
```

The waitlist posts to the live val [`tahar/brodia-waitlist`](https://www.val.town/x/tahar/brodia-waitlist) by default. Set `VITE_WAITLIST_URL` (see `.env.example`) to point it elsewhere.

## Practice calls

**Lock in** starts a real call in the browser (`src/Call.jsx`). It posts the picked map and difficulty to `POST /api/session` (`api/session.js`, a Vercel function). The function creates a private LiveKit room, dispatches the `brodia` cloud worker into it (see `../docs/DEPLOY.md`) and returns a 10-minute token. `livekit-client` loads only when someone starts a call.

Limits come from LiveKit room state, so no database is needed:

- 2 open calls per IP (`BRODIA_MAX_PER_CALLER`; a venue's Wi-Fi shares one IP), checked by room name. The room name carries an HMAC of the IP, never the IP itself.
- 4 calls across the whole site (`BRODIA_MAX_CONCURRENT`). The Build plan runs 5 agent sessions, so one stays free for the Chert line. This cap reads the full room list, which lags a few seconds, so treat it as approximate.
- 10 minutes per call, enforced by the worker (`BRODIA_MAX_CALL_S` in the Dockerfile).
- `BRODIA_PUBLIC_CALLS=0` pauses calls. The page then points people at the waitlist.
- The function rejects other origins and non-JSON requests, and reclaims rooms where the caller never joined after 90 s.

`npm run dev` serves the page only. Use `npx vercel dev` to run `/api/session` locally too.

## Deploy to Vercel

1. Import the repo in Vercel and set **Root Directory** to `landing`. The Vite preset and `vercel.json` handle the build (`npm run build`, output `dist`). Vercel picks up `api/` as functions.
2. Set `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` for the LiveKit project where the worker runs (Production). The other variables are optional (see above). Without the three LiveKit variables, the waitlist still works and Lock in reports that the server isn't configured.

Or from the CLI: `cd landing && npx vercel` (first run links the project), then `npx vercel --prod`.

## Waitlist

- `GET` returns `{count}`. `POST {email}` signs up and returns `{ok, count}`. Duplicate emails are ignored.
- It also stores the scenario and difficulty picked on the page, plus `?ref=` from the URL, so share links can be tagged (e.g. `?ref=tiktok`).
- Read signups in Val Town's SQLite browser or with `SELECT * FROM waitlist ORDER BY created_at DESC`.
