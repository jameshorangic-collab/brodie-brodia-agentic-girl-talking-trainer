"""The post-call game review for a browser call: a JSON snapshot on the LiveKit data channel (topic "brodia.report").

The worker sends it only to the browser caller (identity "brodia-browser", minted by facetime/brodia_server.py and
landing/api/session.js), never to a Chert FaceTime bridge. It goes out while the call runs, whenever it changed, at most every
INTERVAL_S, and once more as the job closes, so the page has the latest one even when the caller hangs up first. It contains
the caller's own scored lines, so it is sent only to that caller, and the worker writes it nowhere. landing/src/Review.jsx renders it.

Shape (v 1):
  scenario, receptivity
  score {start, now, band}               rapport 0..100 (simulation tuning, not anyone's feelings); band 0..4
  turns [{t, quote, delta, score, type, reason}]   t = s from the first transcript; delta = applied change; type positive|neutral|negative|uncertain
  outcomes [{request, accepted}]         contact | date | meet_again | continue
  boundaries [..]
  finished                               the caller said an exit phrase (Coach Brodie's feedback follows)
  coach                                  Coach Brodie's spoken feedback so far, or null
  visual [..]                            verified camera observations only (facetime/brodia.FeedbackSession.visual_observations)
"""
import asyncio, json, logging

log = logging.getLogger('brodia_report')
TOPIC = 'brodia.report'
BROWSER_IDENTITY = 'brodia-browser'
INTERVAL_S = 2.0
MAX_BYTES = 14000       # one reliable data packet, with room to spare


def build(controller, feedback):
    """The review dict for this moment; never raises."""
    r = controller.report() if controller is not None else {'turns': [], 'outcomes': [], 'boundaries': []}
    r['v'] = 1
    r['finished'] = bool(feedback is not None and feedback.finished)
    try:
        r['coach'] = feedback.coach_feedback() if feedback is not None else None
        r['visual'] = feedback.visual_observations() if feedback is not None else []
    except Exception as e:                                                    # a malformed vision summary never blocks the review
        log.warning('report: feedback fields skipped (%s)', type(e).__name__); r.setdefault('coach', None); r['visual'] = []
    return r


def encode(report):
    """Compact JSON within MAX_BYTES: the oldest turns go first, then the coach text is cut."""
    while True:
        data = json.dumps(report, separators=(',', ':')).encode()
        if len(data) <= MAX_BYTES: return data
        if len(report['turns']) > 1: report['turns'] = report['turns'][1:]
        elif report.get('coach'): report['coach'] = report['coach'][:len(report['coach']) // 2]
        else: return data[:0]


async def send(job, force=False):
    """Publish the current review to the browser caller if it changed (or force). Returns True when sent."""
    if job.bound != BROWSER_IDENTITY or not job.room_connected(): return False
    data = encode(build(getattr(job, 'brodia_controller', None), getattr(job, 'brodia_feedback', None)))
    if not data or (data == job.report_sent and not force): return False
    try:
        await job.room.local_participant.publish_data(data, reliable=True, topic=TOPIC, destination_identities=[BROWSER_IDENTITY])
    except Exception as e:
        log.warning('report publish failed (%s)', type(e).__name__); return False
    job.report_sent = data
    return True


async def run_for_job(job, interval=INTERVAL_S):
    """One task per Brodia job (facetime/worker.py starts it): idles until a browser caller is bound."""
    while True:
        await asyncio.sleep(interval)
        await send(job)
