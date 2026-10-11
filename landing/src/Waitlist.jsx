import { useEffect, useState } from 'react';

// Val Town val tahar/brodia-waitlist; override with VITE_WAITLIST_URL.
const URL = import.meta.env.VITE_WAITLIST_URL || 'https://tahar--01a12b6d248575e29f9d54f4968e5c05.web.val.run';

export default function Waitlist({ pick }) {
  const [email, setEmail] = useState('');
  const [trap, setTrap] = useState(''); // honeypot: bots fill it, people never see it
  const [state, setState] = useState('idle'); // idle | sending | done | error
  const [error, setError] = useState('');
  const [count, setCount] = useState(null);

  useEffect(() => {
    if (!URL) return;
    fetch(URL).then((r) => r.ok ? r.json() : null).then((d) => d && setCount(d.count)).catch(() => {});
  }, []);

  async function submit(e) {
    e.preventDefault();
    if (!URL) { setState('error'); setError('Waitlist isn’t connected yet.'); return; }
    setState('sending'); setError('');
    try {
      const ref = new URLSearchParams(location.search).get('ref') || document.referrer || '';
      const r = await fetch(URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, company: trap, ref: ref.slice(0, 200), ...pick }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || 'Couldn’t save that. Try again.');
      if (typeof d.count === 'number') setCount(d.count);
      setState('done');
    } catch (err) {
      setState('error'); setError(err.message);
    }
  }

  return (
    <section className="waitlist" id="waitlist">
      <h2>Get in line.</h2>
      <p className="sub">Early access drops soon. Don’t fumble it.</p>
      {state === 'done' ? (
        <p className="done" role="status"><img src="/avatars/brodie-coach-hype.png" alt="" width="1024" height="1024" />You’re in. +50 aura.</p>
      ) : (
        <form className="join" onSubmit={submit}>
          <label className="sr" htmlFor="wl-email">Email</label>
          <input id="wl-email" type="email" required autoComplete="email" placeholder="you@school.edu"
                 value={email} onChange={(e) => setEmail(e.target.value)} />
          <input className="trap" tabIndex={-1} autoComplete="off" aria-hidden="true" name="company"
                 value={trap} onChange={(e) => setTrap(e.target.value)} />
          <button className="btn" type="submit" disabled={state === 'sending'}>{state === 'sending' ? 'Locking in…' : 'Lock in'}</button>
        </form>
      )}
      {state === 'error' && <p className="err" role="alert">{error}</p>}
      {count > 0 && <p className="count">{count.toLocaleString()} already locked in</p>}
    </section>
  );
}
