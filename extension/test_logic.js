'use strict';

/*
 * Unit tests for the pure URL helpers in content.js (and the format
 * normaliser in background.js). No browser, no network, no dependencies.
 *
 * Run:  node extension/test_logic.js
 * Exit code 0 = all passed, 1 = at least one failure.
 */

var assert = require('assert');
var path = require('path');

var content = require(path.join(__dirname, 'content.js'));
var background = require(path.join(__dirname, 'background.js'));

var qgrabPageVideoUrl = content.qgrabPageVideoUrl;
var buildDownloadUrl = content.buildDownloadUrl;
var buildOpenUrl = content.buildOpenUrl;

var passed = 0;
var failed = 0;

function check(name, fn) {
  try {
    fn();
    passed++;
    console.log('ok   - ' + name);
  } catch (err) {
    failed++;
    console.error('FAIL - ' + name);
    console.error('       ' + (err && err.message ? err.message : err));
  }
}

/* ---- Required cases (from the task) ---- */

check('youtube watch URL maps to its canonical form', function () {
  assert.strictEqual(
    qgrabPageVideoUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ'),
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
  );
});

check('youtube watch URL strips tracking / extra params', function () {
  assert.strictEqual(
    qgrabPageVideoUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123'),
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
  );
});

check('youtu.be URL maps to canonical youtube watch URL', function () {
  assert.strictEqual(
    qgrabPageVideoUrl('https://youtu.be/dQw4w9WgXcQ'),
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
  );
  assert.strictEqual(
    qgrabPageVideoUrl('https://youtu.be/dQw4w9WgXcQ?si=abcdef'),
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
  );
});

check('facebook watch URL maps to its canonical form', function () {
  assert.strictEqual(
    qgrabPageVideoUrl('https://www.facebook.com/watch?v=123456789012345'),
    'https://www.facebook.com/watch?v=123456789012345'
  );
  assert.strictEqual(
    qgrabPageVideoUrl('https://www.facebook.com/watch/?v=123456789012345'),
    'https://www.facebook.com/watch?v=123456789012345'
  );
});

check('youtube homepage returns null', function () {
  assert.strictEqual(qgrabPageVideoUrl('https://www.youtube.com/'), null);
  assert.strictEqual(qgrabPageVideoUrl('https://www.youtube.com'), null);
});

check('unrelated site returns null', function () {
  assert.strictEqual(qgrabPageVideoUrl('https://example.com/watch?v=dQw4w9WgXcQ'), null);
  assert.strictEqual(qgrabPageVideoUrl('https://vimeo.com/123456789'), null);
  assert.strictEqual(qgrabPageVideoUrl('https://www.google.com/'), null);
});

/* ---- Extra coverage ---- */

check('accepts a Location-like object ({ href })', function () {
  assert.strictEqual(
    qgrabPageVideoUrl({ href: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1' }),
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
  );
});

check('accepts a Location-like object ({ hostname, pathname, search })', function () {
  assert.strictEqual(
    qgrabPageVideoUrl({ protocol: 'https:', hostname: 'www.facebook.com', pathname: '/watch', search: '?v=987654321' }),
    'https://www.facebook.com/watch?v=987654321'
  );
});

check('youtube Shorts map to canonical watch URL', function () {
  assert.strictEqual(
    qgrabPageVideoUrl('https://www.youtube.com/shorts/dQw4w9WgXcQ'),
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
  );
});

check('facebook reel URL is recognised', function () {
  assert.strictEqual(
    qgrabPageVideoUrl('https://www.facebook.com/reel/123456789012345'),
    'https://www.facebook.com/reel/123456789012345'
  );
});

check('facebook page videos URL is recognised', function () {
  assert.strictEqual(
    qgrabPageVideoUrl('https://www.facebook.com/SomePage/videos/123456789012345/'),
    'https://www.facebook.com/SomePage/videos/123456789012345/'
  );
});

check('facebook homepage / non-video pages return null', function () {
  assert.strictEqual(qgrabPageVideoUrl('https://www.facebook.com/'), null);
  assert.strictEqual(qgrabPageVideoUrl('https://www.facebook.com/watch'), null);
});

check('youtube non-video pages return null', function () {
  assert.strictEqual(qgrabPageVideoUrl('https://www.youtube.com/results?search_query=cat'), null);
  assert.strictEqual(qgrabPageVideoUrl('https://www.youtube.com/watch'), null);
  assert.strictEqual(qgrabPageVideoUrl('https://www.youtube.com/feed/subscriptions'), null);
});

check('garbage input returns null (never throws)', function () {
  assert.strictEqual(qgrabPageVideoUrl(null), null);
  assert.strictEqual(qgrabPageVideoUrl(undefined), null);
  assert.strictEqual(qgrabPageVideoUrl(''), null);
  assert.strictEqual(qgrabPageVideoUrl('not a url'), null);
  assert.strictEqual(qgrabPageVideoUrl(42), null);
});

check('buildDownloadUrl encodes url + format_id for QGrab /download', function () {
  assert.strictEqual(
    buildDownloadUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ', '22'),
    'https://qgrab.onrender.com/download?url=' +
      encodeURIComponent('https://www.youtube.com/watch?v=dQw4w9WgXcQ') + '&format_id=22'
  );
  // merge ids contain a colon and must survive encoding round-trip
  var u = new URL(buildDownloadUrl('https://www.youtube.com/watch?v=x', 'merge:720'));
  assert.strictEqual(u.searchParams.get('format_id'), 'merge:720');
  assert.strictEqual(u.searchParams.get('url'), 'https://www.youtube.com/watch?v=x');
});

check('buildOpenUrl points at QGrab home with ?url=', function () {
  var u = new URL(buildOpenUrl('https://www.facebook.com/watch?v=123'));
  assert.strictEqual(u.origin + u.pathname, 'https://qgrab.onrender.com/');
  assert.strictEqual(u.searchParams.get('url'), 'https://www.facebook.com/watch?v=123');
});

check('background.normalizeFormats maps /api/info formats', function () {
  var out = background.normalizeFormats([
    { id: '22', label: '720p', kind: 'video+audio', ext: 'mp4', size_h: '12.3 MB' },
    { format_id: 18, label: '360p' },
    { label: 'no id — skipped' },
    null
  ]);
  assert.strictEqual(out.length, 2);
  assert.strictEqual(out[0].id, '22');
  assert.strictEqual(out[0].size_h, '12.3 MB');
  assert.strictEqual(out[1].id, '18');
  assert.deepStrictEqual(background.normalizeFormats(undefined), []);
});

console.log('');
console.log(passed + ' passed, ' + failed + ' failed');
if (failed > 0) {
  process.exit(1);
}
