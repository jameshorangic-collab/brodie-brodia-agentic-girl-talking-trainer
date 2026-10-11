"""Cue player for the coach's single LiveKit audio track.

Track contract: rtc.AudioSource(24000, 1) behind rtc.LocalAudioTrack "coach-audio"; 24 kHz mono s16le,
pushed as 20 ms frames (480 samples). Cues are cached PCM clips (facetime/cues_tts.py manifest), looked up
by exact text; a missing clip is a warning, never an exception on the live path.

Queue policy (one pending slot plus one deferred slot, so speech never lags the movement and a count is never stuck):
- priorities count 0 < positive/start 1 < correction 2 < announce/milestone/visibility 3.
- a count that arrives while a correction or praise is pending goes AHEAD of it: the count takes the pending slot and the
  displaced cue moves to the deferred slot and plays right after the count (the count on the rep, the cue on the next
  descent). A count behind a pending count or a priority-3 cue is dropped (stale). A count arriving while a clip plays
  takes the empty pending slot and is spoken right after the clip.
- a correction arriving while a count is pending is deferred behind it; it replaces a pending positive or an older
  pending correction; it is dropped behind a priority-3 cue. Positives are queued only when nothing is pending.
- priority 3 replaces whatever is pending or deferred (both displaced cues are dropped).
- say_now() is the latency probe: it cuts whatever is playing (source.clear_queue), plays immediately, and the cut cue is
  logged with status "cut".
Consecutive cues are separated by gap_ms (default 100 ms). The AudioSource queue is queue_ms (default 60 ms, so a cue is
on the wire 60 ms after the push; the player counts underruns = pushes that found the queue empty, see the status line).

Optional mixer input (attach_mixer(), off by default; the default path is byte-identical without it): a MixInput that a
conversational layer writes 24 kHz mono PCM into (facetime/voice.py pushes the Gemini Live stream there). The player's pump
task pushes that stream into the SAME AudioSource whenever no clip is playing, keeping at most pump_lead_s queued so a count
still reaches the wire within that lead; while a clip plays, the clip is pushed on its own schedule with the stream mixed
under it at duck_db (about -10 dB, 20 ms ramps), and the duck holds hold_ms after the clip. The stream never blocks the slots.
"""
import asyncio, collections, json, logging, os, time
import numpy as np
from facetime import CUES_DIR, CUES_DIR_GEMINI, CUES_DIR_GEMINI_AU, SAMPLE_RATE, FRAME_SAMPLES, AUDIO_TRACK_NAME

log = logging.getLogger('audio_out')
PRIORITY = {'count': 0, 'positive': 1, 'start': 1, 'other': 1, 'correction': 2, 'announce': 3, 'milestone': 3, 'visibility': 3}
BEEP = '[beep]'                      # 80 ms 1 kHz tone, synthesised into the bank (latency probe)

def bank_coverage(cues_dir):
    """(covered, total) vocabulary strings with a clip on disk in that bank."""
    from facetime.cues_tts import vocabulary
    mf = os.path.join(cues_dir, 'manifest.json')
    m = json.load(open(mf)) if os.path.exists(mf) else {}
    v = vocabulary()
    return sum(1 for t in v if t in m and os.path.exists(os.path.join(cues_dir, m[t]['file']))), len(v)

def default_cues_dir():
    """env CUE_AUDIO_DIR (when it exists and covers at least one string; a missing or empty directory is reported and the
    ranked banks are used instead, so a wrong mount never makes the coach mute), else the bank that covers the most of the
    current vocabulary: Puck first (the plain Puck bank is the default voice), then the
    Australian Puck bank, then the legacy local bank. The vocabulary grows with cues.json, so a bank is never required to be
    complete; missing strings are reported at load."""
    d = os.environ.get('CUE_AUDIO_DIR')
    if d:
        try: c = bank_coverage(d)[0] if os.path.isdir(d) else 0
        except Exception: c = 0
        if c > 0: return d
        log.error('CUE_AUDIO_DIR %s is missing or covers no string; falling back to the ranked banks', d)
        print(f'[cues] WARNING: CUE_AUDIO_DIR {d} is missing or covers no string; using the best bank found instead', flush=True)
    try:
        banks = (CUES_DIR_GEMINI, CUES_DIR_GEMINI_AU, CUES_DIR)          # preference order among equally complete banks
        cov = [(bank_coverage(x), x) for x in banks if os.path.isdir(x)]
        (c, n), best = max(cov, key=lambda t: (t[0][0], -banks.index(t[1])))
        for (ci, ni), x in cov:
            if ci < ni: log.warning('cue bank %s covers %d/%d strings; run facetime.cues_tts with GEMINI_API_KEY set', x, ci, ni)
        return best
    except Exception as e:
        log.warning('bank check failed: %s', e)
    return CUES_DIR

def ensure_beep(cues_dir, ms=80, hz=1000.0, amp=0.5):
    """Write beep_1khz_80ms.pcm (24 kHz s16, 5 ms fades) into the bank and register it as "[beep]" (idempotent)."""
    mf = os.path.join(cues_dir, 'manifest.json')
    try:
        m = json.load(open(mf)) if os.path.exists(mf) else {}
        fn = f'beep_{int(hz)}hz_{ms}ms.pcm'; path = os.path.join(cues_dir, fn)
        if BEEP in m and os.path.exists(os.path.join(cues_dir, m[BEEP]['file'])): return
        n = int(SAMPLE_RATE * ms / 1000); t = np.arange(n) / SAMPLE_RATE
        x = np.sin(2 * np.pi * hz * t); f = int(0.005 * SAMPLE_RATE); ramp = np.linspace(0, 1, f)
        x[:f] *= ramp; x[-f:] *= ramp[::-1]
        os.makedirs(cues_dir, exist_ok=True); open(path, 'wb').write((x * amp * 32767).astype(np.int16).tobytes())
        m[BEEP] = dict(file=fn, duration_s=ms / 1000, chars=0, model='synth', voice='sine', backend='synth')
        json.dump(m, open(mf + '.tmp', 'w'), indent=1, sort_keys=True); os.replace(mf + '.tmp', mf)
    except Exception as e:
        log.warning('ensure_beep failed: %s', e)

TARGET_RMS_DBFS = -18.0        # the bank's median; TTS clips vary from -26 to -14 dBFS, which is a lot on a phone speaker
PEAK_CEIL_DBFS = -1.0

def normalize_level(pcm, target_dbfs=TARGET_RMS_DBFS, ceil_dbfs=PEAK_CEIL_DBFS):
    """Bring a clip's RMS to the bank's target level, never past the peak ceiling."""
    if len(pcm) < 240:
        return pcm
    x = pcm.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(x * x))); peak = float(np.abs(x).max())
    if rms <= 1e-6 or peak <= 1e-6:
        return pcm
    gain = min(10 ** ((target_dbfs - 20 * np.log10(rms)) / 20), 10 ** ((ceil_dbfs - 20 * np.log10(peak)) / 20))
    if abs(gain - 1.0) < 0.05:
        return pcm
    return np.clip(x * gain * 32768.0, -32768, 32767).astype(np.int16)

class CueBank:
    """text -> int16 PCM (24 kHz mono), loaded lazily from the manifest of one voice bank."""
    @classmethod
    def disabled(cls):
        """Empty bank keeps the single streaming mixer track without prerecorded speech."""
        bank = cls.__new__(cls)
        bank.dir, bank.manifest, bank.cache = 'disabled (Brodia)', {}, {}
        return bank

    def __init__(self, cues_dir=None):
        self.dir = cues_dir or default_cues_dir()
        log.info('cue bank %s', self.dir); ensure_beep(self.dir)
        mf = os.path.join(self.dir, 'manifest.json')
        self.manifest = json.load(open(mf)) if os.path.exists(mf) else {}
        self.cache = {}
        if not self.manifest:
            log.warning('no cue manifest at %s; run facetime/cues_tts.py', mf)
        else:
            try:
                c, n = bank_coverage(self.dir)
                print(f'[cues] bank {self.dir}: {len(self.manifest)} clips, covers {c}/{n} of the vocabulary' + ('' if c == n else ' (missing strings are skipped with a warning)'), flush=True)
            except Exception:
                print(f'[cues] bank {self.dir}: {len(self.manifest)} clips', flush=True)
    def get(self, text):
        if text in self.cache:
            return self.cache[text]
        m = self.manifest.get(text)
        if m is None:
            return None
        p = os.path.join(self.dir, m['file'])
        if not os.path.exists(p):
            return None
        pcm = np.frombuffer(open(p, 'rb').read(), np.int16)
        if not (text.startswith('[beep]') or m['file'].startswith('beep')):
            pcm = normalize_level(pcm)                          # speech only; the probe beep keeps its level
        pad = (-len(pcm)) % FRAME_SAMPLES                  # whole 20 ms frames
        if pad:
            pcm = np.concatenate([pcm, np.zeros(pad, np.int16)])
        self.cache[text] = pcm
        return pcm
    def duration(self, text):
        m = self.manifest.get(text); return m['duration_s'] if m else None

class MixInput:
    """A second audio stream (24 kHz mono int16) mixed under the cues by CuePlayer's pump. write() from the event loop; the
    player reads 20 ms at a time. n_written / n_read count samples (a sink uses them for playback positions); clear() drops
    what has not been read (an interrupted reply)."""
    def __init__(self, duck_db=-10.0, hold_ms=150, gain_db=0.0, hold=True):
        self.duck = 10 ** (duck_db / 20); self.hold_s = hold_ms / 1000.0; self.level = 10 ** (gain_db / 20)
        self.hold = hold   # True (2026-10-10 live call: 'two voices talking over each other'): the stream WAITS while a clip plays or is pending and resumes after it, instead of playing ducked under it
        self.chunks = collections.deque(); self.pending = 0; self.n_written = 0; self.n_read = 0; self.n_cleared = 0
        self.gain = 1.0; self.duck_until = 0.0; self.wake = asyncio.Event()
    def write(self, pcm):
        pcm = np.asarray(pcm, np.int16)
        if len(pcm) == 0: return
        self.chunks.append(pcm); self.pending += len(pcm); self.n_written += len(pcm); self.wake.set()
    @property
    def active(self):
        return self.pending > 0
    def read(self, n):
        """The next n samples (zero-padded at the tail of the stream); None when nothing is buffered."""
        if self.pending <= 0: return None
        out = np.zeros(n, np.int16); i = 0
        while i < n and self.chunks:
            c = self.chunks[0]; k = min(n - i, len(c)); out[i:i + k] = c[:k]; i += k
            if k == len(c): self.chunks.popleft()
            else: self.chunks[0] = c[k:]
        self.pending -= i; self.n_read += i
        return out
    def clear(self):
        self.n_cleared += self.pending; self.chunks.clear(); self.pending = 0
    def ramp(self, target, n):
        """Per-sample gain from the current gain to target over n samples (no clicks on a duck step); remembers target."""
        g = np.linspace(self.gain, target, n, dtype=np.float32) if self.gain != target else np.full(n, target, np.float32)
        self.gain = target; return g * self.level


class CuePlayer:
    def __init__(self, bank=None, source=None, on_record=None, queue_ms=60, gap_ms=100):
        """source: an object with `async capture_frame(frame)` and `async wait_for_playout()`;
        default rtc.AudioSource(24000, 1, queue_size_ms=queue_ms) so pushes pace to real time with ~200 ms lead.
        on_record(rec) is called when a cue is finished or dropped."""
        self.bank = bank or CueBank()
        if source is None:
            from livekit import rtc
            self.rtc = rtc
            source = rtc.AudioSource(SAMPLE_RATE, 1, queue_size_ms=queue_ms)
            self.track = rtc.LocalAudioTrack.create_audio_track(AUDIO_TRACK_NAME, source)
        else:
            self.rtc = None; self.track = None
        self.source = source
        self.on_record = on_record; self.gap_s = gap_ms / 1000.0
        self.pending = None          # one slot
        self.deferred = None         # the cue a count jumped ahead of; plays right after the count
        self.urgent = None; self._cut = False
        self.playing = None; self.underruns = 0
        self.records = []
        self._wake = asyncio.Event()
        self._stop = False
        self.n_dropped = 0
        self.mix = None; self._pump_task = None; self.pump_lead_s = 0.04; self.mix_frames = 0   # attach_mixer()
        self.last_voice_t = -1e9     # monotonic time of the last frame with real energy pushed to the source (clip or model voice)

    def speaking(self, window_s=0.15):
        """Cheap: True when an audible frame (a clip or the mixed model voice) was pushed within window_s. The source queue is
        only ~100 ms deep, so this tracks what the caller hears to within about that."""
        return time.monotonic() - self.last_voice_t <= window_s

    def attach_mixer(self, duck_db=-10.0, hold_ms=150, gain_db=0.0, lead_ms=40, hold=True):
        """Add the optional mixer input (see the module docstring); returns the MixInput. The pump starts with run()."""
        self.mix = MixInput(duck_db=duck_db, hold_ms=hold_ms, gain_db=gain_db, hold=hold); self.pump_lead_s = lead_ms / 1000.0
        try:
            loop = asyncio.get_running_loop()
            if self._pump_task is None and not self._stop: self._pump_task = loop.create_task(self._pump())
        except RuntimeError:
            pass                                                      # no loop yet: run() starts the pump
        return self.mix

    def _under(self, chunk):
        """A clip frame with the mixer stream ducked under it (identity when no mixer is attached)."""
        if self.mix is None: return chunk
        if self.mix.hold: self.mix.gain = self.mix.duck; return chunk          # hold: the voice waits for the clip to end (nothing mixed under it)
        m = self.mix.read(len(chunk))
        if m is None:
            self.mix.gain = self.mix.duck; return chunk
        g = self.mix.ramp(self.mix.duck, len(chunk)); self.mix_frames += 1
        return np.clip(chunk.astype(np.float32) + m.astype(np.float32) * g, -32768, 32767).astype(np.int16)

    def _ducked(self):
        return self.playing is not None or self.pending is not None or self.urgent is not None or time.monotonic() < self.mix.duck_until

    async def _pump(self):
        """Mixer stream -> the source whenever no clip is playing, at most pump_lead_s queued ahead (a count waits at most that)."""
        mix = self.mix
        while not self._stop and self.mix is mix:
            if not mix.active:
                mix.wake.clear(); await mix.wake.wait(); continue
            if self.playing is not None or getattr(self.source, 'queued_duration', 0) >= self.pump_lead_s or (mix.hold and self._ducked()):
                await asyncio.sleep(0.005); continue                          # hold: also while a clip is pending or in the hold_ms after one
            m = mix.read(FRAME_SAMPLES); g = mix.ramp(mix.duck if self._ducked() else 1.0, FRAME_SAMPLES); self.mix_frames += 1
            try:
                await self.source.capture_frame(self._frame(np.clip(m.astype(np.float32) * g, -32768, 32767).astype(np.int16)))
            except Exception as e:
                log.warning('mixer push failed: %s', e); await asyncio.sleep(0.02)

    def say(self, text, intent='other', meta=None):
        """Thread-unsafe: call from the event loop (use loop.call_soon_threadsafe from workers).
        Returns the record (status 'queued'|'deferred'|'replaced'|'dropped'|'missing')."""
        rec = dict(text=text, intent=intent, t_say=time.time(), t_push=None, t_done=None, status=None, **(meta or {}))
        pcm = self.bank.get(text)
        if pcm is None:
            rec['status'] = 'missing'; log.warning('no cue audio for %r', text); self._finish(rec); return rec
        rec['duration_s'] = len(pcm) / SAMPLE_RATE
        pr = PRIORITY.get(intent, 1)
        if self.pending is None:
            rec['status'] = 'queued'; self.pending = (rec, pcm); self._wake.set(); return rec
        old, old_pcm = self.pending; pr_old = PRIORITY.get(old['intent'], 1)
        if pr >= 3 or (pr == 2 and pr_old in (1, 2)):
            old['status'] = 'dropped'; old['why_dropped'] = f'replaced by {intent}'; self.n_dropped += 1; self._finish(old)
            if pr >= 3 and self.deferred is not None:                 # a milestone or announce closes the set: the deferred cue goes too
                d = self.deferred[0]; d['status'] = 'dropped'; d['why_dropped'] = f'replaced by {intent}'; self.n_dropped += 1; self._finish(d); self.deferred = None
            rec['status'] = 'replaced'; self.pending = (rec, pcm); self._wake.set(); return rec
        if pr == 0 and pr_old in (1, 2):                      # count jumps ahead; the cue plays right after it
            if self.deferred is not None:
                d = self.deferred[0]; d['status'] = 'dropped'; d['why_dropped'] = 'deferred slot taken'; self.n_dropped += 1; self._finish(d)
            old['status'] = 'deferred'; self.deferred = (old, old_pcm)
            rec['status'] = 'queued'; self.pending = (rec, pcm); self._wake.set(); return rec
        if pr == 2 and pr_old == 0:                            # correction waits behind the pending count
            if self.deferred is not None:
                d = self.deferred[0]; d['status'] = 'dropped'; d['why_dropped'] = 'replaced by a newer correction'; self.n_dropped += 1; self._finish(d)
            rec['status'] = 'deferred'; self.deferred = (rec, pcm); return rec
        rec['status'] = 'dropped'; rec['why_dropped'] = f"{old['intent']} already pending"; self.n_dropped += 1; self._finish(rec); return rec

    def say_now(self, text, intent='probe', meta=None):
        """Latency probe: cut whatever is playing and play `text` immediately (bypasses both slots)."""
        rec = dict(text=text, intent=intent, t_say=time.time(), t_push=None, t_done=None, status='urgent', **(meta or {}))
        pcm = self.bank.get(text)
        if pcm is None:
            rec['status'] = 'missing'; log.warning('no cue audio for %r', text); self._finish(rec); return rec
        rec['duration_s'] = len(pcm) / SAMPLE_RATE
        self.urgent = (rec, pcm); self._cut = True; self._wake.set(); return rec

    def _finish(self, rec):
        self.records.append(rec)
        if self.on_record:
            try: self.on_record(rec)
            except Exception as e: log.warning('on_record failed: %s', e)

    SPEAK_PEAK = 400            # int16 peak above which a pushed frame counts as audible speech (about -38 dBFS)

    def _frame(self, chunk):
        if len(chunk) and int(np.abs(chunk).max()) > self.SPEAK_PEAK: self.last_voice_t = time.monotonic()   # speaking() for the avatar's mouth
        if self.rtc is not None:
            return self.rtc.AudioFrame(chunk.tobytes(), SAMPLE_RATE, 1, len(chunk))
        return chunk

    async def _play(self, rec, pcm, interruptible=True):
        """Push one clip as 20 ms frames (the source paces to real time); returns False when cut by say_now()."""
        rec['t_push'] = time.time(); self.playing = rec
        try:
            for i in range(0, len(pcm), FRAME_SAMPLES):
                if interruptible and self._cut:
                    if hasattr(self.source, 'clear_queue'):
                        try: self.source.clear_queue()
                        except Exception as e: log.warning('clear_queue: %s', e)
                    rec['t_done'] = time.time(); rec['status'] = 'cut'; rec['cut_at_s'] = round(i / SAMPLE_RATE, 2)
                    self.playing = None; self._finish(rec); return False
                if i and getattr(self.source, 'queued_duration', None) == 0: self.underruns += 1
                await self.source.capture_frame(self._frame(self._under(pcm[i:i + FRAME_SAMPLES])))
            await self._wait_playout(interruptible)
            rec['t_done'] = time.time(); rec['status'] = 'played'
        except Exception as e:
            rec['status'] = 'error'; rec['error'] = repr(e); log.warning('push failed for %r: %s', rec['text'], e)
        self.playing = None; self._finish(rec); return True

    async def _wait_playout(self, interruptible):
        """Drain the source queue (at most queue_ms); an urgent clip (say_now) breaks the wait and clears the queue."""
        if self.mix is not None:                                      # the pump keeps the queue fed: wait out the clip's own lead only
            self.mix.duck_until = time.monotonic() + self.mix.hold_s
            end = time.monotonic() + min(float(getattr(self.source, 'queued_duration', 0) or 0), 0.2)
            while time.monotonic() < end and not (interruptible and self._cut): await asyncio.sleep(0.005)
            if interruptible and self._cut:
                try: self.source.clear_queue()
                except Exception as e: log.warning('clear_queue: %s', e)
            self.mix.duck_until = time.monotonic() + self.mix.hold_s
            return
        if not interruptible or not hasattr(self.source, 'queued_duration'):
            await self.source.wait_for_playout(); return
        while getattr(self.source, 'queued_duration', 0) > 0:
            if self._cut:
                try: self.source.clear_queue()
                except Exception as e: log.warning('clear_queue: %s', e)
                return
            await asyncio.sleep(0.005)

    async def _gap(self):
        """A breath between cues, cut short by an urgent clip."""
        end = time.monotonic() + self.gap_s
        while time.monotonic() < end and self.urgent is None:
            await asyncio.sleep(0.01)

    async def run(self):
        """Urgent clip first (cuts the current one), then the pending slot, then the deferred cue right behind it."""
        if self.mix is not None and self._pump_task is None: self._pump_task = asyncio.create_task(self._pump())
        while not self._stop:
            if self.urgent is not None:
                rec, pcm = self.urgent; self.urgent = None; self._cut = False
                await self._play(rec, pcm, interruptible=False); continue
            if self.pending is None:
                self._wake.clear(); await self._wake.wait(); continue
            rec, pcm = self.pending; self.pending = None
            if self.deferred is not None and self.pending is None:
                self.pending = self.deferred; self.deferred = None          # plays right after this cue
            done = await self._play(rec, pcm)
            if done: await self._gap()                                        # a breath between cues (an urgent clip cuts it short)

    def stop(self):
        self._stop = True; self._wake.set()
        if self.mix is not None: self.mix.wake.set()
