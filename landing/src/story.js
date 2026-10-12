import { AVATARS, GRADES, MODES, SCENES } from './data.js';
import { grade, summarize } from './review.js';

/* A 1080x1920 story card of a game review, drawn on a canvas with the site's scene gradients, character art and fonts.
   Shared through the Web Share API (on phones the share sheet offers Instagram / Snapchat stories), else downloaded.
   By default it shows no conversation text; `line` adds the caller's own best line. */

const W = 1080, H = 1920;
const SCENE_ART = {   // the .scene[data-s] gradients in index.css: [color, x, y, radius] blobs over a top->bottom gradient
  park: { from: '#9fd2f0', to: '#4e9a58', blobs: [['#bfe3ff', .2, .1, .6], ['#7cc27a', .85, .3, .65], ['#3f8f4f', .1, .7, .75]] },
  barista: { from: '#c99263', to: '#4a2b1a', blobs: [['#ffd79a', .75, .15, .4], ['#a8673c', .15, .35, .6], ['#5a3420', .8, .8, .75]] },
  street: { from: '#8ea3c4', to: '#26304a', blobs: [['#ffc56b', .2, .3, .2], ['#ff8f8f', .8, .22, .16], ['#47587a', .6, .6, .7]] },
};
const INK = { brill: '#26c4bb', great: '#6a9de3', best: '#86c44a', inacc: '#ecc03a', mist: '#f59846', blund: '#f0565a', book: '#3a3352' };
const GO = '#3ddc84';
const DISPLAY = '"Bricolage Grotesque", "Avenir Next", system-ui, sans-serif';
const BODY = 'Figtree, "Avenir Next", system-ui, sans-serif';
const MONO = '"JetBrains Mono", ui-monospace, monospace';

const loadImage = (src) => new Promise((ok, fail) => { const i = new Image(); i.onload = () => ok(i); i.onerror = fail; i.src = src; });

function rounded(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.roundRect(x, y, w, h, r); ctx.fill();
}

function wrap(ctx, text, maxWidth, maxLines) {
  const words = text.split(/\s+/), lines = [];
  let line = '';
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (ctx.measureText(next).width > maxWidth && line) { lines.push(line); line = w; } else line = next;
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) { lines.length = maxLines; lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, '') + '…'; }
  return lines;
}

function drawScene(ctx, scenario) {
  const art = SCENE_ART[scenario] || SCENE_ART.park;
  const g = ctx.createLinearGradient(0, 0, 0, H); g.addColorStop(0, art.from); g.addColorStop(1, art.to);
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  for (const [c, x, y, r] of art.blobs) {
    const rg = ctx.createRadialGradient(x * W, y * H, 0, x * W, y * H, r * W);
    rg.addColorStop(0, c); rg.addColorStop(1, c + '00');
    ctx.fillStyle = rg; ctx.fillRect(0, 0, W, H);
  }
}

async function drawAvatar(ctx, id, y) {
  const img = await loadImage(`/avatars/${id}.png`);
  const w = 1560, h = (w * 408) / 612, x = (W - w) / 2;
  const off = document.createElement('canvas'); off.width = w; off.height = h;
  const o = off.getContext('2d');
  o.drawImage(img, 0, 0, w, h);
  const a = AVATARS[id], px = ([fx, fy]) => [(fx / 612) * w, (fy / 408) * h];   // the faces are drawn on, like the site's Avatar
  o.fillStyle = 'rgb(41, 35, 30)';
  for (const p of a.eyes) { const [cx, cy] = px(p); o.beginPath(); o.ellipse(cx, cy, w * .0147, h * .0318, 0, 0, Math.PI * 2); o.fill(); }
  for (const p of a.brows) { const [cx, cy] = px(p); rounded(o, cx - w * .0278, cy - h * .0074, w * .0556, h * .0147, 6); }
  { const [cx, cy] = px(a.mouth); rounded(o, cx - w * .0262, cy - h * .0122, w * .0523, h * .0245, 10); }
  const fade = o.createLinearGradient(0, 0, 0, h); fade.addColorStop(.72, '#000'); fade.addColorStop(.99, '#0000');
  o.globalCompositeOperation = 'destination-in'; o.fillStyle = fade; o.fillRect(0, 0, w, h);
  ctx.drawImage(off, x, y);
}

function glyph(ctx, g, cx, cy, r) {
  ctx.fillStyle = INK[g]; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = g === 'book' ? '#a59fbb' : '#fff'; ctx.font = `700 ${Math.round(r * .9)}px ${MONO}`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(GRADES[g].sym, cx, cy + r * .04);
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
}

export async function renderStory(report, pick, seconds, { line = false } = {}) {
  await Promise.all([`800 200px ${DISPLAY}`, `700 60px ${DISPLAY}`, `600 44px ${BODY}`, `500 32px ${MONO}`, `700 32px ${MONO}`]
    .map((f) => document.fonts?.load(f).catch(() => {})));
  const c = document.createElement('canvas'); c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  const s = SCENES[pick.scenario], m = MODES[pick.receptivity], sum = summarize(report, seconds);

  // the stats block is laid out bottom-up from just above the call to action, so a best line never collides with it
  ctx.font = `600 46px ${BODY}`;
  const quote = line && sum.best ? wrap(ctx, `“${sum.best.quote}”`, W - 260, 3) : [];
  const blockH = 362 + (sum.tally.length ? 130 : 0) + (sum.outcome ? 110 : 0) + (quote.length ? 70 + quote.length * 60 : 0);
  const y0 = H - 270 - blockH;                                  // the "AURA" label baseline

  drawScene(ctx, pick.scenario);
  const top = ctx.createLinearGradient(0, 0, 0, 420); top.addColorStop(0, 'rgba(0,0,0,.45)'); top.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = top; ctx.fillRect(0, 0, W, 420);
  await drawAvatar(ctx, s.avatar, Math.min(250, y0 - 900)).catch(() => {});
  const shade = ctx.createLinearGradient(0, y0 - 380, 0, y0 - 40); shade.addColorStop(0, 'rgba(13,10,22,0)'); shade.addColorStop(1, '#0d0a16');
  ctx.fillStyle = shade; ctx.fillRect(0, y0 - 380, W, 340); ctx.fillStyle = '#0d0a16'; ctx.fillRect(0, y0 - 41, W, H - y0 + 41);

  // brand row
  ctx.fillStyle = GO; ctx.beginPath(); ctx.arc(92, 132, 14, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#fff'; ctx.font = `800 64px ${DISPLAY}`; ctx.fillText('brodia', 122, 154);
  ctx.font = `500 30px ${MONO}`; ctx.textAlign = 'right'; ctx.fillText('GAME REVIEW', W - 80, 150); ctx.textAlign = 'left';
  ctx.font = `700 58px ${DISPLAY}`; ctx.fillText(s.name, 80, 300);
  ctx.font = `500 30px ${MONO}`; ctx.globalAlpha = .85; ctx.fillText(`${s.label.toUpperCase()} · ${m.label.toUpperCase()} · ${sum.clock}`, 80, 352); ctx.globalAlpha = 1;

  // score
  let y = y0;
  ctx.fillStyle = '#a59fbb'; ctx.font = `500 32px ${MONO}`; ctx.fillText('AURA', 80, y);
  ctx.fillStyle = '#fff'; ctx.font = `800 240px ${DISPLAY}`; const aura = sum.aura.toLocaleString(); ctx.fillText(aura, 70, y + 210);
  const aw = ctx.measureText(aura).width;
  ctx.fillStyle = sum.gain < 0 ? INK.blund : GO; ctx.font = `700 52px ${MONO}`; ctx.fillText(sum.gainText, 70 + aw + 28, y + 200);
  y += 300;
  ctx.fillStyle = '#fff'; ctx.font = `700 70px ${DISPLAY}`; ctx.fillText(sum.rank, 80, y);
  ctx.fillStyle = '#a59fbb'; ctx.font = `500 40px ${BODY}`;
  ctx.fillText(sum.accuracy === null ? 'No graded lines' : `${sum.accuracy}% accuracy`, 80, y + 62);
  y += 62;

  if (sum.tally.length) {                                         // grade tally
    y += 130; let x = 80;
    for (const [g, n] of sum.tally) {
      glyph(ctx, g, x + 34, y - 16, 34);
      ctx.fillStyle = '#fff'; ctx.font = `700 44px ${MONO}`; ctx.fillText(`×${n}`, x + 80, y);
      x += 80 + ctx.measureText(`×${n}`).width + 40;
    }
  }
  if (sum.outcome) {
    y += 110; ctx.font = `600 40px ${BODY}`;
    const text = sum.outcome.text, tw = ctx.measureText(text).width;
    ctx.fillStyle = sum.outcome.good ? 'rgba(61,220,132,.16)' : 'rgba(255,255,255,.1)'; rounded(ctx, 80, y - 54, tw + 64, 80, 40);
    ctx.fillStyle = sum.outcome.good ? GO : '#d9d4ea'; ctx.fillText(text, 112, y);
  }
  if (quote.length) {
    y += 130; glyph(ctx, grade(sum.best), 114, y - 16, 34);
    ctx.fillStyle = '#fff'; ctx.font = `600 46px ${BODY}`;
    quote.forEach((l, i) => ctx.fillText(l, 172, y + i * 60));
  }

  // call to action
  ctx.fillStyle = GO; rounded(ctx, 80, H - 200, 440, 104, 52);
  ctx.fillStyle = '#0b2615'; ctx.font = `700 42px ${BODY}`; ctx.fillText('Shoot your shot', 124, H - 134);
  ctx.fillStyle = '#d9d4ea'; ctx.font = `500 34px ${MONO}`; ctx.textAlign = 'right'; ctx.fillText('brodia.vercel.app', W - 80, H - 136); ctx.textAlign = 'left';

  const blob = await new Promise((ok) => c.toBlob(ok, 'image/png'));
  return new File([blob], 'brodia-game-review.png', { type: 'image/png' });
}

export const canShare = (file) => !!(file && navigator.canShare?.({ files: [file] }));

export async function shareStory(file) {
  try { await navigator.share({ files: [file], title: 'My Brodia game review' }); return 'shared'; }
  catch (e) { return e?.name === 'AbortError' ? 'cancelled' : 'failed'; }
}

export function saveStory(file) {
  const url = URL.createObjectURL(file), a = document.createElement('a');
  a.href = url; a.download = file.name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
