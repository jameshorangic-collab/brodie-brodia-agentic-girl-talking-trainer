import { useEffect, useRef, useState } from 'react';
import { MODES, SCENES } from './data.js';
import GameReview from './Review.jsx';
import { Avatar } from './ui.jsx';
import { clock } from './review.js';

const REPORT_TOPIC = 'brodia.report'; // facetime/brodia_report.py: the worker's live game review, latest wins

/* A practice call in the browser: POST /api/session (api/session.js), then join the LiveKit room the `brodia` cloud worker
   was dispatched into. Same flow as web/index.html. Started from a click, never on mount (StrictMode would call twice). */
export function useCall() {
  // null | {pick, state: connecting | live | ended | error, msg, waitlist, report, since, seconds, mic, cam, video}
  const [call, setCall] = useState(null);
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
    setCall({ pick, state: 'connecting', msg: 'Connecting…' });
    const { Room, RoomEvent, Track } = await import('livekit-client'); // ~500 kB: only once somebody calls
    if (room.current) return;
    const r = new Room({ audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    room.current = r;
    try {
      const res = await fetch('/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pick) });
      const x = await res.json().catch(() => ({}));
      if (!res.ok) throw Object.assign(new Error(x.error || 'Couldn’t start a practice call. Try again.'), { waitlist: !!(x.paused || x.busy) || res.status === 404 });
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Video) { track.attach(agentVideo.current); update({ video: true }); }
        else audio.current?.append(track.attach());
      });
      r.on(RoomEvent.DataReceived, (payload, _from, _kind, topic) => {
        if (topic !== REPORT_TOPIC) return;
        let report; try { report = JSON.parse(new TextDecoder().decode(payload)); } catch { return; }
        if (report?.v !== 1 || !Array.isArray(report.turns)) return;
        setCall((c) => (!c ? c : { ...c, report, ...(report.finished && c.state === 'live' ? { msg: 'Coach Brodie is breaking it down. Hang up when he’s done.' } : {}) }));
      });
      r.on(RoomEvent.TrackUnsubscribed, (track) => track.detach().forEach((el) => el !== agentVideo.current && el.remove()));
      // rooms hold two participants: anyone leaving is the partner (hung up, or the worker's call cap)
      r.on(RoomEvent.ParticipantDisconnected, () => end());
      r.on(RoomEvent.Disconnected, () => room.current === r && end());
      await r.connect(x.url, x.token);
      await r.startAudio();
      await r.localParticipant.setMicrophoneEnabled(true);
      let cam = true;
      try { await r.localParticipant.setCameraEnabled(true); } catch { cam = false; }
      liveAt.current = Date.now();
      update({ state: 'live', since: liveAt.current, mic: true, cam,
               msg: cam ? 'Say hi. Say “end practice” for your game review.' : 'No camera, so it’s voice-only: no body-language notes this time.' });
    } catch (e) {
      if (room.current === r) { room.current = null; r.disconnect(); }
      const denied = e?.name === 'NotAllowedError';
      update({ state: 'error', msg: denied ? 'Brodia needs your mic to talk. Allow it in the browser and try again.' : e.message, waitlist: !!e.waitlist });
    }
  }

  async function toggle(kind) {
    const p = room.current?.localParticipant;
    if (!p) return;
    try {
      if (kind === 'mic') { const next = !p.isMicrophoneEnabled; await p.setMicrophoneEnabled(next); update({ mic: next }); }
      else { const next = !p.isCameraEnabled; await p.setCameraEnabled(next); update({ cam: next }); }
    } catch { update({ msg: kind === 'mic' ? 'Couldn’t switch the mic.' : 'Couldn’t switch the camera.' }); }
  }

  useEffect(() => () => room.current?.disconnect(), []);
  return { call, start, end, toggle, close: () => { end(); setCall(null); }, refs: { agentVideo, audio } };
}

function useTicker(since) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!since) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [since]);
  return since ? clock(Math.max(0, (now - since) / 1000)) : null;
}

const Icon = {
  mic: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" /></svg>,
  micOff: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M15 10V6a3 3 0 0 0-5.7-1.3M9 9v2a3 3 0 0 0 5 2.2M5.5 11a6.5 6.5 0 0 0 10.4 5.2M18.5 11c0 .7-.1 1.3-.3 1.9M12 17.5V21M3 3l18 18" /></svg>,
  cam: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2.5" y="6" width="13" height="12" rx="3" /><path d="M15.5 10.5 21 7.5v9l-5.5-3" /></svg>,
  camOff: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15.5 10.5 21 7.5v9l-4-2.2M10 6h2.5a3 3 0 0 1 3 3v2.5M15.5 15.5V15a3 3 0 0 1-3 3h-7a3 3 0 0 1-3-3V9a3 3 0 0 1 2-2.8M3 3l18 18" /></svg>,
  end: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 9c-3.2 0-6.2 1-8.6 2.8-.6.5-.8 1.3-.4 2l1.2 2c.4.6 1.2.9 1.9.6l2.6-1c.6-.2 1-.8 1-1.4v-1.6c1.5-.4 3.1-.4 4.6 0V14c0 .6.4 1.2 1 1.4l2.6 1c.7.3 1.5 0 1.9-.6l1.2-2c.4-.7.2-1.5-.4-2C18.2 10 15.2 9 12 9Z" /></svg>,
};

export function CallPanel({ call, start, end, toggle, close, refs }) {
  const timer = useTicker(call?.state === 'live' ? call.since : 0);
  if (!call) return null;
  const s = SCENES[call.pick.scenario], m = MODES[call.pick.receptivity];
  if (call.state === 'ended' && call.report) {
    return (
      <div className="callwrap">
        <GameReview report={call.report} pick={call.pick} seconds={call.seconds} onAgain={() => start(call.pick)} onClose={close} />
      </div>
    );
  }
  const live = call.state === 'live', on = live || call.state === 'connecting';
  const score = live ? call.report?.score : null;
  const status = live ? timer : call.state === 'connecting' ? 'Calling' : call.state === 'error' ? 'Couldn’t connect' : 'Ended';
  return (
    <div className="callwrap" role="dialog" aria-modal="true" aria-label={`Practice call with ${s.name}`}>
      <div className="lcall" data-state={call.state}>
        <div className="lscreen">
          <div className="scene" data-s={call.pick.scenario} />
          {!(live && call.video) && <div className="lc-art"><Avatar id={s.avatar} /></div>}
          <video ref={refs.agentVideo} className="lc-video" autoPlay playsInline />
          {/* no self-view here: the worker's --mirror already draws the caller's camera as an inset in the partner video */}
          <div ref={refs.audio} hidden />
          <div className="top">
            <div className="who">{s.name}</div>
            <div className="where">{on && <i className="dot" />}<span>{s.label} · {m.label}</span><span>·</span><span className="t">{status}</span></div>
          </div>
          {score && (
            <>
              <span className="evalnum" aria-label="Rapport change so far">{score.now >= score.start ? '+' : '−'}{(Math.abs(score.now - score.start) / 10).toFixed(1)}</span>
              <div className="evalbar" aria-hidden="true"><i style={{ height: `${score.now}%` }} /></div>
            </>
          )}
          <p className="lc-msg" role="status">{call.msg}
            {call.waitlist && <> <a href="#waitlist" onClick={close}>Join the waitlist</a> and we’ll ping you.</>}</p>
          <div className="lc-controls">
            {on ? (
              <>
                <button type="button" className="ic" aria-pressed={live && !call.mic} aria-label={call.mic === false ? 'Unmute' : 'Mute'} disabled={!live} onClick={() => toggle('mic')}>{call.mic === false ? Icon.micOff : Icon.mic}</button>
                <button type="button" className="ic" aria-pressed={live && !call.cam} aria-label={call.cam === false ? 'Turn camera on' : 'Turn camera off'} disabled={!live} onClick={() => toggle('cam')}>{call.cam === false ? Icon.camOff : Icon.cam}</button>
                <button type="button" className="ic end" aria-label="End call" onClick={() => end()}>{Icon.end}</button>
              </>
            ) : (
              <>
                <button className="btn" type="button" onClick={() => start(call.pick)}>{call.state === 'error' ? 'Try again' : 'Call again'}</button>
                <button className="btn ghost" type="button" onClick={close}>Close</button>
              </>
            )}
          </div>
        </div>
        <p className="fine lc-fine">AI practice partner, 18+ fictional characters. Your camera and mic stream live to the AI; nothing is recorded. Calls end after 10 minutes.</p>
      </div>
    </div>
  );
}
