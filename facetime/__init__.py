"""Call glue for the real-time coach: a LiveKit participant that watches the caller's video and speaks
pre-rendered cue audio. Research code lives in src/rtcoach and is only imported from here.

Track contract (same as brodie-facetime / the Chert bridge):
- bridge participant (identity BRIDGE_IDENTITY, default "chert-bridge") publishes the caller camera as a
  video track named "facetime-remote-video" (and optionally "facetime-remote-audio").
- the coach (identity AGENT_IDENTITY, default "brodie-agent") publishes ONE audio track "coach-audio":
  24 kHz mono signed 16-bit, 20 ms frames (480 samples). Cues are cached PCM clips pushed into it.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)
DATA = os.environ.get('RTCOACH_DATA', os.path.join(ROOT, 'data'))
CUES_DIR = os.path.join(DATA, 'cues_audio')                 # legacy local cue bank (fallback only)
CUES_DIR_GEMINI = os.path.join(DATA, 'cues_audio_gemini')   # gemini voice bank (never mixed)
CUES_DIR_GEMINI_AU = os.path.join(DATA, 'cues_audio_gemini_au')   # the same Puck voice with an Australian-accent stage direction
SAMPLE_RATE = 24000
FRAME_SAMPLES = 480          # 20 ms at 24 kHz
BRIDGE_IDENTITY = os.environ.get('BRIDGE_IDENTITY', 'chert-bridge')
AGENT_IDENTITY = os.environ.get('AGENT_IDENTITY', 'brodie-agent')
VIDEO_TRACK_NAME = 'facetime-remote-video'
AUDIO_TRACK_NAME = 'coach-audio'
