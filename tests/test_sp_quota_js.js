/* DOM-stub tests for the Script+Prompt DAILY COUNTER client
   (templates/_spjs.html): the two counter lines render from a
   stubbed GET /api/script-prompt/quota response, the refresh
   line shows the reset time formatted in local time from the
   resets_at epoch, the counters refresh after a generation
   finishes, and a 429 daily_limit POST shows its own message.
   Run:  node tests/test_sp_quota_js.js */
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'templates', '_spjs.html'), 'utf8');
const code = html.match(/<script>([\s\S]*)<\/script>/)[1];

/* A fixed future reset instant (captured before Date is faked). */
const RESETS_AT = Math.floor(Date.now() / 1000) + 3600;

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
    sp_err_daily_limit: 'DAILY LIMIT REACHED',
    sp_left_script: 'Scripts left today: {n}',
    sp_left_prompts: 'Prompts left today: {n}',
    sp_refresh_at: 'Counters refresh daily at {time}',
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

/* ---------- scenario 1: counters render + refresh ------------ */
async function scenarioCounters() {
  const quota = {
    script_left: 10, prompts_left: 9,
    script_max: 10, prompts_max: 10, resets_at: RESETS_AT,
  };
  const env = buildEnv({
    fetchHandler: async (url) => {
      if (url === '/api/script-prompt/quota') {
        return jsonRes(200, Object.assign({}, quota));
      }
      if (url === '/api/info') return jsonRes(200, {});
      if (url === '/api/script-prompt') {
        return jsonRes(202, { job_id: 'qjob1',
                              status: 'running' });
      }
      if (url.startsWith('/api/script-prompt/status')) {
        /* The finished job consumed one script slot. */
        quota.script_left = 9;
        return jsonRes(200, { status: 'done',
          script: 'QUOTA SCRIPT', prompts: [],
          mode: 'script', route: 'captions' });
      }
      throw new Error('unexpected fetch ' + url);
    },
  });
  const el = env.registry;
  await flush();
  /* Counters rendered from the load-time quota fetch. */
  assert.strictEqual(el.spLeftScript.textContent,
                     'Scripts left today: 10');
  assert.strictEqual(el.spLeftPrompts.textContent,
                     'Prompts left today: 9');
  /* Refresh line: the template text + a formatted local time. */
  assert.ok(/^Counters refresh daily at \d{1,2}:\d{2}/.test(
    el.spRefreshAt.textContent),
    'refresh line: ' + el.spRefreshAt.textContent);
  /* Run a script generation; when it finishes the counters are
     re-fetched and the script line drops by one. */
  el.spUrl.value = 'https://youtu.be/abc';
  el.spBtnScript.click();
  await flush();
  assert.strictEqual(el.spScript.value, 'QUOTA SCRIPT');
  assert.strictEqual(el.spLeftScript.textContent,
                     'Scripts left today: 9');
  assert.strictEqual(el.spLeftPrompts.textContent,
                     'Prompts left today: 9');
  console.log('PASS counters: render on load, refresh line shows ' +
              'a local time, counters refresh after generation');
}

/* ---------- scenario 2: daily_limit shows its message -------- */
async function scenarioDailyLimit() {
  const env = buildEnv({
    fetchHandler: async (url) => {
      if (url === '/api/script-prompt/quota') {
        return jsonRes(200, { script_left: 0, prompts_left: 2,
          script_max: 10, prompts_max: 10,
          resets_at: RESETS_AT });
      }
      if (url === '/api/info') return jsonRes(200, {});
      if (url === '/api/script-prompt') {
        return jsonRes(429, { error: 'daily_limit' });
      }
      throw new Error('unexpected fetch ' + url);
    },
  });
  const el = env.registry;
  await flush();
  assert.strictEqual(el.spLeftScript.textContent,
                     'Scripts left today: 0');
  el.spUrl.value = 'https://youtu.be/abc';
  el.spBtnScript.click();
  await flush();
  assert.strictEqual(el.spError.textContent, 'DAILY LIMIT REACHED');
  assert.strictEqual(el.spError.style.display, 'block');
  assert.strictEqual(el.spBtnScript.disabled, false);
  console.log('PASS daily_limit: 429 shows the daily-limit message');
}

(async () => {
  await scenarioCounters();
  await scenarioDailyLimit();
  console.log('ALL SP QUOTA JS TESTS PASS');
})().catch((e) => { console.error(e); process.exit(1); });
