/* Download History + assistant fallback tests (round 2/3,
   2026-11-16). Drives templates/_historyjs.html and
   templates/_asstfallback.html in a vm with DOM/localStorage
   stubs: record -> persists -> "reload" (fresh context, same
   storage) -> render shows a Download Again anchor straight
   to /download?url=..&format_id=.. -> todayCount -> clear.
   Fallback: payment question gets the free-site answer with
   no goto, history question goes to download-history, an
   unrelated question returns null.
   Run:  node tests/test_history_js.js */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function scriptOf(file) {
  const html = fs.readFileSync(path.join(__dirname, '..', 'templates', file), 'utf8');
  return html.match(/<script>([\s\S]*)<\/script>/)[1];
}

function makeEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(), children: [], listeners: {},
    style: {}, className: '', textContent: '', href: '', src: '', alt: '',
    loading: '',
    appendChild(c) { this.children.push(c); return c; },
    append(...cs) { cs.forEach((c) => this.children.push(c)); },
    addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    remove() { this.removed = true; },
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return this._ih || ''; },
    set(v) { this._ih = v; if (v === '') this.children = []; },
  });
  return el;
}

function makeWorld(storage) {
  const els = { histList: makeEl('div'), histEmpty: makeEl('p'), histClear: makeEl('button') };
  const docListeners = {};
  const sandbox = {
    console,
    localStorage: {
      getItem: (k) => (k in storage ? storage[k] : null),
      setItem: (k, v) => { storage[k] = String(v); },
      removeItem: (k) => { delete storage[k]; },
    },
    document: {
      getElementById: (id) => els[id] || null,
      createElement: (tag) => makeEl(tag),
      addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  return { sandbox, els, docListeners };
}

const histCode = scriptOf('_historyjs.html');
const storage = {};

// --- first visit: record two downloads
let w = makeWorld(storage);
vm.runInNewContext(histCode, w.sandbox, { filename: '_historyjs.html' });
assert(w.sandbox.QGHistory, 'QGHistory exposed');
w.sandbox.QGHistory.record({
  url: 'https://www.youtube.com/watch?v=abc123', title: 'Test Video',
  thumb: 'https://i.ytimg.com/vi/abc123/hq.jpg', platform: 'youtube',
  format: 'MP4 · 720p', format_id: '22',
});
w.sandbox.QGHistory.record({
  url: 'https://www.tiktok.com/@a/video/1', title: '', thumb: '',
  platform: 'tiktok', format: 'MP3', format_id: '',
});
const saved = JSON.parse(storage.qgrab_dl_history_v1);
assert.strictEqual(saved.length, 2, 'two items stored');
assert.strictEqual(saved[0].url, 'https://www.tiktok.com/@a/video/1', 'newest first');
assert.strictEqual(w.sandbox.QGHistory.todayCount(), 2, 'todayCount counts both');

// --- reload: fresh context, same storage -> list survives + renders
w = makeWorld(storage);
vm.runInNewContext(histCode, w.sandbox, { filename: '_historyjs.html' });
assert.strictEqual(w.sandbox.QGHistory.list().length, 2, 'history survives reload');
w.docListeners.DOMContentLoaded.forEach((fn) => fn());
const rows = w.els.histList.children;
assert.strictEqual(rows.length, 2, 'render makes two rows');
const againA = rows[1].children[rows[1].children.length - 1];
assert.strictEqual(againA.textContent, 'Download Again');
assert.strictEqual(
  againA.href,
  '/download?url=' + encodeURIComponent('https://www.youtube.com/watch?v=abc123') + '&format_id=22',
  'Download Again href re-runs the exact download');
const againB = rows[0].children[rows[0].children.length - 1];
assert.strictEqual(againB.href, '#download-history', 'no format_id -> rerun anchor');
assert.strictEqual(w.els.histEmpty.style.display, 'none', 'empty note hidden');
assert.strictEqual(w.els.histClear.style.display, '', 'clear button shown');

// --- clear empties everything
w.sandbox.QGHistory.clear();
assert.strictEqual(JSON.parse(storage.qgrab_dl_history_v1).length, 0, 'clear wipes storage');
assert.strictEqual(w.sandbox.QGHistory.todayCount(), 0);

// --- assistant fallback
const fbCode = scriptOf('_asstfallback.html');
const w2 = { window: {} };
vm.runInNewContext(fbCode, w2, { filename: '_asstfallback.html' });
const fb = w2.window.qgrabAssistantFallback;
assert.strictEqual(typeof fb, 'function');
let out = fb('How do I pay with JazzCash?');
assert(out && out.goto === null && /completely free/.test(out.answer), 'payment -> free answer');
out = fb('what is the premium price?');
assert(out && /100% free/.test(out.answer), 'premium -> free answer');
out = fb('where is my download history?');
assert(out && out.goto === 'download-history', 'history -> section');
out = fb('how can i download a video');
assert(out && out.goto === 'download', 'download -> downloader');
out = fb('who won the cricket match yesterday?');
assert.strictEqual(out, null, 'unrelated -> null (strict scope)');

console.log('test_history_js: ALL PASS');
