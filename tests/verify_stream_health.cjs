/* Connection health/retry checks with a virtual clock; no classroom or ports. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture() {
  let now = 0, nextTimer = 0;
  const timers = new Map();
  const schedule = (fn, delay, repeat = false) => {
    const id = ++nextTimer; timers.set(id, { fn, due: now + delay, delay, repeat }); return id;
  };
  const classes = () => ({ toggle() {}, add() {}, remove() {} });
  const element = () => ({ dataset: {}, style: {}, classList: classes(), textContent: '',
    isConnected: true, width: 0, height: 0, setAttribute() {}, appendChild() {},
    querySelector() { return null; }, getContext() { return { drawImage() {} }; } });
  const nodes = Object.fromEntries(['conn-state', 'stream-overlay', 'overlay-msg'].map(id => [id, element()]));
  const listeners = new Map();
  const document = { hidden: false, createElement: element, getElementById: id => nodes[id],
    addEventListener(name, fn) { listeners.set(name, fn); },
    removeEventListener(name, fn) { if (listeners.get(name) === fn) listeners.delete(name); } };
  const window = { addEventListener() {}, removeEventListener() {} };
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 0; this.listeners = {}; this.sent = []; }
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
    open() { this.readyState = 1; this.onopen?.(); }
    close() {
      if (this.readyState === 3) return;
      this.readyState = 3;
      for (const fn of this.listeners.close || []) fn();
      this.onclose?.();
    }
    send(value) { this.sent.push(value); }
    meta(fields = {}) { this.onmessage({ data: JSON.stringify({ type: 'meta', capture_age_ms: 0,
      stream_epoch: 1, stream_seq: 1, frozen: false, ...fields }) }); }
  }
  const state = { currentMode: 'single', wsMap: {}, paused: false, myRole: 'guest' };
  const context = vm.createContext({ __testState: state, document, window, WebSocket: Socket,
    Blob, TextDecoder, Uint8Array, DataView, Event, performance: { now: () => now },
    Math: Object.assign(Object.create(Math), { random: () => .5 }),
    setInterval: (fn, ms) => schedule(fn, ms, true), setTimeout: schedule,
    clearInterval: id => timers.delete(id), clearTimeout: id => timers.delete(id) });
  const source = fs.readFileSync(path.join(__dirname, '../windows-lan/stream-client.js'), 'utf8')
    .replace("import { state } from './state.js';", 'const state = globalThis.__testState;')
    .replaceAll('export function ', 'function ');
  vm.runInContext(source + '\nglobalThis.api = { connectScreen, closeScreen };', context);
  const canvas = element();
  let retries = 0;
  const handlers = { register() {}, message() {}, frame() {}, private() {}, reconnect() { retries++; } };
  function connect(key = 'single', extra = {}) { return context.api.connectScreen('ws://test', key, canvas, { ...handlers, ...extra }); }
  function advance(ms) {
    const end = now + ms;
    while (true) {
      const ready = [...timers].filter(([, t]) => t.due <= end).sort((a, b) => a[1].due - b[1].due)[0];
      if (!ready) break;
      const [id, timer] = ready; now = timer.due;
      if (timer.repeat) timer.due += timer.delay; else timers.delete(id);
      timer.fn();
    }
    now = end;
  }
  return { state, document, nodes, timers, canvas, handlers, connect, advance, context,
    phase: () => nodes['conn-state'].dataset.phase, retries: () => retries,
    visibility: () => listeners.get('visibilitychange')?.() };
}

{
  const f = fixture(), ws = f.connect(); ws.open();
  ws.meta(); assert.equal(f.phase(), 'waiting', 'open/meta cannot prove first picture');
  ws._frameApplied(1, 1, true); assert.equal(f.phase(), 'live');
  for (let i = 0; i < 12; i++) { f.advance(1000); ws.meta(); }
  assert.equal(f.phase(), 'live', 'static image with fresh meta remains healthy');
  assert.equal(f.retries(), 0);
  f.advance(3000); assert.equal(f.phase(), 'interrupted');
  f.advance(2000); assert.equal(f.phase(), 'reconnecting');
  assert.equal(ws.readyState, 3, 'black hole invalidates old socket');
  f.advance(1000); assert.equal(f.retries(), 1);
}
{
  const f = fixture(), ws = f.connect(); ws.open(); ws._frameApplied(1, 1, true);
  for (let i = 0; i < 12; i++) { ws.meta({ capture_age_ms: 5000 }); f.advance(1000); }
  assert.equal(f.phase(), 'source'); assert.equal(f.retries(), 0, 'capture failure must not cause reconnect loop');
  ws.meta(); assert.equal(f.phase(), 'live');
  for (let i = 0; i < 8; i++) { ws.meta({ stream_seq: 99, frozen: true }); f.advance(1000); }
  assert.equal(f.phase(), 'frozen'); assert.equal(f.retries(), 0);
  f.state.paused = true;
  for (let i = 0; i < 8; i++) { ws.meta({ stream_seq: 199 }); f.advance(1000); }
  assert.equal(f.phase(), 'paused'); assert.equal(f.retries(), 0);
}
{
  const f = fixture(), ws = f.connect(); ws.open(); ws._frameApplied(1, 1, true);
  for (let i = 0; i < 3; i++) { ws.meta({ stream_seq: 10 }); f.advance(1000); }
  assert.equal(f.phase(), 'lagging');
  for (let i = 0; i < 2; i++) { ws.meta({ stream_seq: 10 }); f.advance(1000); }
  assert.equal(f.phase(), 'reconnecting', 'fresh heartbeat cannot mask stalled application');
}
{
  const f = fixture(), ws = f.connect(); ws.open(); ws.close();
  const replacement = f.connect(); replacement.open();
  f.advance(1000); assert.equal(f.retries(), 0, 'old retry cannot replace a new screen connection');
  f.context.api.closeScreen(replacement);
  assert.equal(f.timers.size, 0, 'intentional close cleans watchdog and retry');
}
{
  const f = fixture(), ws = f.connect(); ws.open(); ws.close();
  f.state.currentMode = 'grid'; f.advance(1000);
  assert.equal(f.retries(), 0, 'single retry cannot reopen after switching to grid');
}
{
  const f = fixture(), ws = f.connect(); ws.open();
  ws.onmessage({ data: JSON.stringify({ type: 'error', reason: 'refresh_required' }) });
  assert.equal(f.phase(), 'ended');
  assert.match(f.nodes['conn-state'].textContent, /版本已更新/);
  f.advance(20000); assert.equal(f.retries(), 0); assert.equal(f.timers.size, 0);
}
{
  const f = fixture(); f.state.currentMode = 'grid';
  const first = f.connect('grid-1', { cell: f.canvas }); first.open(); first._frameApplied(1, 1, true);
  const second = f.connect('grid-2', { cell: f.canvas }); second.open(); second._frameApplied(1, 1, true);
  for (let i = 0; i < 3; i++) { first.meta(); f.advance(1000); }
  assert.equal(f.phase(), 'interrupted', 'one healthy grid cell cannot hide another failed cell');
}
{
  const f = fixture(), first = f.connect(); first.open(); first.close();
  f.advance(1000); assert.equal(f.retries(), 1);
  const second = f.connect(); second.open(); second.close();
  f.advance(1000); assert.equal(f.retries(), 1, 'repeated failures must back off');
  f.advance(1000); assert.equal(f.retries(), 2);
}
{
  const f = fixture(), ws = f.connect(); ws.open(); ws._frameApplied(1, 1, true); ws.meta();
  f.document.hidden = true; f.advance(20000);
  f.document.hidden = false;
  f.visibility(); f.advance(1000);
  assert.equal(f.phase(), 'live', 'foreground return grants a new heartbeat interval');
  ws.meta(); assert.equal(f.retries(), 0);
}
console.log('PASS: first picture; static heartbeat; 3s/5s recovery; source failure; frozen/paused; lag; retry cancellation; protocol error; grid faults.');
