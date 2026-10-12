import { AVATARS, GRADES } from './data.js';

export const Cam = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" {...p}>
    <rect x="2.5" y="6" width="13" height="12" rx="3" /><path d="M15.5 10.5 21 7.5v9l-5.5-3" />
  </svg>
);

export function Glyph({ grade, className = '' }) {
  return <span className={`g ${grade} ${className}`} aria-hidden="true">{GRADES[grade].sym}</span>;
}

/* The faceless figurine with eyes, brows and mouth drawn on top, like the app's avatar. */
export function Avatar({ id }) {
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
