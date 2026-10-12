import { GRADES } from './data.js';
import { Cam, Glyph } from './ui.jsx';

/* The real game review after a call: the worker's "brodia.report" snapshot (facetime/brodia_report.py), drawn like the
   sample on the landing page. Nothing here is stored; it disappears with the dialog. */

const RANKS = ['NPC arc', 'Warming up', 'Solid game', 'Aura farmer', 'Rizz god'];   // by rapport band 0..4
const REQUESTS = { contact: 'Her number', date: 'A date', meet_again: 'See you again', continue: 'Keep talking' };

export function grade(turn) {
  if (turn.type === 'positive') return turn.delta >= 3 ? 'brill' : turn.delta === 2 ? 'great' : 'best';
  if (turn.type === 'negative') return turn.delta <= -3 ? 'blund' : turn.delta === -2 ? 'mist' : 'inacc';
  return 'book';
}

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

function Graph({ start, turns, duration }) {
  const W = 102, H = 60, y = (score) => H - (score / 100) * H;
  const x = (t) => (duration > 0 ? Math.min(W, (t / duration) * W) : 0);
  const pts = [[0, y(start)], ...turns.map((t) => [x(t.t), y(t.score)])];
  const last = pts[pts.length - 1];
  const line = pts.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)} ${py.toFixed(1)}`).join(' ');
  return (
    <svg className="graph" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
         aria-label={`Rapport over the call: from ${start} to ${turns.at(-1)?.score ?? start} out of 100`}>
      <path className="up" d={`${line} L${W} ${last[1].toFixed(1)} L${W} ${H} L0 ${H} Z`} />
      <line className="mid" x1="0" y1={y(start)} x2={W} y2={y(start)} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function GameReview({ report, pick, seconds, onAgain, onClose }) {
  const scored = report.turns.filter((t) => t.type !== 'uncertain');
  const unclear = report.turns.length - scored.length;
  const accuracy = scored.length ? Math.round((100 * scored.filter((t) => t.delta >= 0).length) / scored.length) : null;
  const gained = report.score.now - report.score.start;
  const duration = Math.max(seconds || 0, ...report.turns.map((t) => t.t), 1);

  return (
    <article className="report live" aria-label="Your game review">
      <div className="rhead"><span>Game review</span><span>{clock(seconds || 0)} call</span></div>
      <div className="score">
        <div>
          <div className="aura-lbl">Aura</div>
          <div className="aura"><b>{(report.score.now * 10).toLocaleString()}</b>
            <span className={`delta${gained < 0 ? ' down' : ''}`}>{gained >= 0 ? '+' : '−'}{Math.abs(gained * 10)}</span></div>
        </div>
        <div className="rank"><strong>{RANKS[report.score.band] || RANKS[0]}</strong>
          <span>{accuracy === null ? 'No graded lines yet' : `${accuracy}% accuracy`}</span></div>
      </div>

      <Graph start={report.score.start} turns={report.turns} duration={duration} />
      <div className="gaxis"><span>0:00</span><span>{clock(duration / 2)}</span><span>{clock(duration)}</span></div>

      {report.outcomes.length > 0 && (
        <ul className="outcomes">
          {report.outcomes.map((o) => (
            <li key={o.request} className={o.accepted ? 'yes' : 'no'}>{REQUESTS[o.request] || o.request}: <b>{o.accepted ? 'yes' : 'no'}</b></li>
          ))}
        </ul>
      )}

      {scored.length > 0 ? (
        <ol className="moves">
          {scored.map((t, i) => {
            const g = grade(t);
            return (
              <li key={i}>
                <span className="ts">{clock(t.t)}</span>
                <Glyph grade={g} />
                <div><p><q>{t.quote}</q> <span className="why">{GRADES[g].name}. {t.reason}</span></p></div>
              </li>
            );
          })}
        </ol>
      ) : <p className="empty">Not enough to grade yet. Say a few lines next time.</p>}
      {unclear > 0 && <p className="fine">{unclear} {unclear === 1 ? 'line was' : 'lines were'} too unclear to grade, so they didn’t count.</p>}

      {report.visual.length > 0 && (
        <ul className="seen">{report.visual.map((v, i) => <li key={i}><Cam />{v}</li>)}</ul>
      )}

      <div className="coachsays">
        <img src="/avatars/brodie-coach.png" alt="" width="1024" height="1024" />
        <p>{report.coach
          ? <><b>Coach Brodie</b>{report.coach}</>
          : <><b>Coach Brodie</b>{report.finished ? 'Hung up before I finished. Stay on next time for the full breakdown.' : 'Say “end practice” before you hang up and I’ll break it down for you.'}</>}</p>
      </div>

      <div className="next">
        <button className="btn" type="button" onClick={onAgain}>Run it back</button>
        <button className="btn ghost" type="button" onClick={onClose}>Close</button>
      </div>
    </article>
  );
}
