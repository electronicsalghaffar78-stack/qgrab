'use strict';

/*
 * QGrab Downloader — background service worker (Manifest V3)
 *
 * The content script cannot always rely on the page origin being allowed
 * to call qgrab.onrender.com (CORS / mixed page policies), so format
 * lookup is centralised here. The worker has host_permissions for
 * https://qgrab.onrender.com/*.
 *
 * Message contract:
 *   in : { type: 'qgrab-info', url: '<canonical video page url>' }
 *   out: { ok: true,  title, formats: [{ id, label, kind, ext, size_h }], mp3, captions }
 *      | { ok: false, error: '<human readable message>' }
 *
 * QGrab API:
 *   POST https://qgrab.onrender.com/api/info  { url }
 *   -> { title, formats: [{ id, label, kind, ext, size_h, ... }], mp3, captions }
 */

var QGRAB_ORIGIN = 'https://qgrab.onrender.com';

function normalizeFormats(raw) {
  if (!Array.isArray(raw)) return [];
  var out = [];
  for (var i = 0; i < raw.length; i++) {
    var f = raw[i] || {};
    var id = f.id != null ? String(f.id) : (f.format_id != null ? String(f.format_id) : '');
    if (!id) continue;
    out.push({
      id: id,
      label: f.label || f.note || id,
      kind: f.kind || '',
      ext: f.ext || '',
      size_h: f.size_h || null,
      size: f.size != null ? f.size : null,
      height: f.height != null ? f.height : null,
      note: f.note || ''
    });
  }
  return out;
}

async function fetchQGrabInfo(url) {
  if (!url || typeof url !== 'string') {
    throw new Error('Missing video URL.');
  }
  var res = await fetch(QGRAB_ORIGIN + '/api/info', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify({ url: url })
  });
  var data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  if (!res.ok) {
    var msg = (data && data.error) ? String(data.error) : ('QGrab returned HTTP ' + res.status);
    throw new Error(msg);
  }
  if (!data) {
    throw new Error('QGrab returned an unreadable response.');
  }
  if (data.error) {
    throw new Error(String(data.error));
  }
  return {
    title: data.title || '',
    formats: normalizeFormats(data.formats),
    mp3: !!data.mp3,
    captions: Array.isArray(data.captions) ? data.captions : []
  };
}

// Guarded so `node --check` and a plain require() in tests do not crash
// when the chrome.* APIs are absent.
if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
    if (!message || message.type !== 'qgrab-info') {
      return false;
    }
    fetchQGrabInfo(message.url)
      .then(function (info) {
        sendResponse({
          ok: true,
          title: info.title,
          formats: info.formats,
          mp3: info.mp3,
          captions: info.captions
        });
      })
      .catch(function (err) {
        sendResponse({
          ok: false,
          error: (err && err.message) ? err.message : 'Could not fetch formats from QGrab.'
        });
      });
    // Keep the message channel open for the async reply.
    return true;
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    QGRAB_ORIGIN: QGRAB_ORIGIN,
    normalizeFormats: normalizeFormats,
    fetchQGrabInfo: fetchQGrabInfo
  };
}
