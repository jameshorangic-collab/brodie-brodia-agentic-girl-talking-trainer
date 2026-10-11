"""Render the closed cue vocabulary to PCM with a TTS API and cache it.

Gemini TTS (the current flash TTS model from client.models.list(), generate_content with
response_modalities=["AUDIO"], one prebuilt voice, audio comes back as a 24 kHz s16 mono WAV, resampled if ever not
24 kHz) writes data/cues_audio_gemini/. Each manifest maps text to {file, duration_s, chars,
model, voice, backend}. Clips are <sha1 of text>.pcm, exactly what the "coach-audio"
LiveKit track carries. Rendering is idempotent: clips already in the manifest with a file on disk are skipped.
Leading and trailing silence below -40 dBFS is trimmed, keeping 60 ms of tail so the end of a word is not clipped.
Gemini is billed per token (text in, audio out): the usage metadata totals are printed.

Run:  .venv/bin/python -m facetime.cues_tts [--voice Puck] [--model ...] [--dry-run]
"""
import argparse, hashlib, json, os, sys, time, concurrent.futures as cf
import numpy as np
from facetime import CUES_DIR_GEMINI, SAMPLE_RATE
from rtcoach.coach import CUES, PRAISE, COUNT_WORDS
from rtcoach.exmap import LR2CLF

SILENCE_DBFS = -40.0
TAIL_S = 0.060
COUNT_TRIM = (-45.0, 0.030)          # count words: do not clip a soft onset, keep only 30 ms of tail (immediacy)

def count_words():
    return {w.capitalize() for w in COUNT_WORDS.values()} | {str(n) for n in range(21, 31)}

def trim_params(text):
    return COUNT_TRIM if text in count_words() else (SILENCE_DBFS, TAIL_S)

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
def number_word(n):
    """1..30 as words (Coach.COUNT_WORDS stops at twenty)."""
    if n <= 20: return ONES[n]
    if n < 30: return 'twenty ' + ONES[n - 20]
    return 'thirty'

def exercise_names():
    """Every exercise name the coach can say: the LR2CLF keys plus the plain demo names."""
    return sorted(set(LR2CLF) | {'squats', 'pushups', 'lunges', 'jumping jacks'})

def vocabulary():
    """Every string the coach can say. Order is stable (sorted) so the manifest diff is readable."""
    v = set()
    v.update(c['cue'] for c in CUES.values() if c.get('cue'))
    v.update(PRAISE)
    v.update(w.capitalize() for w in COUNT_WORDS.values())
    v.update(str(n) for n in range(21, 31))                       # Coach says digits past twenty
    v.update(f"That's {n}" for n in (5, 10, 15, 20, 25, 30))
    v.update(["Let's go", "That's it"])
    names = exercise_names()
    v.update(f"Let's do {ex}" for ex in names)
    # session script (facetime/session.py): plan mode, auto mode, tempo
    v.update(f"That's {number_word(n)}, nice work" for n in range(1, 31))
    v.update(f"Moving on to {ex}" for ex in names)
    v.update(f"Looks like {ex}" for ex in names)
    v.update(["Rest for a moment", "All done, great session", "Nice work", "Slow down", "Pick up the pace"])
    v.update(["Okay, moving on"])                                    # --gesture-next: the T-pose command (facetime/probe.py TPose)
    v.update(["Step back so I can see your whole body", "Great, I can see you", "I will wait here, step into view when you are ready"])   # facetime/visibility.py
    v.update(["Probe ready, raise both arms"])                      # latency probe (coach_agent --latency-probe)
    bad = [t for t in v if '\u2014' in t or '\u2013' in t]
    assert not bad, f'dashes in cue text: {bad}'
    return sorted(v)

def sha1(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()

def trim(pcm, rate=SAMPLE_RATE, dbfs=SILENCE_DBFS, tail_s=TAIL_S):
    """Trim leading/trailing samples below `dbfs`, keep `tail_s` of tail after the last loud sample."""
    x = np.frombuffer(pcm, np.int16)
    thr = 32767 * 10 ** (dbfs / 20)
    loud = np.flatnonzero(np.abs(x.astype(np.int32)) > thr)
    if len(loud) == 0:
        return x.tobytes()
    a = int(loud[0]); b = min(len(x), int(loud[-1]) + 1 + int(tail_s * rate))
    return x[a:b].tobytes()

def load_manifest(cues_dir=CUES_DIR_GEMINI):
    mf = os.path.join(cues_dir, 'manifest.json')
    if os.path.exists(mf):
        return json.load(open(mf))
    return {}

def save_manifest(m, cues_dir=CUES_DIR_GEMINI):
    os.makedirs(cues_dir, exist_ok=True)
    mf = os.path.join(cues_dir, 'manifest.json'); tmp = mf + '.tmp'
    json.dump(m, open(tmp, 'w'), indent=1, sort_keys=True); os.replace(tmp, mf)

def bank_complete(cues_dir):
    """True when every vocabulary string has a clip on disk in that bank."""
    m = load_manifest(cues_dir)
    return all(t in m and os.path.exists(os.path.join(cues_dir, m[t]['file'])) for t in vocabulary())

# ---- gemini backend ----
GEMINI_USD = {'text_in_per_m': 0.50, 'audio_out_per_m': 10.0}      # gemini-2.5-flash-preview-tts list price; the 3.8 model is assumed the same

def gemini_client(api_key=None):
    """genai.Client on the key from GEMINI_API_KEY. With env GEMINI_BASE_URL set (hackathon: the key is a team token and the relay in
    modal/gemini_relay.py holds the real one) every call goes to that base URL instead of Google; unset, the client is built as before."""
    from google import genai
    key = api_key or os.environ['GEMINI_API_KEY']
    base_url = (os.environ.get('GEMINI_BASE_URL') or '').strip().rstrip('/')
    if not base_url:
        return genai.Client(api_key=key)
    from google.genai import types
    print(f'[cues_tts] gemini via relay {base_url}', flush=True)
    return genai.Client(api_key=key, http_options=types.HttpOptions(base_url=base_url))

def gemini_pick_model(client, want):
    names = [m.name.split('/')[-1] for m in client.models.list() if 'tts' in m.name.lower()]
    if want in names:
        return want
    for f in (lambda n: 'flash' in n and 'lite' not in n and 'preview' not in n, lambda n: 'flash' in n and 'lite' not in n,
              lambda n: 'flash' in n, lambda n: True):
        c = [n for n in names if f(n)]
        if c:
            return sorted(c)[-1]
    raise SystemExit(f'no Gemini TTS model listed (have {names})')

def gemini_render_one(client, model, voice, text):
    """Plain text, or a bracketed stage direction before it: "(Australian accent, warm, upbeat trainer) Sink lower" is not read
    aloud by gemini-3.8-flash-tts (a spoken prefix like "Say this in ..." is); system instructions are not supported."""
    from google.genai import types
    import io, wave
    cfg = types.GenerateContentConfig(response_modalities=['AUDIO'],
                                      speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
                                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    last = None
    for attempt in range(5):
        try:
            r = client.models.generate_content(model=model, contents=text, config=cfg)
            part = r.candidates[0].content.parts[0]; data = part.inline_data.data; mime = part.inline_data.mime_type or ''
            if data[:4] == b'RIFF':
                w = wave.open(io.BytesIO(data)); rate, ch = w.getframerate(), w.getnchannels(); x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
            else:                                   # audio/L16;codec=pcm;rate=24000
                rate = int(mime.split('rate=')[1].split(';')[0]) if 'rate=' in mime else SAMPLE_RATE; ch = 1; x = np.frombuffer(data, np.int16)
            if ch > 1:
                x = x.reshape(-1, ch).mean(1).astype(np.int16)
            if rate != SAMPLE_RATE:
                n = int(round(len(x) * SAMPLE_RATE / rate)); x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x.astype(np.float32)).astype(np.int16)
            u = r.usage_metadata
            return x.tobytes(), dict(text_tokens=u.prompt_token_count or 0, audio_tokens=u.candidates_token_count or 0, total_tokens=u.total_token_count or 0)
        except Exception as e:
            last = e; time.sleep(2.0 * (attempt + 1))
    raise last

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--model', default=None, help='Gemini Flash TTS model; the newest available Flash model is selected when omitted')
    ap.add_argument('--voice', default=None, help='Gemini prebuilt voice (default Puck)')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--dry-run', action='store_true', help='list what would be rendered, no API calls')
    ap.add_argument('--rerender-counts', action='store_true', help='drop the count words from the manifest so they are rendered again with the tighter trim')
    ap.add_argument('--style', default='', help='a bracketed stage direction prepended to every string, e.g. "(Australian accent, warm, upbeat trainer) "; not spoken, not part of the manifest key')
    ap.add_argument('--out-dir', default=None, help='bank directory (default: data/cues_audio_gemini); use a new directory for a new voice so banks never mix')
    a = ap.parse_args()
    cues_dir = a.out_dir or CUES_DIR_GEMINI
    want_model = a.model or 'gemini-3.8-flash-tts'; voice = a.voice or 'Puck'
    vocab = vocabulary(); man = load_manifest(cues_dir)
    if a.rerender_counts:
        old = {t: man[t]['duration_s'] for t in count_words() if t in man}
        for t in old: man.pop(t)
        print(f'count words before re-render: {len(old)} clips, mean {sum(old.values()) / max(len(old), 1):.3f} s, total {sum(old.values()):.2f} s')
    todo = [t for t in vocab if not (t in man and os.path.exists(os.path.join(cues_dir, man[t]['file'])))]
    chars = sum(len(t) for t in todo)
    print(f'[gemini] vocabulary {len(vocab)} strings, cached {len(vocab) - len(todo)}, to render {len(todo)} ({chars} chars) -> {cues_dir}')
    if a.dry_run or not todo:
        print(f'estimated cost for the remaining {len(todo)} clips: about ${len(todo) * 55 * GEMINI_USD["audio_out_per_m"] / 1e6:.3f} (55 audio tokens per clip)')
        if not todo:
            tot = sum(v['duration_s'] for v in man.values())
            print(f'nothing to do; {len(man)} clips, {tot:.1f} s of audio, mean clip {tot / max(len(man), 1):.2f} s; bank complete: {bank_complete(cues_dir)}')
        return
    client = gemini_client(); model = gemini_pick_model(client, want_model)
    if model != want_model: print(f'{want_model} not listed, using {model}')
    def job(text):
        pcm, usage = gemini_render_one(client, model, voice, a.style + text); db, tail = trim_params(text); return text, pcm, trim(pcm, dbfs=db, tail_s=tail), usage
    os.makedirs(cues_dir, exist_ok=True)
    t0 = time.time(); done = 0; raw_s = 0.0; out_s = 0.0; tok = dict(text_tokens=0, audio_tokens=0, total_tokens=0)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for text, pcm, cut, usage in ex.map(job, todo):
            fn = sha1(text) + '.pcm'
            open(os.path.join(cues_dir, fn), 'wb').write(cut)
            d = len(cut) / 2 / SAMPLE_RATE
            db, tail = trim_params(text)
            man[text] = dict(file=fn, duration_s=round(d, 3), chars=len(text), model=model, voice=voice, backend='gemini', trim_dbfs=db, tail_s=tail, **({'style': a.style} if a.style else {}))
            raw_s += len(pcm) / 2 / SAMPLE_RATE; out_s += d; done += 1
            if usage:
                for k in tok: tok[k] += usage[k]
            if done % 25 == 0 or done == len(todo):
                save_manifest(man, cues_dir); print(f'  {done}/{len(todo)}  {time.time() - t0:.0f} s', flush=True)
    save_manifest(man, cues_dir)
    print(f'rendered {done} clips with {model}/{voice}: {raw_s:.1f} s raw -> {out_s:.1f} s after trim; mean clip {out_s / max(done, 1):.2f} s')
    usd = tok['text_tokens'] * GEMINI_USD['text_in_per_m'] / 1e6 + tok['audio_tokens'] * GEMINI_USD['audio_out_per_m'] / 1e6
    print(f"usage totals: {tok['text_tokens']} text tokens in, {tok['audio_tokens']} audio tokens out, {tok['total_tokens']} total; "
          f"cost at the 2.5-flash-tts list price (${GEMINI_USD['text_in_per_m']}/M in, ${GEMINI_USD['audio_out_per_m']}/M audio out): ${usd:.3f}")
    tot = sum(v['duration_s'] for v in man.values())
    print(f'manifest {os.path.join(cues_dir, "manifest.json")}: {len(man)} clips, mean clip {tot / max(len(man), 1):.2f} s; bank complete: {bank_complete(cues_dir)}')

if __name__ == '__main__':
    main()
