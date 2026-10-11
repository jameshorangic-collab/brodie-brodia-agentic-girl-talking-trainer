import { useEffect, useState } from 'react';
import { AVATARS, GRADES, MODES, SAMPLE_MOVES, SCENES } from './data.js';
import Waitlist from './Waitlist.jsx';

const Cam = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" {...p}>
    <rect x="2.5" y="6" width="13" height="12" rx="3" /><path d="M15.5 10.5 21 7.5v9l-5.5-3" />
  </svg>
);

function Glyph({ grade, className = '' }) {
  return <span className={`g ${grade} ${className}`} aria-hidden="true">{GRADES[grade].sym}</span>;
}

function useCallTimer(resetKey) {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    setSec(0);
    const t0 = Date.now();
    const id = setInterval(() => setSec(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [resetKey]);
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

function Chips({ label, options, value, onChange }) {
  return (
    <div className="row" role="group" aria-label={label}>
      <span className="lbl">{label}</span>
      {Object.entries(options).map(([key, o]) => (
        <button key={key} type="button" className="chip" aria-pressed={value === key} onClick={() => onChange(key)}>{o.label}</button>
      ))}
    </div>
  );
}

/* The faceless figurine with eyes, brows and mouth drawn on top, like the app's avatar. */
function Avatar({ id }) {
  const a = AVATARS[id];
  const at = ([x, y]) => ({ left: `${(x / 612) * 100}%`, top: `${(y / 408) * 100}%` });
  return (
    <div className="avatar" key={id}>
      <img src={`/avatars/${id}.png`} alt="" width="612" height="408" />
      {a.brows.map((p, i) => <i key={`b${i}`} className="brow" style={at(p)} />)}
      {a.eyes.map((p, i) => <i key={`e${i}`} className="eye" style={at(p)} />)}
      <i className="mouth" style={at(a.mouth)} />
    </div>
  );
}

function Phone({ scene, mode }) {
  const s = SCENES[scene], m = MODES[mode];
  const timer = useCallTimer(scene + mode);
  return (
    <div className="phone" aria-hidden="true">
      <div className="screen">
        <div className="scene" data-s={scene} />
        <Avatar id={s.avatar} />
        <div className="top">
          <div className="who">{s.name}</div>
          <div className="where"><i className="dot" /><span>{s.label}</span><span>·</span><span className="t">{timer}</span></div>
        </div>
        <span className="evalnum">{m.num}</span>
        <div className="evalbar"><i style={{ height: `${m.bar}%` }} /></div>
        <div className="self" />
        {/* keyed so the bubble and its grade re-animate on every pick */}
        <div className="bubble" key={scene + mode}>{s[mode]}<Glyph grade={m.grade} /></div>
        <div className="controls">
          <span><svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" /></svg></span>
          <span><Cam stroke="#fff" strokeWidth="2" /></span>
          <span className="end"><svg viewBox="0 0 24 24" fill="#fff"><path d="M12 9c-3.2 0-6.2 1-8.6 2.8-.6.5-.8 1.3-.4 2l1.2 2c.4.6 1.2.9 1.9.6l2.6-1c.6-.2 1-.8 1-1.4v-1.6c1.5-.4 3.1-.4 4.6 0V14c0 .6.4 1.2 1 1.4l2.6 1c.7.3 1.5 0 1.9-.6l1.2-2c.4-.7.2-1.5-.4-2C18.2 10 15.2 9 12 9Z" /></svg></span>
        </div>
      </div>
    </div>
  );
}

function Review() {
  return (
    <section className="after">
      <div>
        <img className="coach" src="/avatars/brodie-coach.png" alt="Coach Brodie in a backwards cap, holding a rose and giving a thumbs up" width="1024" height="1024" />
        <h2>Game review.</h2>
        <p className="sub">Coach Brodie grades every line. No cap.</p>
        <ul className="legend" aria-label="Move grades">
          {['brill', 'inacc', 'great', 'mist', 'best', 'blund'].map((g) => (
            <li key={g}><Glyph grade={g} /><span>{GRADES[g].name}{g === 'blund' && <small> · ignoring a no</small>}</span></li>
          ))}
        </ul>
      </div>

      <article className="report" aria-label="Sample game review">
        <div className="rhead"><span>Sample · Park · Mid</span><span>1:42 call</span></div>
        <div className="score">
          <div>
            <div className="aura-lbl">Aura</div>
            <div className="aura"><b>1,340</b><span className="delta">+86</span></div>
          </div>
          <div className="rank"><strong>Aura farmer</strong><span>87% accuracy</span></div>
        </div>

        {/* eval over the call: x = seconds (0 to 102), y = eval (midline 30, up = going well) */}
        <svg className="graph" viewBox="0 0 102 60" preserveAspectRatio="none" role="img" aria-label="Evaluation over the call: up after the opener, dips at 0:04 and 0:51, ends high">
          <path className="up" d="M0 30 L2 18 L4 26 L19 14 L51 34 L70 22 L90 12 L102 10 L102 60 L0 60 Z" />
          <line className="mid" x1="0" y1="30" x2="102" y2="30" vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="gaxis"><span>0:00</span><span>0:51</span><span>1:42</span></div>

        <ol className="moves">
          {SAMPLE_MOVES.map((m) => (
            <li key={m.ts}>
              <span className="ts">{m.ts}</span>
              <Glyph grade={m.grade} />
              <div>
                <p>{m.quote && <q>{m.quote}</q>} {m.text}</p>
                {m.cam && <span className="cam"><Cam />caught on cam</span>}
              </div>
            </li>
          ))}
        </ol>

        <div className="next">
          <p><b>Next game</b>Same opener. Dip sooner.</p>
        </div>
      </article>
    </section>
  );
}

export default function App() {
  const [scene, setScene] = useState('park');
  const [mode, setMode] = useState('neutral');
  const m = MODES[mode];

  return (
    <div className="wrap">
      <nav>
        <a className="mark" href="#top"><i />brodia</a>
        <a className="btn small" href="#waitlist"><span>Shoot your shot</span><Cam /></a>
      </nav>

      <main id="top">
        <section className="hero">
          <div>
            <div className="kicker"><Glyph grade="brill" />Rizz sim · on FaceTime</div>
            <h1>Shoot your <em>shot.</em></h1>
            <p className="lede">FaceTime her. Get rated. Farm aura.</p>

            <div className="picker">
              <Chips label="Map" options={SCENES} value={scene} onChange={setScene} />
              <Chips label="Difficulty" options={MODES} value={mode} onChange={setMode} />
              <p className="hint" aria-live="polite"><b>{m.lead}</b> {m.hint}</p>
            </div>

            <div className="cta">
              <a className="btn" href="#waitlist">Lock in
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </a>
              <span className="note">No app. Just FaceTime.</span>
            </div>
          </div>

          <div className="stage"><Phone scene={scene} mode={mode} /></div>
        </section>

        <Review />
        <Waitlist pick={{ scenario: scene, receptivity: mode }} />
      </main>

      <footer>
        <span>AI practice. All characters 18+. Taking the L gracefully = +aura.</span>
        <span>Made at IvyHacks 2026</span>
      </footer>
    </div>
  );
}
