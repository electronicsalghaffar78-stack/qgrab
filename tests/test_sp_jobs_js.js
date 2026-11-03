/* DOM-stub tests for the Script+Prompt background-job client
   (templates/_spjs.html, v3): POST -> 202 -> poll -> done fills
   the panes and clears sessionStorage; a job stored in
   sessionStorage on page load resumes polling; a poll request
   that itself fails (network) is retried silently and never
   surfaces as the job's error.
   Run:  node tests/test_sp_jobs_js.js */
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'templates', '_spjs.html'), 'utf8');
const code = html.match(/<script>([\s\S]*)<\/script>/)[1];

/* ---------- fake clock + timers ---------- */
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
async function advance(ms) {
  const target = now + ms;
  for (;;) {
    let next = null;
    for (const [id, t] of timers) {
      if (t.at <= target && (!next || t.at < next.t.at)) next = { id, t };
    }
    if (!next) break;
    now = next.t.at;
    if (next.t.interval) next.t.at = now + next.t.interval;
    else timers.delete(next.id);
    next.t.cb();
    await flush();
  }
  now = target;
  await flush();
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

function buildEnv({ fetchHandler, seedJob }) {
  now = 0;
  timers = new Map();
  timerSeq = 0;
  const registry = {};
  const store = new Map();
  if (seedJob) store.set('sp_job', JSON.stringify(seedJob));
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
  return { registry, store, sessionStorage };
}

function jsonRes(status, body) {
  return { status, ok: status >= 200 && status < 300,
           json: async () => body };
}

/* ---------- scenario 1: fresh job, poll running -> done ------ */
async function scenarioFreshJob() {
  const statusQueue = [
    { status: 'running' },
    { status: 'done', script: 'HELLO SCRIPT', prompts: [],
      mode: 'script', route: 'audio' },
  ];
  const env = buildEnv({
    fetchHandler: async (url) => {
      if (url === '/api/info') return jsonRes(200, { duration: 60 });
      if (url === '/api/script-prompt') {
        return jsonRes(202, { job_id: 'job1', status: 'running' });
      }
      if (url.startsWith('/api/script-prompt/status')) {
        return jsonRes(200, statusQueue.shift());
      }
      throw new Error('unexpected fetch ' + url);
    },
  });
  const el = env.registry;
  el.spUrl.value = 'https://vm.tiktok.com/abc/';
  el.spBtnScript.click();
  await flush();
  /* Job persisted for resume, countdown ticking with the
     duration-sharpened estimate (20 + 0.5*60 = 50s). */
  const stored = JSON.parse(env.store.get('sp_job'));
  assert.strictEqual(stored.job_id, 'job1');
  assert.strictEqual(stored.mode, 'script');
  assert.ok(/Please wait… 0:50/.test(el.spBtnScript.textContent),
            'label: ' + el.spBtnScript.textContent);
  assert.strictEqual(el.spBtnScript.disabled, true);
  await advance(3000);
  assert.strictEqual(el.spScript.value, 'HELLO SCRIPT');
  assert.ok(!env.store.has('sp_job'), 'stored job cleared');
  assert.strictEqual(el.spBtnScript.textContent, 'Create Script');
  assert.strictEqual(el.spBtnScript.disabled, false);
  assert.strictEqual(el.spResult.style.display, 'block');
  console.log('PASS fresh job: 202 -> polls -> done, panes filled, storage cleared');
}

/* ---------- scenario 2: stored job resumes on load ----------- */
async function scenarioResume() {
  const env = buildEnv({
    seedJob: { job_id: 'job9', mode: 'prompts',
               url: 'https://vm.tiktok.com/xyz/',
               started_at: 0 },
    fetchHandler: async (url) => {
      if (url === '/api/info') return jsonRes(200, { duration: 30 });
      if (url.startsWith('/api/script-prompt/status')) {
        return jsonRes(200, { status: 'done', script: '',
          prompts: ['PROMPT ONE'], mode: 'prompts',
          route: 'audio' });
      }
      throw new Error('unexpected fetch ' + url);
    },
  });
  const el = env.registry;
  await flush();
  assert.strictEqual(el.spUrl.value, 'https://vm.tiktok.com/xyz/');
  assert.strictEqual(el.spPrompts.children.length, 1);
  assert.strictEqual(
    el.spPrompts.children[0].children[1].textContent, 'PROMPT ONE');
  assert.ok(!env.store.has('sp_job'), 'stored job cleared');
  assert.strictEqual(el.spBtnPrompts.textContent, 'Create Prompts');
  assert.strictEqual(el.spBtnPrompts.disabled, false);
  console.log('PASS resume: stored job resumed polling and rendered');
}

/* ---------- scenario 3: a failed poll tick is silent --------- */
async function scenarioFlakyPoll() {
  let statusCalls = 0;
  const env = buildEnv({
    fetchHandler: async (url) => {
      if (url === '/api/info') return jsonRes(200, {});
      if (url === '/api/script-prompt') {
        return jsonRes(202, { job_id: 'job3', status: 'running' });
      }
      if (url.startsWith('/api/script-prompt/status')) {
        statusCalls++;
        if (statusCalls === 1) throw new Error('network down');
        return jsonRes(200, { status: 'done',
          script: 'LATE SCRIPT', prompts: [], mode: 'script',
          route: 'captions' });
      }
      throw new Error('unexpected fetch ' + url);
    },
  });
  const el = env.registry;
  el.spUrl.value = 'https://youtu.be/abc';
  el.spBtnScript.click();
  await flush();
  assert.notStrictEqual(el.spError.style.display, 'block',
                        'failed poll must not surface an error');
  await advance(3000);
  assert.strictEqual(el.spScript.value, 'LATE SCRIPT');
  assert.notStrictEqual(el.spError.style.display, 'block');
  console.log('PASS flaky poll: failed tick retried silently, result delivered');
}

(async () => {
  await scenarioFreshJob();
  await scenarioResume();
  await scenarioFlakyPoll();
  console.log('ALL SP JOB JS TESTS PASS');
})().catch((e) => { console.error(e); process.exit(1); });
