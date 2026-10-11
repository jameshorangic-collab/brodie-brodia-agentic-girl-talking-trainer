# Brodia landing page

Vite + React. The waitlist posts to a Val Town HTTP val (`waitlist-val.ts`), which stores signups in that val's SQLite database.

## Run locally

```bash
cd landing
npm install
npm run dev
```

The waitlist posts to the live val [`tahar/brodia-waitlist`](https://www.val.town/x/tahar/brodia-waitlist) by default. Set `VITE_WAITLIST_URL` (see `.env.example`) to point it elsewhere.

## Deploy to Vercel

1. Import the repo in Vercel and set **Root Directory** to `landing`. The Vite preset and `vercel.json` handle the build (`npm run build`, output `dist`).
2. Deploy. No environment variables are required.

Or from the CLI: `cd landing && npx vercel` (first run links the project), then `npx vercel --prod`.

## Waitlist

- `GET` returns `{count}`. `POST {email}` signs up and returns `{ok, count}`. Duplicate emails are ignored.
- It also stores the scenario and difficulty picked on the page, plus `?ref=` from the URL, so share links can be tagged (e.g. `?ref=tiktok`).
- Read signups in Val Town's SQLite browser or with `SELECT * FROM waitlist ORDER BY created_at DESC`.
