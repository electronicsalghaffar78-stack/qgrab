/* DOM-stub click-through for the Install App guide sheet script
   (_installjs.html), run against the exact code the Flask app
   serves on the homepage.

   Round-2 regression: live, clicking Install App opened the
   guide sheet clipped at the TOP of the viewport — only a ~50px
   sliver (the tail of step 3) visible, title / × / steps 1–2
   off-screen, dimming only over the header strip. Cause: the
   backdrop markup ships inside the sticky <header>, and the
   header's `backdrop-filter: blur(8px)` makes it the containing
   block for fixed-position descendants, so the backdrop's
   position:fixed; inset:0 resolved against the ~58px header box
   instead of the viewport. Fix: at init the script moves the
   backdrop to the end of <body>
   (document.body.appendChild(backdrop)) so fixed positioning
   anchors to the viewport again.

   This suite rebuilds the served nesting (backdrop inside
   header > nav, button beside it), runs the real script, and
   verifies:
     - after init the backdrop's parent is document.body, it is
       body's last child, and the header no longer contains it,
     - click opens the sheet with the platform's steps shown,
     - close button, backdrop self-tap and Escape close it, a
       tap on the sheet itself does not,
     - beforeinstallprompt still switches the button to the
       native prompt (sheet stays shut), appinstalled hides the
       button, and an iPhone UA gets the iOS steps.
   Run:  node tests/test_install_sheet_js.js */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const { execFileSync } = require('child_process');

/* ---------- extract the served install script ---------- */
const repoRoot = path.join(__dirname, '..');
const pyCandidates = [
  process.env.QGRAB_PYTHON,
  path.join(repoRoot, '.venv', 'bin', 'python'),
  path.join(repoRoot, '..', 'downloader-site', '.venv', 'bin', 'python'),
  'python3',
].filter(Boolean);
const py = pyCandidates.find((p) => p === 'python3' || fs.existsSync(p));
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qgrab-install-js-'));
const dump = `
import re, sys, os
sys.path.insert(0, ${JSON.stringify(repoRoot)})
os.environ.setdefault("QGRAB_DATA_DIR", ${JSON.stringify(outDir)})
import app as A
html = A.app.test_client().get("/").get_data(as_text=True)
with open(os.path.join(${JSON.stringify(outDir)}, "home.html"), "w") as fh:
    fh.write(html)
blocks = re.findall(r"<script(?![^>]*application/ld\\+json)([^>]*)>([\\s\\S]*?)</script>", html)
for attrs, body in blocks:
    if "src=" not in attrs and "installBackdrop" in body:
        with open(os.path.join(${JSON.stringify(outDir)}, "install.js"), "w") as fh:
            fh.write(body)
        break
`;
execFileSync(py, ['-c', dump], { encoding: 'utf8' });
const homeHtml = fs.readFileSync(path.join(outDir, 'home.html'), 'utf8');
const installJs = fs.readFileSync(path.join(outDir, 'install.js'), 'utf8');
assert.ok(installJs.includes('beforeinstallprompt'), 'install script extracted');
assert.ok(installJs.includes('document.body.appendChild(backdrop)'),
  'served install script carries the backdrop relocation');

/* The trap, as served: the backdrop markup sits INSIDE <header>
   (the sticky, backdrop-filtered ancestor) in the page HTML. */
const backdropAt = homeHtml.indexOf('id="installBackdrop"');
const headerEnd = homeHtml.indexOf('</header>');
assert.ok(backdropAt !== -1 && headerEnd !== -1 && backdropAt < headerEnd,
  'served backdrop markup starts inside <header>, as on the live site');

/* ---------------- DOM stub ---------------- */
class El {
  constructor(tag, id) {
    this.tagName = (tag || 'div').toUpperCase();
    this.id = id || '';
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.hidden = false;
  }
  appendChild(child) {
    if (child.parentNode) {
      const i = child.parentNode.children.indexOf(child);
      if (i !== -1) child.parentNode.children.splice(i, 1);
    }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  dispatch(type, event) {
    const e = event || {};
    if (e.target === undefined) e.target = this;
    (this.listeners[type] || []).slice().forEach((fn) => fn(e));
  }
  contains(node) {
    for (let n = node; n; n = n.parentNode) if (n === this) return true;
    return false;
  }
}

const ANDROID_UA = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) ' +
  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36';
const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) ' +
  'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';

function buildPage(userAgent) {
  /* Mirror the served nesting: the button and the backdrop (with
     the sheet and its children) live inside header > nav; a
     trailing page element proves the backdrop lands LAST in
     <body> after relocation. */
  const body = new El('body');
  const header = new El('header');
  const nav = new El('nav');
  const btn = new El('button', 'installBtn');
  const backdrop = new El('div', 'installBackdrop');
  backdrop.hidden = true;
  const sheet = new El('div', 'installSheet');
  const closeBtn = new El('button', 'installSheetClose');
  const stepsAndroid = new El('ol', 'installStepsAndroid');
  const stepsIos = new El('ol', 'installStepsIos');
  stepsIos.hidden = true;
  sheet.appendChild(closeBtn);
  sheet.appendChild(stepsAndroid);
  sheet.appendChild(stepsIos);
  backdrop.appendChild(sheet);
  nav.appendChild(btn);
  nav.appendChild(backdrop);
  header.appendChild(nav);
  const main = new El('main');
  body.appendChild(header);
  body.appendChild(main);

  const byId = {};
  [btn, backdrop, sheet, closeBtn, stepsAndroid, stepsIos]
    .forEach((el) => { byId[el.id] = el; });
  const document = new El('#document');
  document.body = body;
  document.getElementById = (id) => byId[id] || null;

  const windowListeners = {};
  const window = {
    navigator: {
      userAgent,
      platform: userAgent.includes('iPhone') ? 'iPhone' : 'Linux armv8l',
      maxTouchPoints: 5,
      standalone: undefined,
    },
    matchMedia: () => ({ matches: false }),
    addEventListener: (type, fn) => {
      (windowListeners[type] = windowListeners[type] || []).push(fn);
    },
    dispatch: (type, event) => {
      (windowListeners[type] || []).slice().forEach((fn) => fn(event));
    },
  };
  return { window, document, body, header, main, btn, backdrop, sheet,
           closeBtn, stepsAndroid, stepsIos };
}

function runScript(page) {
  const sandbox = { window: page.window, document: page.document, console };
  vm.createContext(sandbox);
  vm.runInContext(installJs, sandbox, { filename: 'install.js' });
}

/* ---------------- Android click-through ---------------- */
{
  const p = buildPage(ANDROID_UA);
  assert.strictEqual(p.backdrop.parentNode, p.header.children[0],
    'precondition: backdrop starts inside header > nav');
  runScript(p);

  /* the fix: relocated to the end of <body> at init */
  assert.strictEqual(p.backdrop.parentNode, p.document.body,
    'after init the backdrop parent is document.body');
  assert.strictEqual(p.body.children[p.body.children.length - 1], p.backdrop,
    'backdrop is the last child of <body>');
  assert.ok(!p.header.contains(p.backdrop),
    'header no longer contains the backdrop');
  assert.strictEqual(p.backdrop.hidden, true, 'sheet starts closed');

  /* click opens the sheet with the Android steps */
  p.btn.dispatch('click');
  assert.strictEqual(p.backdrop.hidden, false, 'click opens the sheet');
  assert.strictEqual(p.stepsAndroid.hidden, false, 'Android steps shown');
  assert.strictEqual(p.stepsIos.hidden, true, 'iOS steps stay hidden');

  /* a tap on the sheet itself does not close it */
  p.backdrop.dispatch('click', { target: p.sheet });
  assert.strictEqual(p.backdrop.hidden, false, 'sheet tap keeps it open');

  /* × button closes */
  p.closeBtn.dispatch('click');
  assert.strictEqual(p.backdrop.hidden, true, 'close button closes');

  /* backdrop self-tap closes */
  p.btn.dispatch('click');
  assert.strictEqual(p.backdrop.hidden, false, 'sheet reopens');
  p.backdrop.dispatch('click', { target: p.backdrop });
  assert.strictEqual(p.backdrop.hidden, true, 'backdrop tap closes');

  /* Escape closes */
  p.btn.dispatch('click');
  assert.strictEqual(p.backdrop.hidden, false, 'sheet reopens again');
  p.document.dispatch('keydown', { key: 'Escape' });
  assert.strictEqual(p.backdrop.hidden, true, 'Escape closes');

  /* native prompt path intact: beforeinstallprompt switches the
     button to prompt(), the sheet stays shut */
  let promptCalls = 0;
  p.window.dispatch('beforeinstallprompt', {
    preventDefault() {},
    prompt() { promptCalls += 1; },
    userChoice: Promise.resolve({ outcome: 'accepted' }),
  });
  p.btn.dispatch('click');
  assert.strictEqual(promptCalls, 1, 'native prompt fired from the button');
  assert.strictEqual(p.backdrop.hidden, true,
    'sheet stays shut when the native prompt is available');

  /* appinstalled hides the button */
  p.window.dispatch('appinstalled', {});
  assert.strictEqual(p.btn.hidden, true, 'appinstalled hides the button');
  console.log('  android: relocation + open/close + native prompt OK');
}

/* ---------------- iPhone click-through ---------------- */
{
  const p = buildPage(IPHONE_UA);
  runScript(p);
  assert.strictEqual(p.backdrop.parentNode, p.document.body,
    'iOS: backdrop relocated to <body> too');
  p.btn.dispatch('click');
  assert.strictEqual(p.backdrop.hidden, false, 'iOS: sheet opens');
  assert.strictEqual(p.stepsIos.hidden, false, 'iOS steps shown');
  assert.strictEqual(p.stepsAndroid.hidden, true, 'Android steps hidden');
  p.closeBtn.dispatch('click');
  assert.strictEqual(p.backdrop.hidden, true, 'iOS: close button closes');
  console.log('  iphone: relocation + iOS steps OK');
}

console.log('ALL INSTALL SHEET JS TESTS PASS');
