import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { createSessionId, copyText } from './browser-compat.js';
globalThis.localStorage = {
  values: new Map(),
  getItem(key) { return this.values.get(key) ?? null; },
  setItem(key, value) { this.values.set(key, value); },
};
const base = new URL('./config.mjs', import.meta.url).href;
for (const [id, search, bootstrap, expected, host] of [
  [1, '', 'current-token', 'current-token', null],
  [2, '?join=explicit-token', 'current-token', 'explicit-token', null],
  [3, '?host=admin', undefined, null, 'admin'],
  [4, '', undefined, null, null],
]) {
  globalThis.location = {search};
  globalThis.window = {__CLASSTREAM_JOIN_TOKEN__: bootstrap};
  const config = await import(base + '?test=' + id);
  assert.equal(config.JOIN_PARAM, expected);
  assert.equal(config.HOST_PARAM, host);
  assert.match(config.SESSION_ID, /^[0-9a-f-]{36}$/);
}
console.log('PASS: browser module token bootstrap, explicit token, teacher URL, and no-class behavior.');
// Reproduce LAN HTTP: randomUUID and navigator.clipboard are absent.
Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {
  getRandomValues: array => webcrypto.getRandomValues(array),
}});
const ids = Array.from({length: 200}, () => createSessionId());
assert.equal(new Set(ids).size, ids.length);
for (const sid of ids) assert.match(sid, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
localStorage.values.clear();
globalThis.location = {search: ''};
globalThis.window = {__CLASSTREAM_JOIN_TOKEN__: 'http-class'};
const config = await import(base + '?test=http');
assert.equal(config.JOIN_PARAM, 'http-class');
assert.equal(localStorage.getItem('pystream_sid'), config.SESSION_ID);
Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {}});
let selected = false, removed = false, restored = false, copiedText = '';
globalThis.document = {
  activeElement: {focus() {restored = true;}},
  createElement() {return {style: {}, focus() {}, select() {selected = true;}, setSelectionRange() {}, remove() {removed = true;}};},
  body: {appendChild(field) {copiedText = field.value;}},
  execCommand(command) {assert.equal(command, 'copy'); assert.ok(selected); return true;},
};
await copyText('HTTP classroom code');
assert.equal(copiedText, 'HTTP classroom code');
assert.ok(removed && restored);
navigator.clipboard = {writeText: async () => {throw new Error('Permission denied');}};
await copyText('fallback after permission denial');
assert.equal(copiedText, 'fallback after permission denial');
document.execCommand = () => false;
window.prompt = (message, text) => {assert.equal(text, 'manual fallback');};
await copyText('manual fallback');
console.log('PASS: HTTP UUID v4 without randomUUID, saved session ID, clipboard absence/denial/manual fallback.');
