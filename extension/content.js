'use strict';

/*
 * QGrab Downloader — content script
 *
 * Injects a small floating, QGrab-branded panel on YouTube and Facebook
 * video pages. The panel is position:fixed and appended only to
 * document.body (never inserted into Facebook's / YouTube's own DOM
 * trees / containers), so site redesigns do not break it — the worst
 * case is that it floats in its corner, still fully usable.
 *
 * Pure URL helpers (qgrabPageVideoUrl, buildDownloadUrl, buildOpenUrl)
 * are exported at the bottom for Node unit tests. All DOM work is
 * guarded so `require('./content.js')` in Node is safe.
 */

var QGRAB_ORIGIN = 'https://qgrab.onrender.com';

/* ------------------------------------------------------------------ */
/* Pure helpers — no DOM, no chrome.*                                  */
/* ------------------------------------------------------------------ */

/**
 * Accept a string URL, a Location-like object ({ href } or
 * { hostname, pathname, search, protocol }), or null/undefined.
 * Returns a URL object or null.
 */
function _toUrl(input) {
  if (!input) return null;
  try {
    if (typeof input === 'string') {
      return new URL(input);
    }
    if (typeof input === 'object') {
      if (typeof input.href === 'string' && input.href) {
        return new URL(input.href);
      }
      if (typeof input.hostname === 'string' && input.hostname) {
        var proto = input.protocol || 'https:';
        var path = input.pathname || '/';
        var search = input.search || '';
        var hash = input.hash || '';
        return new URL(proto + '//' + input.hostname + path + search + hash);
      }
    }
  } catch (e) {
    return null;
  }
  return null;
}

function _isYouTubeHost(host) {
  return host === 'youtube.com' || host === 'www.youtube.com' ||
    host === 'm.youtube.com' || host === 'music.youtube.com' ||
    host === 'www.youtube-nocookie.com';
}

function _isShortHost(host) {
  return host === 'youtu.be' || host === 'www.youtu.be';
}

function _isFacebookHost(host) {
  return host === 'facebook.com' || host === 'www.facebook.com' ||
    host === 'm.facebook.com' || host === 'mbasic.facebook.com' ||
    host === 'web.facebook.com';
}

function _isFbWatchHost(host) {
  return host === 'fb.watch';
}

/**
 * qgrabPageVideoUrl(locationOrUrl)
 *
 * Returns the canonical video URL for a YouTube / Facebook video page,
 * or null when the page is not a single-video page.
 *
 * Canonical forms:
 *   YouTube watch : https://www.youtube.com/watch?v=<id>
 *   youtu.be/<id> : https://www.youtube.com/watch?v=<id>
 *   YT Shorts     : https://www.youtube.com/watch?v=<id>
 *   FB watch      : https://www.facebook.com/watch?v=<id>
 *   FB reel       : https://www.facebook.com/reel/<id>
 *   FB video      : https://www.facebook.com<path>  (…/videos/<id>/ etc.)
 */
function qgrabPageVideoUrl(input) {
  var u = _toUrl(input);
  if (!u) return null;
  var host = (u.hostname || '').toLowerCase();
  var path = u.pathname || '/';

  /* ---- YouTube short links ---- */
  if (_isShortHost(host)) {
    var shortId = path.replace(/^\/+/, '').split('/')[0];
    if (shortId) {
      return 'https://www.youtube.com/watch?v=' + encodeURIComponent(shortId);
    }
    return null;
  }

  /* ---- YouTube ---- */
  if (_isYouTubeHost(host)) {
    if (path === '/watch') {
      var v = u.searchParams.get('v');
      if (v) return 'https://www.youtube.com/watch?v=' + encodeURIComponent(v);
      return null;
    }
    var shorts = path.match(/^\/shorts\/([\w-]{6,})/);
    if (shorts) {
      return 'https://www.youtube.com/watch?v=' + encodeURIComponent(shorts[1]);
    }
    var live = path.match(/^\/live\/([\w-]{6,})/);
    if (live) {
      return 'https://www.youtube.com/watch?v=' + encodeURIComponent(live[1]);
    }
    var embed = path.match(/^\/embed\/([\w-]{6,})/);
    if (embed) {
      return 'https://www.youtube.com/watch?v=' + encodeURIComponent(embed[1]);
    }
    // Homepage, /feed/*, /results, channel pages, etc. — not a video page.
    return null;
  }

  /* ---- Facebook short links ---- */
  if (_isFbWatchHost(host)) {
    // fb.watch/<code> is itself the shareable canonical link; QGrab /
    // yt-dlp can resolve it. Keep it as-is (https, no tracking params).
    var code = path.replace(/^\/+/, '').split('/')[0];
    if (code) return 'https://fb.watch/' + encodeURIComponent(code) + '/';
    return null;
  }

  /* ---- Facebook ---- */
  if (_isFacebookHost(host)) {
    // /watch?v=<id>  and  /watch/?v=<id>
    if (path === '/watch' || path === '/watch/') {
      var fv = u.searchParams.get('v');
      if (fv) return 'https://www.facebook.com/watch?v=' + encodeURIComponent(fv);
      return null;
    }
    // /reel/<id> , /reels/<id>
    var reel = path.match(/^\/(?:reel|reels)\/(\d+)/);
    if (reel) {
      return 'https://www.facebook.com/reel/' + reel[1];
    }
    // /<page>/videos/<id>/ , /<page>/videos/<set>/<id>/ , /videos/<id>
    var videos = path.match(/\/videos\/(?:[^/]+\/)?(\d{5,})/);
    if (videos) {
      // Preserve the original path — it is already canonical enough and
      // keeps the page context yt-dlp sometimes needs.
      return 'https://www.facebook.com' + path.replace(/\/?$/, '/');
    }
    // /video.php?v=<id> (legacy)
    if (path === '/video.php') {
      var lv = u.searchParams.get('v');
      if (lv) return 'https://www.facebook.com/watch?v=' + encodeURIComponent(lv);
      return null;
    }
    // /<user>/videos/... already handled; /share/v/<code>/ , /share/r/<code>/
    var share = path.match(/^\/share\/[vr]\/([\w-]+)/);
    if (share) {
      return 'https://www.facebook.com' + path;
    }
    return null;
  }

  return null;
}

/** Download link QGrab will process: /download?url=…&format_id=… */
function buildDownloadUrl(pageUrl, formatId) {
  return QGRAB_ORIGIN + '/download?url=' + encodeURIComponent(pageUrl) +
    '&format_id=' + encodeURIComponent(String(formatId));
}

/** "Open in QGrab" link: homepage pre-filled with the video URL. */
function buildOpenUrl(pageUrl) {
  return QGRAB_ORIGIN + '/?url=' + encodeURIComponent(pageUrl);
}

/** True when the current page should show the panel. */
function isSupportedVideoPage(input) {
  return qgrabPageVideoUrl(input) !== null;
}

/* ------------------------------------------------------------------ */
/* DOM panel — browser only                                            */
/* ------------------------------------------------------------------ */

var PANEL_ID = 'qgrab-panel-root';

function _formatRowText(f) {
  var label = f.label || f.id || 'Format';
  var bits = [label];
  if (f.ext) bits.push(String(f.ext).toUpperCase());
  if (f.kind && f.kind !== 'video+audio') bits.push(f.kind);
  if (f.size_h) bits.push(f.size_h);
  return bits.join(' · ');
}

function _el(tag, text, styles, attrs) {
  var node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (styles) {
    for (var k in styles) {
      if (Object.prototype.hasOwnProperty.call(styles, k)) node.style[k] = styles[k];
    }
  }
  if (attrs) {
    for (var a in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, a)) node.setAttribute(a, attrs[a]);
    }
  }
  return node;
}

var BTN_STYLE = {
  background: '#16a34a', color: '#fff', border: 'none', borderRadius: '8px',
  padding: '8px 14px', fontSize: '14px', fontWeight: '700', cursor: 'pointer',
  fontFamily: 'system-ui,-apple-system,Segoe UI,Roboto,sans-serif'
};
var LINK_STYLE = {
  display: 'block', padding: '7px 10px', margin: '4px 0', borderRadius: '6px',
  background: '#f0fdf4', color: '#14532d', textDecoration: 'none',
  fontSize: '13px', fontFamily: 'system-ui,-apple-system,Segoe UI,Roboto,sans-serif'
};

function renderPanel() {
  if (typeof document === 'undefined' || !document.body) return;
  var pageUrl = qgrabPageVideoUrl(window.location);
  var existing = document.getElementById(PANEL_ID);

  if (!pageUrl) {
    if (existing) existing.remove();
    return;
  }
  if (existing) return; // already mounted for this SPA view

  var root = _el('div', null, {
    position: 'fixed', right: '16px', bottom: '16px', zIndex: '2147483647',
    maxWidth: '320px', minWidth: '220px', background: '#ffffff', color: '#111827',
    border: '1px solid #bbf7d0', borderRadius: '12px',
    boxShadow: '0 8px 30px rgba(0,0,0,.25)', padding: '12px'
  }, { id: PANEL_ID, role: 'complementary', 'aria-label': 'QGrab downloader' });

  var header = _el('div', null, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' });
  var title = _el('strong', 'QGrab', { fontSize: '15px', fontFamily: 'system-ui,-apple-system,Segoe UI,Roboto,sans-serif' });
  var close = _el('button', '×', {
    background: 'transparent', border: 'none', fontSize: '18px', lineHeight: '1',
    cursor: 'pointer', color: '#6b7280', padding: '2px 6px'
  }, { type: 'button', 'aria-label': 'Close QGrab panel', title: 'Close' });
  close.addEventListener('click', function () { root.remove(); });
  header.appendChild(title);
  header.appendChild(close);
  root.appendChild(header);

  var btn = _el('button', '⬇ QGrab', BTN_STYLE, { type: 'button' });
  var status = _el('div', '', {
    fontSize: '12px', color: '#4b5563', marginTop: '8px',
    fontFamily: 'system-ui,-apple-system,Segoe UI,Roboto,sans-serif'
  });
  var list = _el('div', null, { marginTop: '6px' });

  var openLink = _el('a', 'Open in QGrab ↗', {
    display: 'inline-block', marginTop: '8px', fontSize: '13px', color: '#15803d',
    fontFamily: 'system-ui,-apple-system,Segoe UI,Roboto,sans-serif'
  }, { href: buildOpenUrl(pageUrl), target: '_blank', rel: 'noopener noreferrer' });

  function showFallback(note) {
    status.textContent = note || 'Could not load formats here. You can still open this video in QGrab:';
    list.innerHTML = '';
    if (!root.contains(openLink)) root.appendChild(openLink);
  }

  btn.addEventListener('click', function () {
    btn.disabled = true;
    btn.textContent = '⏳ Loading…';
    status.textContent = 'Asking QGrab for formats…';
    list.innerHTML = '';

    function done() { btn.disabled = false; btn.textContent = '⬇ QGrab'; }

    if (typeof chrome === 'undefined' || !chrome.runtime || !chrome.runtime.sendMessage) {
      done();
      showFallback('Extension messaging is unavailable. You can still open this video in QGrab:');
      return;
    }

    try {
      chrome.runtime.sendMessage({ type: 'qgrab-info', url: pageUrl }, function (resp) {
        done();
        var lastErr = (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.lastError)
          ? chrome.runtime.lastError.message : null;
        if (lastErr || !resp || !resp.ok || !Array.isArray(resp.formats) || resp.formats.length === 0) {
          var why = (resp && resp.error) ? resp.error : lastErr;
          showFallback(why ? ('Could not load formats (' + why + '). Open this video in QGrab instead:')
                            : 'No formats were returned. Open this video in QGrab instead:');
          return;
        }
        status.textContent = resp.title ? ('Formats for: ' + resp.title) : 'Choose a format — the download is processed by QGrab:';
        resp.formats.forEach(function (f) {
          var a = _el('a', '⬇ ' + _formatRowText(f), LINK_STYLE, {
            href: buildDownloadUrl(pageUrl, f.id), target: '_blank', rel: 'noopener noreferrer'
          });
          list.appendChild(a);
        });
        if (resp.mp3) {
          var mp3 = _el('a', '⬇ MP3 audio', LINK_STYLE, {
            href: buildDownloadUrl(pageUrl, 'mp3'), target: '_blank', rel: 'noopener noreferrer'
          });
          list.appendChild(mp3);
        }
        if (!root.contains(openLink)) root.appendChild(openLink);
      });
    } catch (e) {
      done();
      showFallback('Could not load formats here. You can still open this video in QGrab:');
    }
  });

  root.appendChild(btn);
  root.appendChild(status);
  root.appendChild(list);
  root.appendChild(openLink);
  document.body.appendChild(root);
}

function boot() {
  if (typeof document === 'undefined' || typeof window === 'undefined') return;
  if (window.__qgrabBooted) return;
  window.__qgrabBooted = true;

  function tryRender() { renderPanel(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tryRender, { once: true });
  } else {
    tryRender();
  }

  // YouTube and Facebook are SPAs — the URL changes without a reload.
  // Re-check on navigation / history changes and periodically (cheap:
  // renderPanel() is a no-op when the panel already exists / not needed).
  var lastHref = window.location.href;
  function onMaybeNavigate() {
    if (window.location.href !== lastHref) {
      lastHref = window.location.href;
      var old = document.getElementById(PANEL_ID);
      if (old) old.remove();
      tryRender();
    }
  }
  window.addEventListener('popstate', onMaybeNavigate);
  window.addEventListener('yt-navigate-finish', onMaybeNavigate);
  setInterval(onMaybeNavigate, 1500);
}

/* ------------------------------------------------------------------ */
/* Exports + boot guard                                                */
/* ------------------------------------------------------------------ */

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    QGRAB_ORIGIN: QGRAB_ORIGIN,
    qgrabPageVideoUrl: qgrabPageVideoUrl,
    buildDownloadUrl: buildDownloadUrl,
    buildOpenUrl: buildOpenUrl,
    isSupportedVideoPage: isSupportedVideoPage
  };
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') {
  boot();
}
