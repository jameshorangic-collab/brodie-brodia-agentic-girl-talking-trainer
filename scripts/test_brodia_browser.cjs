// Real selector JavaScript with mocked DOM/LiveKit; no frontend dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const source = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];

async function test(scenario, receptivity, cameraFails = false) {
  const nodes = {
    '#start': {}, '#leave': {}, '#status': {},
    '#media': { elements: [], append(e) { this.elements.push(e); }, replaceChildren() { this.elements = []; } },
  };
  let sent, active;
  const audio = { kind: 'audio', attach: () => ({}), mediaStreamTrack: { getSettings: () => ({ sampleRate: 48000 }) } };
  class Room {
    constructor(options) {
      active = this; this.options = options; this.events = {};
      this.localParticipant = {
        setMicrophoneEnabled: async (on) => { assert.equal(this.camera, undefined, 'microphone must be enabled before the camera'); this.microphone = on; },
        setCameraEnabled: async (on) => {
          if (cameraFails) { this.camera = false; const e = new Error('Permission denied'); e.name = 'NotAllowedError'; throw e; }
          this.camera = on;
        },
        trackPublications: new Map(cameraFails ? [['audio', { track: audio }]] : [['audio', { track: audio }], ['video', { track: { kind: 'video', attach: () => ({}) } }]]),
      };
    }
    on(name, fn) { this.events[name] = fn; }
    async connect(url, token) { assert.equal(url, 'wss://example.invalid'); assert.equal(token, 'offline-token'); }
    async startAudio() { this.audioStarted = true; }
    async disconnect() { this.disconnected = true; }
  }
  const context = {
    document: { querySelector(selector) { return selector.includes('name=s') ? { value: scenario } : selector.includes('name=r') ? { value: receptivity } : nodes[selector]; } },
    console: { info() {} },
    LivekitClient: { Room, RoomEvent: { TrackSubscribed: 'track', TrackUnsubscribed: 'untrack', Disconnected: 'disconnect' } },
    fetch: async (url, options) => {
      assert.equal(url, '/api/session'); sent = JSON.parse(options.body);
      return { ok: true, json: async () => ({ url: 'wss://example.invalid', token: 'offline-token', ...sent }) };
    },
  };
  vm.runInNewContext(source, context);
  await nodes['#start'].onclick();
  assert.deepEqual(sent, { scenario, receptivity });
  const capture = active.options.audioCaptureDefaults;
  assert.equal(capture.echoCancellation, true); assert.equal(capture.noiseSuppression, true);
  assert.equal(capture.autoGainControl, true); assert.equal(capture.channelCount, 1);
  assert.equal(active.audioStarted, true); assert.equal(active.microphone, true);
  assert.equal(active.disconnected, undefined, 'call must continue');
  assert.ok(nodes['#status'].textContent.startsWith(`Connected to ${scenario} + ${receptivity}.`));
  assert.equal(nodes['#status'].textContent.includes('Camera unavailable — voice-only practice'), cameraFails);
  if (!cameraFails) assert.equal(active.camera, true);
  assert.equal(nodes['#leave'].hidden, false);
  assert.equal(nodes['#media'].elements[0].muted, true); // no local audio loopback
  if (!cameraFails) assert.equal(nodes['#media'].elements[1].className, 'self'); // local self-view: small
  active.events.track({ attach: () => ({ muted: false }) });
  assert.equal(nodes['#media'].elements.at(-1).muted, false); // Gemini remains audible
  // P17-A: the agent's video track (pose mirror) is rendered prominently (class agent: full width, first in the flex order)
  const agentEl = { muted: false, removed: false, remove() { this.removed = true; nodes['#media'].elements = nodes['#media'].elements.filter(e => e !== this); } };
  const agentVideo = { kind: 'video', attach: () => agentEl, detach: () => [agentEl] };
  active.events.track(agentVideo);
  assert.equal(nodes['#media'].elements.at(-1).className, 'agent');
  assert.equal(agentEl.title, `${{barista: 'Jess', street: 'Nadia', park: 'Maya'}[scenario]} · ${scenario}`); // character + scenario label
  assert.ok(/#media \.agent\{order:-1;flex:1 1 100%/.test(html), 'agent video styled prominently');
  active.events.untrack(agentVideo);
  assert.equal(agentEl.removed, true); // an unpublished agent track leaves no frozen element
  await nodes['#leave'].onclick();
  assert.equal(active.disconnected, true); assert.equal(nodes['#media'].elements.length, 0);
}

async function testNextCall(scenario, receptivity) {
  const nodes = { '#start': {}, '#leave': {}, '#status': {}, '#media': {}, '#nextcall': {}, '#nextstatus': {} };
  let sent;
  const context = {
    document: { querySelector(selector) { return selector.includes('name=s') ? { value: scenario } : selector.includes('name=r') ? { value: receptivity } : nodes[selector]; } },
    console: { info() {} }, LivekitClient: {},
    fetch: async (url, options) => {
      assert.equal(url, '/api/next-call'); assert.equal(options.method, 'POST'); sent = JSON.parse(options.body);
      return { ok: true, json: async () => ({ pending: true, id: 'abcd', expires_in: 120, ...sent }) };
    },
  };
  vm.runInNewContext(source, context);
  await nodes['#nextcall'].onclick();
  assert.deepEqual(sent, { scenario, receptivity });
  const text = nodes['#nextstatus'].textContent;
  for (const phrase of ['Demo-only', `${scenario} + ${receptivity}`, 'One caller at a time', 'expires in 120 s', 'Not yet proven to reach the call'])
    assert.ok(text.includes(phrase), `next-call copy missing ${phrase}: ${text}`);
  assert.equal(nodes['#nextcall'].disabled, false);
  context.fetch = async () => ({ ok: false });
  await nodes['#nextcall'].onclick();
  assert.equal(nodes['#nextstatus'].textContent, 'Could not save the next-call choice');
}

(async () => {
  assert.ok(html.includes('camera and microphone are streamed live to the AI practice partner; they are not recorded by default'), 'privacy notice missing');
  await testNextCall('park', 'neutral');
  await testNextCall('street', 'uninterested');
  console.log('next FaceTime call (demo-only) button: POST /api/next-call and honest copy: PASS');
  for (const scenario of ['barista', 'street', 'park']) {
    for (const stance of ['interested', 'neutral', 'uninterested']) await test(scenario, stance);
  }
  await test('park', 'neutral', true);
  console.log('camera denied: call continues voice-only with honest status: PASS');
  console.log('9/9 browser selections, audio preferences, local mute, remote playback, agent video (prominent) and self-view (small), and disconnect: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
