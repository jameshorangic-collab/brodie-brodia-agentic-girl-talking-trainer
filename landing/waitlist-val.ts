// Brodia waitlist: a Val Town HTTP val. Deployed copy lives on Val Town; this file is the source of record.
// GET  -> {count}
// POST {email, scenario?, receptivity?, ref?, company?} -> {ok, count}   (company is a honeypot)
import { sqlite } from "https://esm.town/v/std/sqlite/main.ts";

await sqlite.execute(`CREATE TABLE IF NOT EXISTS waitlist (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  scenario TEXT,
  receptivity TEXT,
  ref TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
)`);

const EMAIL = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,24}$/;
const SCENARIOS = new Set(["barista", "street", "park"]);
const MOODS = new Set(["interested", "neutral", "uninterested"]);

async function count() {
  const r = await sqlite.execute("SELECT COUNT(*) AS n FROM waitlist");
  return Number(r.rows[0].n);
}

export default async function (req: Request): Promise<Response> {
  if (req.method === "GET") return Response.json({ count: await count() });
  if (req.method !== "POST") return Response.json({ error: "Use GET or POST." }, { status: 405 });

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Send JSON with an email." }, { status: 400 });
  }
  if (body.company) return Response.json({ ok: true, count: await count() }); // bot: pretend it worked

  const email = String(body.email ?? "").trim().toLowerCase();
  if (!EMAIL.test(email)) return Response.json({ error: "That email doesn’t look right." }, { status: 400 });
  const scenario = SCENARIOS.has(String(body.scenario)) ? String(body.scenario) : null;
  const receptivity = MOODS.has(String(body.receptivity)) ? String(body.receptivity) : null;
  const ref = body.ref ? String(body.ref).slice(0, 200) : null;

  await sqlite.execute({
    sql: "INSERT INTO waitlist (email, scenario, receptivity, ref) VALUES (?, ?, ?, ?) ON CONFLICT(email) DO NOTHING",
    args: [email, scenario, receptivity, ref],
  });
  return Response.json({ ok: true, count: await count() });
}
