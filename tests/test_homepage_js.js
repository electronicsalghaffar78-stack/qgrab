/* DOM-stub runtime tests for the homepage's inline scripts
   (theme init, three-dot menu, reviews widget, downloader UI,
   Script+Prompt tool) — the exact code the Flask app serves,
   extracted from the rendered page, then driven through the
   main interactive flows against a stub DOM + stub fetch:
     - theme: <html data-theme> set, qgrabToggleTheme flips and
       persists to localStorage
     - menu: opens on click, closes on outside click and Escape
     - downloader: /api/info submit renders title/meta/thumbnail
       and the format groups (merge, audio, MP3, captions with a
       language <select> whose default value is the first
       caption language); a format click shows the "Please wait"
       download state, which restores itself after 5 s
     - reviews: picking a star and submitting hides the form,
       shows the thanks block and updates the summary
     - SP tool: counters render from the quota endpoint and a
       generation fills the script pane via job polling
   Added in the 2026-11-04 audit round: the pre-existing suites
   covered the SP tool's JS in isolation, but nothing executed
   the downloader / menu / theme / reviews code at runtime.
   Run:  node tests/test_homepage_js.js */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const { execFileSync } = require('child_process');

/* ---------- extract the served inline scripts ---------- */
const repoRoot = path.join(__dirname, '..');
/* The master tree carries the .venv; the deploy-repo snapshot
   does not, so fall back to the sibling master tree's venv. */
const pyCandidates = [
  process.env.QGRAB_PYTHON,
  path.join(repoRoot, '.venv', 'bin', 'python'),
  path.join(repoRoot, '..', 'downloader-site', '.venv', 'bin', 'python'),
  'python3',
].filter(Boolean);
const py = pyCandidates.find((p) => p === 'python3' || fs.existsSync(p));
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qgrab-home-js-'));
const dump = `
import re, sys, os
sys.path.insert(0, ${JSON.stringify(repoRoot)})
os.environ.setdefault("QGRAB_DATA_DIR", ${JSON.stringify(outDir)})
import app as A
html = A.app.test_client().get("/").get_data(as_text=True)
blocks = re.findall(r"<script(?![^>]*application/ld\\+json)([^>]*)>([\\s\\S]*?)</script>", html)
n = 0
for attrs, body in blocks:
    if "src=" in attrs or not body.strip():
        continue
    with open(os.path.join(${JSON.stringify(outDir)}, f"s{n:02d}.js"), "w") as fh:
        fh.write(body)
    n += 1
print(n)
`;
const count = parseInt(execFileSync(py, ['-c', dump], { encoding: 'utf8' }).trim(), 10);
assert.ok(count >= 5, `expected >=5 inline scripts, got ${count}`);
const scripts = fs.readdirSync(outDir).filter((f) => f.endsWith('.js')).sort()
  .map((f) => fs.readFileSync(path.join(outDir, f), 'utf8'));

/* ---------------- fake timers ---------------- */
let timers = new Map(), tseq = 0, now = 0;
function fakeSetTimeout(cb, ms) { const id = ++tseq; timers.set(id, { at: now + (ms || 0), cb, interval: 0 }); return id; }
function fakeSetInterval(cb, ms) { const id = ++tseq; timers.set(id, { at: now + (ms || 0), cb, interval: ms || 0 }); return id; }
function fakeClear(id) { timers.delete(id); }
function tick(ms) {
  const end = now + ms;
  for (;;) {
    let nxt = null;
    for (const [id, t] of timers) if (t.at <= end && (!nxt || t.at < nxt.t.at)) nxt = { id, t };
    if (!nxt) break;
    now = nxt.t.at;
    if (nxt.t.interval) nxt.t.at = now + nxt.t.interval; else timers.delete(nxt.id);
    nxt.t.cb();
  }
  now = end;
}
const realImmediate = setImmediate;
async function flush(n = 30) { for (let i = 0; i < n; i++) await new Promise((r) => realImmediate(r)); }

/* ---------------- DOM stub ---------------- */
class El {
  constructor(tag) {
    this.tagName = (tag || 'div').toUpperCase();
    this.children = [];
    this.parent = null;
    this.listeners = {};
    this.style = {};
    this.dataset = {};
    this.attrs = {};
    this._classes = new Set();
    this.textContent = '';
    this._innerHTML = '';
    this._value = '';
    this.hidden = false;
    this.disabled = false;
    const self = this;
    this.classList = {
      add: (...c) => c.forEach((x) => self._classes.add(x)),
      remove: (...c) => c.forEach((x) => self._classes.delete(x)),
      toggle: (c, force) => { const on = force !== undefined ? force : !self._classes.has(c); on ? self._classes.add(c) : self._classes.delete(c); return on; },
      contains: (c) => self._classes.has(c),
    };
  }
  get value() {
    /* Browser parity: a <select> with no explicit selection
       reports its first option's value. */
    if (this.tagName === 'SELECT' && this._value === '') {
      const opt = this.children.find((c) => c.tagName === 'OPTION');
      if (opt) return opt._value;
    }
    return this._value;
  }
  set value(v) { this._value = String(v); }
  get className() { return [...this._classes].join(' '); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(v) { this._innerHTML = String(v); if (v === '') this.children = []; }
  get href() { return this.attrs.href || ''; }
  set href(v) { this.attrs.href = String(v); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  removeEventListener() {}
  dispatch(ev, obj = {}) {
    const e = Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, obj);
    return (this.listeners[ev] || []).map((f) => f(e));
  }
  append(...kids) { for (const k of kids) { if (k && typeof k === 'object') { k.parent = this; this.children.push(k); } } }
  appendChild(k) { this.append(k); return k; }
  prepend(k) { if (k && typeof k === 'object') { k.parent = this; this.children.unshift(k); } }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  closest(sel) {
    let el = this;
    const m = sel.match(/^([a-z]+)?(\[data-v\])?$/i);
    while (el) {
      if (m) {
        const tagOk = !m[1] || el.tagName === m[1].toUpperCase();
        const dvOk = !m[2] || (el.dataset && el.dataset.v !== undefined);
        if (tagOk && dvOk) return el;
      }
      el = el.parent;
    }
    return null;
  }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  scrollIntoView() {}
  focus() {}
  select() {}
  remove() {}
  click() { this.dispatch('click'); }
}

const registry = {};
const documentEl = new El('html');
const document = {
  documentElement: documentEl,
  body: new El('body'),
  listeners: {},
  getElementById(id) { if (!registry[id]) { registry[id] = new El('div'); registry[id].id = id; } return registry[id]; },
  createElement(tag) { return new El(tag); },
  createTextNode(t) { const n = new El('#text'); n.textContent = String(t); return n; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
  dispatch(ev, obj = {}) { const e = Object.assign({ target: document.body, preventDefault() {}, stopPropagation() {} }, obj); (this.listeners[ev] || []).forEach((f) => f(e)); },
};

const store = new Map();
const localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
const sessionStore = new Map();
const sessionStorage = {
  getItem: (k) => (sessionStore.has(k) ? sessionStore.get(k) : null),
  setItem: (k, v) => sessionStore.set(k, String(v)),
  removeItem: (k) => sessionStore.delete(k),
};

/* ---------------- fetch stub ---------------- */
function jsonResp(status, obj) {
  return { ok: status >= 200 && status < 300, status, json: async () => obj, text: async () => JSON.stringify(obj) };
}
let spPolls = 0;
async function fetchStub(url) {
  const u = String(url);
  if (u.includes('/api/info')) return jsonResp(200, {
    title: 'Test Video', site: 'TikTok', duration_h: '0:42', uploader: 'tester',
    thumbnail: 'https://img.example/t.jpg',
    formats: [
      { id: 'merge:720', label: '720p', ext: 'mp4', kind: 'video+audio', size_h: '8 MB' },
      { id: '136', label: '136', ext: 'mp4', kind: 'video', size_h: '' },
      { id: '140', label: '140', ext: 'm4a', kind: 'audio', size_h: '1 MB' },
    ],
    mp3: true,
    captions: [{ code: 'en', name: 'English' }],
  });
  if (u.includes('/api/rate')) return jsonResp(200, { ok: true, average: 5, count: 1, reviews: [] });
  if (u.includes('/api/script-prompt/quota')) return jsonResp(200, { script_left: 10, prompts_left: 10, script_max: 10, prompts_max: 10, resets_at: Math.floor(Date.now() / 1000) + 3600 });
  if (u.includes('/api/script-prompt/status')) { spPolls++; return jsonResp(200, { status: 'done', title: 'Test Video', mode: 'script', route: 'captions', script: 'Hello script text.', prompts: [], truncated: false }); }
  if (u.includes('/api/script-prompt')) return jsonResp(202, { job_id: 'job1', status: 'running' });
  return jsonResp(404, { error: 'unstubbed ' + u });
}

const windowObj = {
  addEventListener(ev, fn) { (this._l = this._l || {}); (this._l[ev] = this._l[ev] || []).push(fn); },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  location: { href: 'http://localhost/', reload() {} },
  navigator: {},
  localStorage, sessionStorage,
  document,
  fetch: fetchStub,
  setTimeout: fakeSetTimeout, setInterval: fakeSetInterval,
  clearTimeout: fakeClear, clearInterval: fakeClear,
  URL, JSON, Date, Math, Promise, encodeURIComponent, decodeURIComponent,
  console,
};
windowObj.window = windowObj;
windowObj.self = windowObj;
const ctx = vm.createContext(windowObj);

/* Elements the page serves with content the scripts rely on */
const starInput = document.getElementById('starInput');
for (let v = 1; v <= 5; v++) { const b = new El('button'); b.dataset.v = String(v); starInput.appendChild(b); }
document.getElementById('hmenuPanel').hidden = true;

const results = [];
function check(name, fn) {
  try { fn(); results.push('PASS ' + name); }
  catch (e) { results.push('FAIL ' + name + ' :: ' + (e && e.message)); }
}

(async () => {
  const loadErrors = [];
  scripts.forEach((code, i) => {
    try { vm.runInContext(code, ctx, { filename: `inline-${i}.js` }); }
    catch (e) { loadErrors.push(`script ${i}: ${e.message}`); }
  });
  await flush();
  check('all homepage scripts load without throwing', () => assert.deepStrictEqual(loadErrors, []));

  check('theme initialised on <html data-theme>', () => {
    const th = documentEl.getAttribute('data-theme');
    assert.ok(th === 'dark' || th === 'light', 'data-theme=' + th);
  });
  check('theme toggle flips + persists', () => {
    const before = documentEl.getAttribute('data-theme');
    windowObj.qgrabToggleTheme();
    const after = documentEl.getAttribute('data-theme');
    assert.notStrictEqual(after, before);
    assert.strictEqual(localStorage.getItem('qgrab_theme'), after);
  });

  const hbtn = document.getElementById('hmenuBtn');
  const panel = document.getElementById('hmenuPanel');
  check('menu opens on button click', () => {
    hbtn.dispatch('click');
    assert.strictEqual(panel.hidden, false);
    assert.strictEqual(hbtn.getAttribute('aria-expanded'), 'true');
  });
  check('menu closes on outside document click', () => {
    document.dispatch('click');
    assert.strictEqual(panel.hidden, true);
  });
  check('menu closes on Escape', () => {
    hbtn.dispatch('click');
    document.dispatch('keydown', { key: 'Escape' });
    assert.strictEqual(panel.hidden, true);
  });

  const input = document.getElementById('urlInput');
  input.value = 'https://www.tiktok.com/@x/video/123';
  document.getElementById('grabForm').dispatch('submit');
  await flush();
  const result = document.getElementById('result');
  const box = document.getElementById('rFormats');
  check('info flow shows result box', () => assert.strictEqual(result.style.display, 'block'));
  check('info flow fills title + meta', () => {
    assert.strictEqual(document.getElementById('rTitle').textContent, 'Test Video');
    assert.ok(document.getElementById('rMeta').textContent.includes('TikTok'));
  });
  check('thumbnail src set from info', () => {
    assert.strictEqual(document.getElementById('rThumb').src, 'https://img.example/t.jpg');
  });
  function walk(el, out = []) { for (const c of el.children || []) { out.push(c); walk(c, out); } return out; }
  const anchors = walk(box).filter((n) => n.tagName === 'A');
  check('formats rendered incl. merge + mp3 + captions rows', () => {
    const hrefs = anchors.map((a) => a.href);
    assert.ok(hrefs.some((h) => h.includes('format_id=merge%3A720')), hrefs.join(','));
    assert.ok(hrefs.some((h) => h.includes('format_id=mp3')), hrefs.join(','));
    assert.ok(hrefs.some((h) => h.includes('format_id=subs%3Aen')), hrefs.join(','));
    assert.ok(hrefs.some((h) => h.includes('format_id=transcript%3Aen')), hrefs.join(','));
  });
  const dlStatus = document.getElementById('dlStatus');
  const mp3Anchor = anchors.find((x) => x.href.includes('format_id=mp3'));
  check('format click -> Please wait state', () => {
    box.dispatch('click', { target: mp3Anchor });
    assert.strictEqual(mp3Anchor.dataset.dlBusy, '1');
    assert.strictEqual(dlStatus.textContent, 'Please wait');
    assert.strictEqual(dlStatus.style.display, 'block');
  });
  check('download state restores after 5s', () => {
    tick(5000);
    assert.strictEqual(mp3Anchor.dataset.dlBusy, undefined);
    assert.strictEqual(dlStatus.style.display, 'none');
  });

  starInput.dispatch('click', { target: starInput.children[4] });
  document.getElementById('rateName').value = 'Tester';
  document.getElementById('rateText').value = 'Great tool';
  document.getElementById('rateForm').dispatch('submit');
  await flush();
  check('review submit hides form + shows thanks', () => {
    assert.strictEqual(document.getElementById('rateForm').style.display, 'none');
    assert.strictEqual(document.getElementById('rateThanks').style.display, 'block');
  });
  check('review submit updates summary', () => {
    assert.strictEqual(document.getElementById('rateNum').textContent, '5.0');
  });

  check('SP counters rendered from quota endpoint', () => {
    assert.ok(document.getElementById('spLeftScript').textContent.includes('10'));
    assert.ok(document.getElementById('spLeftPrompts').textContent.includes('10'));
    assert.ok(document.getElementById('spRefreshAt').textContent.length > 5);
  });
  document.getElementById('spUrl').value = 'https://www.tiktok.com/@x/video/123';
  document.getElementById('spBtnScript').click();
  await flush();
  tick(3000); await flush(); tick(3000); await flush();
  check('SP generation fills script pane via polling', () => {
    assert.strictEqual(document.getElementById('spScript').value, 'Hello script text.');
    assert.ok(spPolls >= 1);
  });

  console.log(results.join('\n'));
  const fails = results.filter((r) => r.startsWith('FAIL'));
  console.log(fails.length ? `\n${fails.length} FAILURES` : '\nALL HOMEPAGE JS TESTS PASS');
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.log(results.join('\n')); console.error('HARNESS ERROR', e); process.exit(2); });
