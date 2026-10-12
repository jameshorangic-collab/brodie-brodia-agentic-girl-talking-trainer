import { useState } from 'react';
import { GRADES, MODES, SCENES } from './data.js';
import { Avatar, Cam, Glyph } from './ui.jsx';
import { clock, grade, summarize } from './review.js';
import StoryShare from './StoryShare.jsx';

/* The real game review after a call: the worker's "brodia.report" snapshot (facetime/brodia_report.py). Nothing here is
   stored; it disappears with the dialog. */

function Graph({ start, turns, duration }) {
  const W = 102, H = 60, y = (score) => H - (score / 100) * H;
  const x = (t) => Math.min(W, (t / duration) * W);
  const pts = [[0, y(start)], ...turns.map((t) => [x(t.t), y(t.score)])];
  const line = pts.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)} ${py.toFixed(1)}`).join(' ');
  return (
    <svg className="graph" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
         aria-label={`Rapport over the call: from ${start} to ${turns.at(-1)?.score ?? start} out of 100`}>
      <path className="up" d={`${line} L${W} ${pts.at(-1)[1].toFixed(1)} L${W} ${H} L0 ${H} Z`} />
      <line className="mid" x1="0" y1={y(start)} x2={W} y2={y(start)} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const StoryIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="6" y="2.5" width="12" height="19" rx="3" /><path d="M12 7v7M9 10l3-3 3 3" />
  </svg>
);

export default function GameReview({ report, pick, seconds, onAgain, onClose }) {
  const s = SCENES[pick.scenario], m = MODES[pick.receptivity], sum = summarize(report, seconds);
  const [sharing, setSharing] = useState(false);

  return (
    <div className="rsheet" role="dialog" aria-modal="true" aria-label="Your game review">
      <div className="rscroll">
        <header className="rhero">
          <div className="scene" data-s={pick.scenario} />
          <div className="rhero-art"><Avatar id={s.avatar} /></div>
          <div>
            <div className="rkick">Game review · {s.name} · {m.label}</div>
            <div className="aura-lbl">Aura</div>
            <div className="aura"><b>{sum.aura.toLocaleString()}</b><span className={`delta${sum.gain < 0 ? ' down' : ''}`}>{sum.gainText}</span></div>
            <div className="rank"><strong>{sum.rank}</strong>
              <span>{sum.accuracy === null ? 'No graded lines yet' : `${sum.accuracy}% accuracy`} · {sum.clock} call</span></div>
          </div>
        </header>

        {(sum.tally.length > 0 || sum.outcome) && (
          <div className="rbadges">
            {sum.outcome && <span className={`outcome ${sum.outcome.good ? 'yes' : 'no'}`}>{sum.outcome.text}</span>}
            {sum.tally.map(([g, n]) => <span key={g} className="tally" title={GRADES[g].name}><Glyph grade={g} />×{n}</span>)}
          </div>
        )}

        <div className="coachsays">
          <img src="/avatars/brodie-coach.png" alt="" width="1024" height="1024" />
          <p><b>Coach Brodie</b>{report.coach
            || (report.finished ? 'You hung up before I finished. Stay on next time for the full breakdown.'
                                : 'Say “end practice” before you hang up and I’ll break it down for you.')}</p>
        </div>

        {sum.scored.length > 0 && (
          <section aria-label="Rapport over the call">
            <Graph start={report.score.start} turns={report.turns} duration={sum.duration} />
            <div className="gaxis"><span>0:00</span><span>{clock(sum.duration / 2)}</span><span>{clock(sum.duration)}</span></div>
          </section>
        )}

        {sum.scored.length > 0 ? (
          <ol className="rmoves" aria-label="Your lines, graded">
            {sum.scored.map((t, i) => {
              const g = grade(t);
              return (
                <li key={i}>
                  <details>
                    <summary><span className="ts">{clock(t.t)}</span><Glyph grade={g} /><q>{t.quote}</q></summary>
                    <p><b className={`kind ${g}`}>{GRADES[g].name}.</b> {t.reason}</p>
                  </details>
                </li>
              );
            })}
          </ol>
        ) : <p className="empty">Not enough to grade yet. Say a few lines next time.</p>}
        {sum.unclear > 0 && <p className="fine">{sum.unclear} {sum.unclear === 1 ? 'line was' : 'lines were'} too unclear to grade, so they didn’t count.</p>}

        {report.visual.length > 0 && <ul className="seen">{report.visual.map((v, i) => <li key={i}><Cam />{v}</li>)}</ul>}
      </div>

      <footer className="ractions">
        <button className="btn" type="button" onClick={() => setSharing(true)}><StoryIcon />Share to story</button>
        <button className="btn ghost" type="button" onClick={onAgain}>Run it back</button>
        <button className="btn ghost x" type="button" onClick={onClose} aria-label="Close">✕</button>
      </footer>

      {sharing && <StoryShare report={report} pick={pick} seconds={seconds} best={sum.best} onClose={() => setSharing(false)} />}
    </div>
  );
}
