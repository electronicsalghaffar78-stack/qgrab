/* Stats-ping partial (templates/_subscribejs.html).
   Until release 2026-11-16.27 this partial also carried the
   email-subscribe form wiring and the 3rd-download popup
   decision (qgrabSubShouldShow). The owner ordered ALL
   visitor-facing subscribe UI removed in .27, so the contract
   now is: qgStat survives (fire-and-forget POST /api/event —
   history/invite/anim code depends on it) and NO subscribe
   machinery ships anymore.
   Run:  node tests/test_subscribe_js.js */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'templates', '_subscribejs.html'), 'utf8');
const code = html.match(/<script>([\s\S]*)<\/script>/)[1];

/* --- the shipped source carries no subscribe machinery --- */
assert.ok(!code.includes('/api/subscribe'),
  'partial must not call /api/subscribe anymore');
assert.ok(!code.includes('js-sub-form'),
  'partial must not wire subscribe forms anymore');
assert.ok(!code.includes('qgrab_subscribed'),
  'partial must not touch the old subscribed flag');
assert.ok(!code.includes('sub-pop'),
  'partial must not build the subscribe popup anymore');

function makeWorld() {
  const calls = [];
  const sandbox = {
    console,
    fetch: (url, opts) => {
      calls.push({ url, opts });
      return Promise.resolve({});
    },
    localStorage: {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    },
    document: { querySelectorAll: () => [] },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(code, sandbox, { filename: '_subscribejs.html' });
  return { sandbox, calls };
}

const { sandbox, calls } = makeWorld();

/* --- qgStat survives and pings /api/event --- */
assert.strictEqual(typeof sandbox.qgStat, 'function',
  'qgStat must still be defined');
sandbox.qgStat('extension_download');
assert.strictEqual(calls.length, 1, 'qgStat fires exactly one ping');
assert.strictEqual(calls[0].url, '/api/event');
assert.strictEqual(calls[0].opts.method, 'POST');
assert.deepStrictEqual(JSON.parse(calls[0].opts.body),
  { name: 'extension_download' });

/* --- the popup decision/entry points are gone --- */
assert.strictEqual(sandbox.qgrabSubShouldShow, undefined,
  'qgrabSubShouldShow must be gone');
assert.strictEqual(sandbox.qgrabSubMaybeShow, undefined,
  'qgrabSubMaybeShow must be gone');

console.log('PASS test_subscribe_js (stats ping only, subscribe gone)');
