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
     - toolkit: submitting a pasted link renders the details
       card (title, meta with null counts hidden, thumbnail,
       hashtag/tag chips, channel link) from /api/video-details
     - ai tools: the quota note renders from /api/ai-tools/quota
       and a generation renders one row per item and updates
       the left count from /api/ai-tools/generate
     - update app: a stored version equal to /api/version's
       toasts "already latest" without reloading; an older one
       records the new version, sets the just-updated flag and
       reloads
     - assistant: the panel opens from the floating button, a
       question renders the user + answer messages (each bubble
       carrying dir="auto" so mixed-direction text never renders
       reversed) with a "Take me there" goto button (whose click
       closes the panel), and the Talk to Support form submits
       and shows the server's confirmation
     - search: each platform tab keeps its OWN query + results
       (switching away and back restores them; a never-searched
       tab shows the clean state), and Watch opens the on-site
       modal with the canonical www.youtube.com embed src for
       YouTube results while a Facebook result keeps its
       official plugin embed src untouched
     - player fullscreen: the Fullscreen pill requests native
       fullscreen on the frame wrapper (a YouTube video also
       tries the guarded landscape orientation lock, a TikTok
       video does not), and when the API is missing or rejects
       (iPhone) the modal's expanded viewport mode takes over
       and toggles back off — the button is never dead
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
  if (u.includes('/api/video-details')) return jsonResp(200, {
    ok: true, title: 'Toolkit Video #cats', description: 'A short description.',
    thumbnail: 'https://img.example/big.jpg',
    webpage_url: 'https://www.youtube.com/watch?v=MIW2VPprnLw',
    uploader: 'Tester', channel_url: 'https://www.youtube.com/@Tester',
    upload_date: '2025-11-02', view_count: 1234, like_count: 56,
    comment_count: null, duration: 372, duration_h: '6:12', site: 'Youtube',
    tags: ['cats', 'fun'], hashtags: ['#cats'],
  });
  if (u.includes('/api/ai-tools/quota')) return jsonResp(200, { left: 10, max: 10, resets_at: Math.floor(Date.now() / 1000) + 3600 });
  if (u.includes('/api/ai-tools/generate')) return jsonResp(200, { ok: true, tool: 'titles', items: ['Title One', 'Title Two'], left: 9, max: 10 });
  if (u.includes('/api/search')) {
    const pu = new URL(u, 'http://stub');
    const plat = pu.searchParams.get('platform') || 'youtube';
    const qq = pu.searchParams.get('q') || '';
    if (plat === 'youtube') return jsonResp(200, { ok: true, results: [
      { id: 'MIW2VPprnLw', title: 'YT one ' + qq, author: 'Chan', thumbnail: '', duration_h: '3:32', views: '', published: '',
        webpage_url: 'https://www.youtube.com/watch?v=MIW2VPprnLw',
        embed_url: 'https://www.youtube-nocookie.com/embed/MIW2VPprnLw' },
      { id: 'dQw4w9WgXcQ', title: 'YT two ' + qq, author: 'Chan', thumbnail: '', duration_h: '3:33', views: '', published: '',
        webpage_url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        embed_url: 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ' },
    ] });
    if (plat === 'facebook') return jsonResp(200, { ok: true, results: [
      { id: 'fb1', title: 'FB one ' + qq, author: '', thumbnail: '', duration_h: '', views: '', published: '',
        webpage_url: 'https://www.facebook.com/watch/?v=123',
        embed_url: 'https://www.facebook.com/plugins/video.php?href=https%3A%2F%2Fwww.facebook.com%2Fwatch%2F%3Fv%3D123&show_text=0' },
    ] });
    if (plat === 'tiktok') return jsonResp(200, { ok: true, results: [
      { id: '7300000000000000001', title: 'TT one ' + qq, author: 'dancer1', thumbnail: '', duration_h: '0:30', views: '', published: '',
        webpage_url: 'https://www.tiktok.com/@dancer1/video/7300000000000000001',
        embed_url: 'https://www.tiktok.com/embed/v2/7300000000000000001' },
    ] });
    return jsonResp(200, { ok: true, results: [] });
  }
  if (u.includes('/api/assistant')) return jsonResp(200, { ok: true, answer: 'Use the downloader box at the top of the page.', goto: 'download', support: false, left: 29, max: 30 });
  if (u.includes('/api/support')) return jsonResp(200, { ok: true, message: 'Thank you! Your message has been received. We will look into it and reply to your email within 24–48 hours. If it is a problem with the site, we aim to fix it within 24–48 hours — please try again after that.' });
  if (u.includes('/api/version')) return jsonResp(200, { version: '2026-11-08.1' });
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

/* Search tabs: the stub DOM has no real .stab buttons, so hand
   the search UI four tab elements through querySelectorAll
   (every other selector keeps the stub's empty answer), and
   give window.location an origin for the player-src builder. */
const stabEls = ['youtube', 'facebook', 'tiktok', 'instagram'].map((p) => {
  const b = new El('button');
  b.dataset.platform = p;
  if (p === 'youtube') b.classList.add('active');
  return b;
});
const realQSA = document.querySelectorAll;
document.querySelectorAll = (sel) => (sel === '.stab' ? stabEls.slice() : realQSA(sel));
windowObj.location.origin = 'https://qgrab.onrender.com';

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

  /* toolkit: paste a link -> details card renders from the API */
  document.getElementById('tkInput').value = 'https://www.youtube.com/watch?v=MIW2VPprnLw';
  document.getElementById('tkForm').dispatch('submit');
  await flush();
  check('toolkit renders details card', () => {
    assert.strictEqual(document.getElementById('tkCard').style.display, '');
    assert.strictEqual(document.getElementById('tkTitle').textContent, 'Toolkit Video #cats');
    const meta = document.getElementById('tkMeta').textContent;
    assert.ok(meta.includes('1,234 views'), meta);
    assert.ok(meta.includes('Published 2025-11-02'), meta);
    assert.ok(!meta.includes('comments'), meta); /* null count hidden */
  });
  check('toolkit fills thumbnail, chips and channel link', () => {
    assert.strictEqual(document.getElementById('tkThumb').src, 'https://img.example/big.jpg');
    assert.strictEqual(document.getElementById('tkThumbDl').href, 'https://img.example/big.jpg');
    assert.strictEqual(document.getElementById('tkHashtags').children.length, 1);
    assert.strictEqual(document.getElementById('tkHashtags').children[0].textContent, '#cats');
    assert.strictEqual(document.getElementById('tkTags').children.length, 2);
    assert.strictEqual(document.getElementById('tkChannel').style.display, '');
    assert.strictEqual(document.getElementById('tkChannel').href, 'https://www.youtube.com/@Tester');
    assert.strictEqual(document.getElementById('tkTagsNone').style.display, 'none');
  });

  /* ai tools: quota note renders; a generation fills result rows */
  check('AI tools quota note rendered', () => {
    assert.ok(document.getElementById('aiLeft').textContent.includes('10'),
      document.getElementById('aiLeft').textContent);
  });
  document.getElementById('aiInput').value = 'funny cats';
  document.getElementById('aiForm').dispatch('submit');
  await flush();
  check('AI generate renders rows + updates left count', () => {
    const rows = document.getElementById('aiResults').children;
    assert.strictEqual(rows.length, 2);
    assert.strictEqual(rows[0].children[0].textContent, 'Title One');
    assert.ok(document.getElementById('aiLeft').textContent.includes('9'));
    assert.strictEqual(document.getElementById('aiActions').style.display, '');
  });

  /* update app: stored version == server version -> toast, no reload */
  let reloads = 0;
  windowObj.location.reload = () => { reloads++; };
  localStorage.setItem('qgrab_app_version', '2026-11-08.1');
  document.getElementById('appUpdateBtn').dispatch('click');
  await flush();
  check('update check at latest version toasts, no reload', () => {
    assert.strictEqual(document.getElementById('spToast').textContent,
      'You already have the latest version.');
    assert.strictEqual(reloads, 0);
  });
  /* update app: older stored version -> record, flag, reload */
  localStorage.setItem('qgrab_app_version', '2026-11-01.1');
  document.getElementById('appUpdateBtn').dispatch('click');
  await flush();
  check('update with older version records + flags + reloads', () => {
    assert.strictEqual(reloads, 1);
    assert.strictEqual(localStorage.getItem('qgrab_app_version'), '2026-11-08.1');
    assert.strictEqual(sessionStorage.getItem('qgrab_just_updated'), '1');
  });
  sessionStorage.removeItem('qgrab_just_updated');

  /* search: per-platform tab state + the on-site Watch player */
  const sGrid = document.getElementById('searchResults');
  const sInputEl = document.getElementById('searchInput');
  const frameEl = document.getElementById('playerFrame');
  const modalEl = document.getElementById('playerModal');
  const hasCls = (n, c) => (n.className || '').split(/\s+/).includes(c);
  const watchBtns = () => walk(sGrid).filter((n) => hasCls(n, 'watch-btn'));
  const cardTitles = () => walk(sGrid).filter((n) => hasCls(n, 'stitle')).map((n) => n.textContent);
  sInputEl.value = 'cats';
  document.getElementById('searchForm').dispatch('submit');
  await flush();
  check('search renders YouTube results', () => {
    assert.strictEqual(sGrid.children.length, 2);
    assert.deepStrictEqual(cardTitles(), ['YT one cats', 'YT two cats']);
  });
  watchBtns()[0].dispatch('click');
  check('Watch plays YouTube in the modal via the canonical embed', () => {
    assert.ok(modalEl.classList.contains('open'));
    assert.strictEqual(frameEl.src,
      'https://www.youtube.com/embed/MIW2VPprnLw?autoplay=1&rel=0&playsinline=1&origin=https%3A%2F%2Fqgrab.onrender.com');
  });
  document.getElementById('playerClose').dispatch('click');
  check('player close clears the frame + hides the modal', () => {
    assert.strictEqual(frameEl.src, '');
    assert.ok(!modalEl.classList.contains('open'));
  });
  stabEls[1].dispatch('click'); /* -> facebook */
  check('switching to Facebook shows its own clean state', () => {
    assert.strictEqual(sInputEl.value, '');
    assert.strictEqual(sGrid.children.length, 0);
    assert.strictEqual(sInputEl.placeholder, 'Search Facebook videos...');
  });
  sInputEl.value = 'dogs';
  document.getElementById('searchForm').dispatch('submit');
  await flush();
  check('Facebook search renders its own results', () => {
    assert.strictEqual(sGrid.children.length, 1);
    assert.deepStrictEqual(cardTitles(), ['FB one dogs']);
  });
  watchBtns()[0].dispatch('click');
  check('Facebook Watch keeps the official plugin embed untouched', () => {
    assert.strictEqual(frameEl.src,
      'https://www.facebook.com/plugins/video.php?href=https%3A%2F%2Fwww.facebook.com%2Fwatch%2F%3Fv%3D123&show_text=0');
  });
  document.getElementById('playerClose').dispatch('click');
  stabEls[0].dispatch('click'); /* -> back to youtube */
  check('returning to YouTube restores its query + results', () => {
    assert.strictEqual(sInputEl.value, 'cats');
    assert.strictEqual(sGrid.children.length, 2);
    assert.deepStrictEqual(cardTitles(), ['YT one cats', 'YT two cats']);
  });
  watchBtns()[1].dispatch('click');
  check('restored YouTube results still play canonically', () => {
    assert.strictEqual(frameEl.src,
      'https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0&playsinline=1&origin=https%3A%2F%2Fqgrab.onrender.com');
  });
  document.getElementById('playerClose').dispatch('click');
  stabEls[2].dispatch('click'); /* -> tiktok, never searched */
  check('a never-searched platform shows the clean state', () => {
    assert.strictEqual(sInputEl.value, '');
    assert.strictEqual(sGrid.children.length, 0);
  });
  stabEls[1].dispatch('click'); /* -> facebook again */
  check('Facebook kept its own search too', () => {
    assert.strictEqual(sInputEl.value, 'dogs');
    assert.strictEqual(sGrid.children.length, 1);
  });

  /* player fullscreen: native request + YouTube landscape lock */
  const fsBtn = document.getElementById('playerFsBtn');
  const fsWrap = document.getElementById('playerFrameWrap');
  check('fullscreen pill is wired in the player', () => {
    assert.ok(fsBtn, 'fullscreen button element missing');
    assert.ok((fsBtn.listeners.click || []).length >= 1,
      'fullscreen button has no click handler');
  });
  let fsCalls = 0, lockCalls = [];
  fsWrap.requestFullscreen = () => { fsCalls++; return Promise.resolve(); };
  windowObj.screen = { orientation: { lock: (o) => { lockCalls.push(o); return Promise.resolve(); } } };
  stabEls[0].dispatch('click'); /* -> youtube (its results are back) */
  watchBtns()[0].dispatch('click');
  fsBtn.dispatch('click');
  await flush();
  check('YouTube fullscreen goes native + locks landscape', () => {
    assert.strictEqual(fsCalls, 1);
    assert.deepStrictEqual(lockCalls, ['landscape']);
    assert.ok(!modalEl.classList.contains('expanded'));
  });
  document.getElementById('playerClose').dispatch('click');
  /* player fullscreen: TikTok goes native, NO orientation lock */
  stabEls[2].dispatch('click'); /* -> tiktok */
  sInputEl.value = 'dance';
  document.getElementById('searchForm').dispatch('submit');
  await flush();
  check('TikTok search renders its result', () => {
    assert.strictEqual(sGrid.children.length, 1);
    assert.deepStrictEqual(cardTitles(), ['TT one dance']);
  });
  watchBtns()[0].dispatch('click');
  check('TikTok Watch loads the embed/v2 src', () => {
    assert.strictEqual(frameEl.src, 'https://www.tiktok.com/embed/v2/7300000000000000001');
  });
  fsCalls = 0; lockCalls = [];
  fsBtn.dispatch('click');
  await flush();
  check('TikTok fullscreen is native only, no landscape lock', () => {
    assert.strictEqual(fsCalls, 1);
    assert.deepStrictEqual(lockCalls, []);
    assert.ok(!modalEl.classList.contains('expanded'));
  });
  document.getElementById('playerClose').dispatch('click');
  /* player fullscreen: a REJECTING request falls back to expanded */
  fsWrap.requestFullscreen = () => Promise.reject(new Error('denied'));
  watchBtns()[0].dispatch('click');
  fsBtn.dispatch('click');
  await flush();
  check('rejected fullscreen falls back to expanded mode', () => {
    assert.ok(modalEl.classList.contains('expanded'));
  });
  fsBtn.dispatch('click');
  await flush();
  check('the same button toggles expanded mode back off', () => {
    assert.ok(!modalEl.classList.contains('expanded'));
  });
  document.getElementById('playerClose').dispatch('click');
  /* player fullscreen: NO API at all (iPhone) -> expanded, and
     closing the player clears it */
  delete fsWrap.requestFullscreen;
  watchBtns()[0].dispatch('click');
  fsBtn.dispatch('click');
  await flush();
  check('missing fullscreen API expands the player', () => {
    assert.ok(modalEl.classList.contains('expanded'));
  });
  document.getElementById('playerClose').dispatch('click');
  check('closing the player clears expanded mode', () => {
    assert.ok(!modalEl.classList.contains('expanded'));
    assert.ok(!modalEl.classList.contains('open'));
  });

  /* assistant: open the panel, ask, get an answer + goto */
  const asstPanel = document.getElementById('asstPanel');
  document.getElementById('asstBtn').dispatch('click');
  check('assistant panel opens on button click', () => {
    assert.strictEqual(asstPanel.style.display, 'flex');
    assert.strictEqual(document.getElementById('asstBtn').getAttribute('aria-expanded'), 'true');
  });
  document.getElementById('asstInput').value = 'How do I download a video?';
  document.getElementById('asstForm').dispatch('submit');
  await flush();
  const asstMsgs = document.getElementById('asstMsgs');
  check('assistant renders user + answer messages', () => {
    assert.strictEqual(asstMsgs.children.length, 2);
    assert.strictEqual(asstMsgs.children[0].textContent, 'How do I download a video?');
    assert.strictEqual(asstMsgs.children[1].textContent, 'Use the downloader box at the top of the page.');
    assert.strictEqual(document.getElementById('asstInput').value, '');
  });
  check('assistant bubbles carry dir=auto (text never reversed)', () => {
    assert.strictEqual(asstMsgs.children[0].getAttribute('dir'), 'auto');
    assert.strictEqual(asstMsgs.children[1].getAttribute('dir'), 'auto');
  });
  const gotoBtn = asstMsgs.children[1].children.find((c) => c.tagName === 'BUTTON');
  check('assistant goto button appears under the answer', () => {
    assert.ok(gotoBtn, 'goto button missing');
    assert.strictEqual(gotoBtn.textContent, 'Take me there →');
  });
  gotoBtn.dispatch('click');
  check('goto click closes the panel', () => {
    assert.strictEqual(asstPanel.style.display, 'none');
  });
  /* assistant: Talk to Support form submits + confirms */
  document.getElementById('asstBtn').dispatch('click');
  document.getElementById('asstSupportBtn').dispatch('click');
  check('support button switches to the support form', () => {
    assert.strictEqual(document.getElementById('asstSupportForm').style.display, 'flex');
    assert.strictEqual(document.getElementById('asstChatView').style.display, 'none');
  });
  document.getElementById('asstSupEmail').value = 'visitor@example.com';
  document.getElementById('asstSupMsg').value = 'The download button does nothing.';
  document.getElementById('asstSupportForm').dispatch('submit');
  await flush();
  check('support submit shows the server confirmation verbatim', () => {
    assert.ok(document.getElementById('asstSupStatus').textContent
      .startsWith('Thank you! Your message has been received.'));
    assert.strictEqual(document.getElementById('asstSupMsg').value, '');
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
