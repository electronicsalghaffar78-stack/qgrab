/* Subscribe popup trigger logic (round 3): the decision
   function from templates/_subscribejs.html — shows at the
   3rd download, never when subscribed, not again within
   7 days of a dismissal, again after 7 days.
   Run:  node tests/test_subscribe_js.js */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'templates', '_subscribejs.html'), 'utf8');
const code = html.match(/<script>([\s\S]*)<\/script>/)[1];

function makeWorld({ downloads, subscribed, dismissed }) {
  const store = {};
  if (subscribed) store.qgrab_subscribed = '1';
  if (dismissed) store.qgrab_sub_dismissed = String(dismissed);
  const sandbox = {
    console,
    fetch: () => Promise.reject(new Error('offline')),
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
    document: {
      querySelectorAll: () => [],
      createElement: () => ({ classList: { add() {} }, style: {},
        addEventListener() {}, querySelector: () => null,
        set innerHTML(v) {}, }),
      body: { appendChild() {} },
    },
    QGHistory: { list: () => new Array(downloads).fill({}) },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(code, sandbox, { filename: '_subscribejs.html' });
  return sandbox;
}

const NOW = 1763000000000;
const DAY = 24 * 3600 * 1000;

let w = makeWorld({ downloads: 2 });
assert.strictEqual(w.qgrabSubShouldShow(NOW), false, 'not before 3rd download');
w = makeWorld({ downloads: 3 });
assert.strictEqual(w.qgrabSubShouldShow(NOW), true, 'shows at 3rd download');
w = makeWorld({ downloads: 9 });
assert.strictEqual(w.qgrabSubShouldShow(NOW), true, 'still shows after 3rd');
w = makeWorld({ downloads: 5, subscribed: true });
assert.strictEqual(w.qgrabSubShouldShow(NOW), false, 'never when subscribed');
w = makeWorld({ downloads: 5, dismissed: NOW - 3 * DAY });
assert.strictEqual(w.qgrabSubShouldShow(NOW), false, 'not within 7 days of dismissal');
w = makeWorld({ downloads: 5, dismissed: NOW - 8 * DAY });
assert.strictEqual(w.qgrabSubShouldShow(NOW), true, 'again after 7 days');
assert.strictEqual(typeof w.qgStat, 'function', 'qgStat helper defined');

console.log('test_subscribe_js: ALL PASS');
