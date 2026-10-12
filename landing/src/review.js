/* Shared reading of a worker "brodia.report" snapshot (facetime/brodia_report.py) for Review.jsx and the story card. */

export const RANKS = ['NPC arc', 'Warming up', 'Solid game', 'Aura farmer', 'Rizz god'];   // by rapport band 0..4
export const TALLY_ORDER = ['brill', 'great', 'best', 'inacc', 'mist', 'blund'];
const WON = { contact: 'Got her number', date: 'Locked in a date', meet_again: 'She wants to see you again', continue: 'She kept it going' };
const LOST = { contact: 'No number this time', date: 'No date this time', meet_again: 'Not this time', continue: 'She wrapped it up' };

export function grade(turn) {
  if (turn.type === 'positive') return turn.delta >= 3 ? 'brill' : turn.delta === 2 ? 'great' : 'best';
  if (turn.type === 'negative') return turn.delta <= -3 ? 'blund' : turn.delta === -2 ? 'mist' : 'inacc';
  return 'book';
}

export const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export function summarize(report, seconds) {
  const scored = report.turns.filter((t) => t.type !== 'uncertain');
  const gain = report.score.now - report.score.start;
  const counts = Object.fromEntries(TALLY_ORDER.map((g) => [g, 0]));
  for (const t of scored) { const g = grade(t); if (g in counts) counts[g] += 1; }
  const won = ['contact', 'date', 'meet_again', 'continue'].map((r) => report.outcomes.find((o) => o.request === r && o.accepted)).find(Boolean);
  const lost = report.outcomes.find((o) => !o.accepted);
  const best = scored.filter((t) => t.type === 'positive').sort((a, b) => b.delta - a.delta || a.t - b.t)[0] || null;
  const duration = Math.max(seconds || 0, ...report.turns.map((t) => t.t), 1);
  return {
    scored, unclear: report.turns.length - scored.length, duration, clock: clock(seconds || 0),
    aura: report.score.now * 10, gain, gainText: `${gain >= 0 ? '+' : '−'}${Math.abs(gain * 10)}`,
    rank: RANKS[report.score.band] || RANKS[0],
    accuracy: scored.length ? Math.round((100 * scored.filter((t) => t.delta >= 0).length) / scored.length) : null,
    tally: TALLY_ORDER.filter((g) => counts[g]).map((g) => [g, counts[g]]),
    outcome: won ? { text: WON[won.request], good: true } : lost ? { text: LOST[lost.request], good: false } : null,
    best,
  };
}
