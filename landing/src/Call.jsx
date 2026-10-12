import { useEffect, useRef, useState } from 'react';
import { MODES, SCENES } from './data.js';
import GameReview from './Review.jsx';

const REPORT_TOPIC = 'brodia.report'; // facetime/brodia_report.py: the worker's live game review, latest wins

/* A practice call in the browser: POST /api/session (api/session.js), then join the LiveKit room the `brodia` cloud worker
   was dispatched into. Same flow as web/index.html. Started from a click, never on mount (StrictMode would call twice). */
export function useCall() {
  const [call, setCall] = useState(null); // null | {pick, state: connecting | live | ended | error, msg, waitlist, report, seconds}
  const room = useRef(null), liveAt = useRef(0);
  const agentVideo = useRef(null), audio = useRef(null);
  const update = (patch) => setCall((c) => (c ? { ...c, ...patch } : c));

  function end(msg = 'Call ended. GG.') {
    const r = room.current; room.current = null;
    if (r) r.disconnect();
    audio.current?.replaceChildren();
    update({ state: 'ended', msg, seconds: liveAt.current ? (Date.now() - liveAt.current) / 1000 : 0 });
    liveAt.current = 0;
  }

  async function start(pick) {
    if (room.current) return;
    setCall({ pick, state: 'connecting', msg: `Calling ${SCENES[pick.scenario].name}…` });
    const { Room, RoomEvent, Track } = await import('livekit-client'); // ~500 kB: only once somebody calls
    if (room.current) return;
    const r = new Room({ audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    room.current = r;
    try {
      const res = await fetch('/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pick) });
      const x = await res.json().catch(() => ({}));
      if (!res.ok) throw Object.assign(new Error(x.error || 'Couldn’t start a practice call. Try again.'), { waitlist: !!(x.paused || x.busy) || res.status === 404 });
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Video) track.attach(agentVideo.current);
        else audio.current?.append(track.attach());
      });
      r.on(RoomEvent.DataReceived, (payload, _from, _kind, topic) => {
        if (topic !== REPORT_TOPIC) return;
        let report; try { report = JSON.parse(new TextDecoder().decode(payload)); } catch { return; }
        if (report?.v !== 1 || !Array.isArray(report.turns)) return;
        setCall((c) => (!c ? c : { ...c, report, ...(report.finished && c.state === 'live' ? { msg: 'Coach Brodie is breaking it down. Hang up when he’s done to see your game review.' } : {}) }));
      });
      r.on(RoomEvent.TrackUnsubscribed, (track) => track.detach().forEach((el) => el !== agentVideo.current && el.remove()));
      // rooms hold two participants: anyone leaving is the partner (hung up, or the worker's call cap)
      r.on(RoomEvent.ParticipantDisconnected, () => end());
      r.on(RoomEvent.Disconnected, () => room.current === r && end());
      await r.connect(x.url, x.token);
      await r.startAudio();
      await r.localParticipant.setMicrophoneEnabled(true);
      let camera = true;
      try { await r.localParticipant.setCameraEnabled(true); } catch { camera = false; }
      liveAt.current = Date.now();
      update({ state: 'live', msg: camera ? 'Say hi. Say “end practice” for your game review.' : 'No camera, so it’s voice-only: no body-language notes this time.' });
    } catch (e) {
      if (room.current === r) { room.current = null; r.disconnect(); }
      const denied = e?.name === 'NotAllowedError';
      update({ state: 'error', msg: denied ? 'Brodia needs your mic to talk. Allow it in the browser and try again.' : e.message, waitlist: !!e.waitlist });
    }
  }

  useEffect(() => () => room.current?.disconnect(), []);
  return { call, start, end, close: () => { end(); setCall(null); }, refs: { agentVideo, audio } };
}

export function CallPanel({ call, start, end, close, refs }) {
  if (!call) return null;
  const s = SCENES[call.pick.scenario], m = MODES[call.pick.receptivity];
  const on = call.state === 'connecting' || call.state === 'live';
  return (
    <div className="callwrap" role="dialog" aria-modal="true" aria-label={`Practice call with ${s.name}`}>
      <div className="call">
        <div className="callhead"><b>{s.name}</b><span>{s.label} · {m.label}</span></div>
        {call.state === 'ended' && call.report
          ? <GameReview report={call.report} pick={call.pick} seconds={call.seconds} onAgain={() => start(call.pick)} onClose={close} />
          : <>
            <div className="callstage" data-state={call.state}>
              <video ref={refs.agentVideo} className="agent" autoPlay playsInline />
              {/* no self-view here: the worker's --mirror already draws the caller's camera as an inset in the partner video */}
              <div ref={refs.audio} hidden />
            </div>
            <p className="callmsg" role="status">{call.msg}</p>
          </>}
        {call.waitlist && <p className="callmsg"><a href="#waitlist" onClick={close}>Join the waitlist</a> and we’ll ping you.</p>}
        {!(call.state === 'ended' && call.report) && (
          <div className="callctl">
            {on ? <button className="btn end" type="button" onClick={() => end()}>End call</button>
                : <button className="btn ghost" type="button" onClick={close}>Close</button>}
          </div>
        )}
        <p className="fine">AI practice partner, 18+ fictional characters. Your camera and mic stream live to the AI; nothing is recorded. Calls end after 10 minutes.</p>
      </div>
    </div>
  );
}
