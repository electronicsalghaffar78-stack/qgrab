/* DOM-stub tests for the Script+Prompt usage line client
   (templates/_spjs.html) after ROUND 3 (2026-11-16): the
   daily counters were removed by the owner's order — the two
   quota lines now state the tool is free & unlimited (no
   quota fetch at all), a generation still runs end-to-end,
   and a 429 rate_limited POST (the burst throttle, the only
   throttle left) shows its friendly "please wait" message.
   Run:  node tests/test_sp_quota_js.js */
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'templates', '_spjs.html'), 'utf8');
const code = html.match(/<script>([\s\S]*)<\/script>/)[1];

/* ---------- fake clock + timers (same harness as jobs) ------- */
let now = 0;
let timers = new Map();
let timerSeq = 0;
function fakeSetTimeout(cb, ms) {
  const id = ++timerSeq;
  timers.set(id, { at: now + (ms || 0), cb, interval: 0 });
  return id;
}
function fakeSetInterval(cb, ms) {
  const id = ++timerSeq;
  timers.set(id, { at: now + (ms || 0), cb, interval: ms || 0 });
  return id;
}
function fakeClear(id) { timers.delete(id); }
const realImmediate = setImmediate;
async function flush() {
  for (let i = 0; i < 25; i++) {
    await new Promise((r) => realImmediate(r));
  }
}

/* ---------- DOM stubs ---------- */
function makeEl(id) {
  const el = {
    id, children: [], listeners: {}, style: {}, disabled: false,
    textContent: '', value: '', className: '',
    addEventListener(ev, fn) {
      (this.listeners[ev] = this.listeners[ev] || []).push(fn);
    },
    click() {
      (this.listeners.click || []).forEach(
        (f) => f({ preventDefault() {} }));
    },
    append(...kids) { this.children.push(...kids); },
    appendChild(k) { this.children.push(k); return k; },
    querySelectorAll() { return []; },
    scrollIntoView() {}, focus() {}, select() {}, remove() {},
  };
  return el;
}

function buildEnv({ fetchHandler }) {
  now = 0;
  timers = new Map();
  timerSeq = 0;
  const registry = {};
  const store = new Map();
  const sessionStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  const document = {
    getElementById(id) {
      if (!registry[id]) registry[id] = makeEl(id);
      return registry[id];
    },
    createElement() { return makeEl('anon'); },
    body: makeEl('body'),
  };
  registry.spBtnScript = makeEl('spBtnScript');
  registry.spBtnScript.textContent = 'Create Script';
  registry.spBtnPrompts = makeEl('spBtnPrompts');
  registry.spBtnPrompts.textContent = 'Create Prompts';
  registry.spRegenPrompts = makeEl('spRegenPrompts');
  registry.spRegenPrompts.textContent = 'Regenerate';
  globalThis.document = document;
  globalThis.window = globalThis;
  globalThis.sessionStorage = sessionStorage;
  globalThis.fetch = fetchHandler;
  globalThis.I18N = {
    sp_working: 'Please wait', err_link: 'BAD LINK',
    err_generic: 'GENERIC', sp_err_nosubs: 'NO SUBS',
    sp_err_toolong: 'TOO LONG', sp_err_audiobig: 'AUDIO BIG',
    sp_err_nospeech: 'NO SPEECH', sp_err_rate: 'RATE',
    sp_err_ai: 'AI UNAVAILABLE', sp_err_setup: 'SETUP',
    sp_copied: 'Copied',
  };
  globalThis.setTimeout = fakeSetTimeout;
  globalThis.setInterval = fakeSetInterval;
  globalThis.clearTimeout = fakeClear;
  globalThis.clearInterval = fakeClear;
  Date.now = () => now;
  (0, eval)(code);
  return { registry, store };
}

function jsonRes(status, body) {
  return { status, ok: status >= 200 && status < 300,
           json: async () => body };
}

const UNLIMITED_S = 'Scripts: free & unlimited — no daily limit';
const UNLIMITED_P = 'Prompts: free & unlimited — no daily limit';

/* ---------- scenario 1: unlimited lines + generation --------- */
async function scenarioUnlimited() {
  let quotaFetched = false;
  const env = buildEnv({
    fetchHandler: async (url) => {
      if (url === '/api/script-prompt/quota') {
        quotaFetched = true;
        return jsonRes(200, { script_used: 3, prompts_used: 1,
                              unlimited: true, resets_at: 0 });
      }
      if (url === '/api/info') return jsonRes(200, {});
      if (url === '/api/script-prompt') {
        return jsonRes(202, { job_id: 'qjob1', status: 'running' });
      }
      if (url.startsWith('/api/script-prompt/status')) {
        return jsonRes(200, { status: 'done',
          script: 'QUOTA SCRIPT', prompts: [],
          mode: 'script', route: 'captions' });
      }
      throw new Error('unexpected fetch ' + url);
    },
  });
  const el = env.registry;
  await flush();
  assert.strictEqual(el.spLeftScript.textContent, UNLIMITED_S);
  assert.strictEqual(el.spLeftPrompts.textContent, UNLIMITED_P);
  assert.strictEqual(el.spRefreshAt.textContent, '');
  assert.strictEqual(quotaFetched, false,
    'round 3: the SP client must not fetch quota counters');
  el.spUrl.value = 'https://youtu.be/abc';
  el.spBtnScript.click();
  await flush();
  assert.strictEqual(el.spScript.value, 'QUOTA SCRIPT');
  assert.strictEqual(el.spLeftScript.textContent, UNLIMITED_S);
  console.log('PASS unlimited lines shown, generation runs, ' +
              'no quota fetch');
}

/* ---------- scenario 2: rate_limited shows its message ------- */
async function scenarioRateLimited() {
  const env = buildEnv({
    fetchHandler: async (url) => {
      if (url === '/api/info') return jsonRes(200, {});
      if (url === '/api/script-prompt') {
        return jsonRes(429, { error: 'rate_limited' });
      }
      throw new Error('unexpected fetch ' + url);
    },
  });
  const el = env.registry;
  await flush();
  assert.strictEqual(el.spLeftScript.textContent, UNLIMITED_S);
  el.spUrl.value = 'https://youtu.be/abc';
  el.spBtnScript.click();
  await flush();
  assert.strictEqual(el.spError.textContent, 'RATE');
  assert.strictEqual(el.spError.style.display, 'block');
  assert.strictEqual(el.spBtnScript.disabled, false);
  console.log('PASS rate_limited: 429 shows the please-wait message');
}

(async () => {
  await scenarioUnlimited();
  await scenarioRateLimited();
  console.log('ALL SP QUOTA JS TESTS PASS');
})().catch((e) => { console.error(e); process.exit(1); });
