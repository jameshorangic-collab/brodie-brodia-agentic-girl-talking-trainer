// POST /api/session {scenario, receptivity}: the public version of facetime/brodia_server.py's create_session.
// Creates a private room, dispatches the `brodia` cloud worker into it with the selection as metadata, and returns a
// 10-minute browser token. LiveKit itself is the rate-limit store, so there is nothing else to run: each caller (an HMAC of
// their IP) owns BRODIA_MAX_PER_CALLER fixed room names, checked by name (consistent at once; the full room listing lags a
// few seconds, so it only backs the coarse global cap). The worker caps each call's length (BRODIA_MAX_CALL_S).
//
// Env (Vercel project settings): LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET (the project the worker is deployed in),
// optional AGENT_NAME (brodia), BRODIA_PUBLIC_CALLS=0 to pause, BRODIA_MAX_CONCURRENT (4: the Build plan runs 5 agent
// sessions, one is left for the Chert line), BRODIA_MAX_PER_CALLER (2: a venue's Wi-Fi shares one IP).
import crypto from 'node:crypto';
import { AccessToken, AgentDispatchClient, RoomServiceClient } from 'livekit-server-sdk';

const SCENARIOS = ['barista', 'street', 'park'];
const RECEPTIVITIES = ['interested', 'neutral', 'uninterested'];
const PREFIX = 'brodia-web-';
const STALE_S = 90; // a room this old with fewer than two participants never got its caller (or lost them): reclaim it

const int = (v, d) => (Number.isInteger(Number(v)) && Number(v) > 0 ? Number(v) : d);

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  if (process.env.BRODIA_PUBLIC_CALLS === '0') return res.status(503).json({ error: 'Practice calls are paused right now. Join the waitlist and we’ll ping you.', paused: true });

  const origin = req.headers.origin;
  if (origin) {
    let host = '';
    try { host = new URL(origin).host; } catch {}
    if (host !== req.headers.host) return res.status(403).json({ error: 'forbidden' });
  }
  if (!(req.headers['content-type'] || '').toLowerCase().startsWith('application/json')) return res.status(415).json({ error: 'Content-Type must be application/json' });

  const { scenario, receptivity } = req.body && typeof req.body === 'object' ? req.body : {};
  if (!SCENARIOS.includes(scenario) || !RECEPTIVITIES.includes(receptivity)) return res.status(400).json({ error: 'Pick a map and a difficulty.' });

  const { LIVEKIT_URL: url, LIVEKIT_API_KEY: key, LIVEKIT_API_SECRET: secret } = process.env;
  if (!url || !key || !secret) {
    console.error('[session] LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set');
    return res.status(500).json({ error: 'Practice server is not configured' });
  }
  const api = url.replace(/^ws/, 'http');
  const rooms = new RoomServiceClient(api, key, secret);

  const ip = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim() || req.socket?.remoteAddress || 'unknown';
  const caller = crypto.createHmac('sha256', secret).update(ip).digest('hex').slice(0, 16); // never store the raw IP

  try {
    const now = Date.now() / 1000;
    const isStale = (r) => now - Number(r.creationTime) > STALE_S && r.numParticipants < 2;
    const slots = Array.from({ length: int(process.env.BRODIA_MAX_PER_CALLER, 2) }, (_, i) => `${PREFIX}${caller}-${i}`);
    const mine = await rooms.listRooms(slots);
    const stale = mine.filter(isStale); // never reused in the same request: the old agent may still be leaving
    await Promise.allSettled(stale.map((r) => rooms.deleteRoom(r.name)));
    const room = slots.find((n) => !mine.some((r) => r.name === n));
    if (!room) return res.status(429).json({ error: 'You already have a practice call open. End it first, then try again.' });

    const live = (await rooms.listRooms()).filter((r) => r.name.startsWith(PREFIX) && !isStale(r));
    if (live.length >= int(process.env.BRODIA_MAX_CONCURRENT, 4))
      return res.status(429).json({ error: 'Every practice partner is on a call. Try again in a few minutes.', busy: true });

    await rooms.createRoom({ name: room, emptyTimeout: 60, departureTimeout: 10, maxParticipants: 2 });
    await new AgentDispatchClient(api, key, secret).createDispatch(room, process.env.AGENT_NAME || 'brodia', {
      metadata: JSON.stringify({ brodia: { scenario, receptivity } }),
    });

    const at = new AccessToken(key, secret, { identity: 'brodia-browser', ttl: '10m' });
    at.addGrant({ roomJoin: true, room, canPublish: true, canSubscribe: true, canPublishData: false });
    return res.status(201).json({ room, url, token: await at.toJwt(), scenario, receptivity });
  } catch (e) {
    console.error('[session] dispatch failed:', e?.name || 'Error', e?.message?.slice(0, 160));
    return res.status(502).json({ error: 'Couldn’t start a practice call. Try again.' });
  }
}
