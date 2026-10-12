import { GRADES } from './data.js';

export const Cam = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" {...p}>
    <rect x="2.5" y="6" width="13" height="12" rx="3" /><path d="M15.5 10.5 21 7.5v9l-5.5-3" />
  </svg>
);

export function Glyph({ grade, className = '' }) {
  return <span className={`g ${grade} ${className}`} aria-hidden="true">{GRADES[grade].sym}</span>;
}
