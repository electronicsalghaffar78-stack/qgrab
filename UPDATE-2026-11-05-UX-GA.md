# QGrab Update — 2026-11-05 (UX + Google Analytics)

Qudoos ke hukm par do tabdeeliyan, ek hi deploy (commit 8536935, Render par live 2026-11-05 13:17 PKT):

## 1. Script/Prompt — timer khatam, popup message
- Script/Prompt ke waiting display se countdown/timer **bilkul hata diya** (button par sirf "Please wait" rehta hai, koi m:ss nahi).
- Job asal me shuru hote hi (server 202 accept kare to) ek chhota **toast/popup** aata hai: "This will take about 2–3 minutes — please wait, your result is being prepared." — ~5 second me **khud gayab** ho jata hai. Text i18n key `sp_wait_note` se aata hai (saari 30 zubanain).
- Ghalti (error/daily limit) par toast nahi aata. Baqi async flow bilkul waisa hi (polling, resume, counters, refund).
- Files: `templates/_spjs.html`, `templates/_sptool.html`, `templates/_extras.html`, `i18n.py`, test update `tests/test_sp_jobs_js.js`.

## 2. Google Analytics 4 (owner-only stats)
- GA4 property "QGrab" **electronics account** (AI Control Social) par bani. Measurement ID: **G-JM9C078ZNW**. Timezone Pakistan, currency PKR.
- Tag site ke tamam pages par: `templates/_themehead.html` (shared head) me gtag snippet + `window.qgEvent()` helper (guarded — GA block ho to bhi site ki koi feature nahi rukti).
- Custom events: `download_start` (asli download shuru hone par, platform parameter ke saath — index.html + platform.html), `script_generated` aur `prompt_generated` (sirf asli completion par — click/error/resume-redisplay par nahi).
- Dashboard: analytics.google.com, sirf electronics account se khulta hai. Data aana shuru hone me Google ke mutabiq 24–48 ghante lag sakte hain.
- Files: `templates/_themehead.html`, `templates/index.html`, `templates/platform.html`, `templates/_spjs.html`.

## Tests
- Dono changes ke baad tamam suites PASS (Python 9/9, JS 3/3) + live static check: GA ID, toast, events mojood; purane timer functions (spFmtTime/spSharpenFromInfo) gayab.

## Fix round — 2026-11-05 dopehar (commit 9b72a9c, live 13:35 PKT)
Pehle live test (13:19–13:26 PKT) me do masle mile, dono theek kiye:
1. **Toast live par nazar nahi aaya** — root cause: `app.py` ki `_js_strings()` whitelist me `sp_wait_note` key shaamil hi nahi thi, is liye page ke I18N me key gayab thi aur `spShowToast()` ka guard har click par khamoshi se ruk jata tha. Fix: whitelist me ek line add. Naya regression test `tests/test_sp_jobs.py::test_sp_i18n_keys_reach_the_page` — _spjs.html ke tamam I18N keys ka page tak pohanchna assert karta hai (ye test purane code par fail hota tha).
2. **Prompts ai_unavailable** — Render logs se saboot: Gemini first model (gemini-3.8-flash) us waqt HTTP 503 (Google ki taraf se overload) + ek TimeoutError de raha tha; text routes ka slow-mode cap sirf **2 attempts** tha, is liye job doosre models tak pohanchne se pehle mar jata tha. Fix: naya `SP_TEXT_SLOW_MAX_ATTEMPTS = 6` — text routes (script + prompts) ab slow failures par 6 attempts tak cascade chalti hain (audio route pehle se 6 par tha, unchanged). Tamam suites PASS (Python 116 tests, JS 3/3).

## Install App button — 2026-11-05 shaam (commit bbfdc8a, live 17:59 PKT)
Qudoos ki shikayat: naye phone visitors ko install ka option nazar nahi aata tha. PWA setup (manifest, icons 192/512/maskable, service worker) pehle se mukammal tha — masla sirf ye tha ke Chrome ab khud install banner nahi dikhata aur site ke paas apna button nahi tha. Ab:
- Site ke **header me "Install App" button** (homepage, 4 platform pages, Script+Prompt page) — naye fragments `templates/_installbtn.html` + `templates/_installjs.html`.
- Android/Chrome par click se asal install dialog khulta hai (`beforeinstallprompt` capture); iPhone par Share → "Add to Home Screen" ka hint, baqi browsers par menu wala hint (neeche pill, 6s me khud gayab).
- App pehle se installed ho to button khud chhup jata hai. Text i18n keys `install_app`, `install_hint_ios`, `install_hint_menu` — saari 30 zubanain + `_js_strings()` whitelist + regression test (`tests/test_install_button.py`). Suites: Python 10/10, JS 3/3 PASS; live par button teeno qisam ke pages par verified.

## Language-switch fix — 2026-11-05 shaam (commit 36b26f1, Render deploy dep-dbm8433bc2fs738j89l0, live ~18:18 PKT)
Qudoos ki shikayat: ek dafa Urdu select karne ke baad site English par wapas nahi aati thi, kitni hi dafa try kiya.
- **Root cause:** `app.py` ka `lang_url("en")` bare path (`/`) return karta tha — English ke menu link me `?lang=en` hota hi nahi tha. Is liye `_current_lang()` hamesha purani `qgrab_lang` cookie (Urdu, 1 saal ke liye set) par girta tha aur English kabhi dobara select hi nahi ho sakti thi.
- **Fix:** ab har language-menu link `?lang=<code>` carry karta hai, English samet — click par sahi zuban render hoti hai aur `_persist_lang` cookie bhi usi zuban se update ho jati hai. Hreflang/canonical handling bilkul unchanged.
- **Tests:** nayi suite `tests/test_lang_switch.py`; tamam suites PASS.
- **Live-verified:** Urdu cookie ke saath `/?lang=en` English render karta hai + `Set-Cookie: qgrab_lang=en` aata hai; page ke menu me English ka link `/?lang=en` hai. Baqi zubanon ka cookie-only raasta bhi bilkul waisa hi chalta hai.

## Keep-warm — Render wake page ka free jugaad — 2026-11-05 shaam (commit c83886c, live ~18:23 PKT)
Qudoos paid plan par raazi nahi hue (free hi rahega), lekin Render ki soi hui service ke jaagne wala kaala page ("APPLICATION LOADING / SERVICE WAKING UP") naye visitors ko dara deta tha — unhe lagta tha device hack ho gaya. Hal:
- Repo me GitHub Actions workflow `.github/workflows/keep-warm.yml`: har **10 minute** par `https://qgrab.onrender.com/healthz` ko ping karta hai, taake free service 15-minute idle spin-down tak kabhi pohanchti hi nahi — site hamesha jaagi rehti hai aur visitors ko wake page nahi dikhta.
- Workflow **GitHub web UI se add kiya gaya**, kyunke push integration ke paas workflows permission nahi (403 "Resource not accessible by integration") — aayenda workflow files hamesha isi tarah add hongi.
- **Pehla manual run kamyab** — 11 second me mukammal.
- **Sakht had (lazmi yaad rahe):** Render free = **750 instance-hours/month per workspace**. Ek hamesha-jaagi service 31-din wale mahine me zyada se zyada **744 ghante** leti hai — is liye is account par **koi doosri free service kabhi add nahi hogi**, warna ghante khatam hote hi tamam free services mahine ke aakhir tak suspend ho jayengi.

## Install-guide fix — 2026-11-05 raat (commits a5ffc1c + fcc6982, Render deploy dep-dbm9d00u01pc738p2po0, live ~19:46 PKT)
Qudoos ki shikayat: log Install App button dabate hain lekin app install nahi hoti — home screen par icon hi nahi aata.
- **Root cause:** Chrome naye / kam-engagement wale visitors ko `beforeinstallprompt` (asal install dialog) deta hi nahi — unke paas button ka sirf wohi **6-second wala hint pill** tha, jo parhne se pehle gayab ho jata tha, is liye koi install mukammal kar hi nahi pata tha aur home screen par icon kabhi aata hi nahi tha. PWA setup (manifest, icons, service worker) pehle se theek tha; masla sirf fallback raaste ka tha.
- **Fix:** hint pill hata kar ek **persistent install-guide bottom sheet** laga di — `role="dialog"`, × close button, backdrop ya Esc se band, **koi timer nahi** (khud gayab nahi hoti). Android/Chrome ke qadam: browser menu (⋮) → «Install app» ya «Add to Home screen» → icon home screen par aa jata hai. iPhone ke liye alag Share-wale qadam. Tamam **30 zubanon** me — 7 nayi i18n keys.
- Jo visitors engaged hain (Chrome unhe asal prompt deta hai), unke liye **native prompt wala raasta bilkul unchanged** hai.
- **Manifest** me `categories` + **2 screenshots** add hue (`static/screenshots/` — narrow + wide) taake Chrome ka richer install dialog poora bane. Screenshots **GitHub web UI se upload** hue, kyunke push tool binary files reject karta hai — code wala commit (a5ffc1c) aam raaste se gaya, screenshots wala (fcc6982) web UI se.
- **Live-verified:** homepage par sheet ka markup + qadam wala text mojood, purana hint pill gayab, manifest aur dono screenshots 200 OK de rahe hain.

## Install-sheet position fix — 2026-11-05 raat (commit f37aacb, Render deploy dep-dbm9nnk9v7es7399g190, live ~20:08 PKT)
Install-guide sheet live hone ke baad Qudoos ke phone ki photo aur live browser repro — dono me sheet ghalat jagah khulti mili: neeche se ubharne ke bajaye screen ke **upar atak** jati thi, sirf step 3 ki aakhri line dikhti thi.
- **Root cause:** sticky `<header>` par laga `backdrop-filter: blur(8px)` (index.html / platform.html / scriptprompt.html) fixed-position wale child elements ke liye **containing block** bana deta hai. Backdrop ka markup header ke andar rehta hai, is liye us ka `position:fixed` poori screen ke bajaye sirf ~58px wali header strip ke hisaab se resolve hota tha — sheet upar clip ho gayi, title, × button aur steps 1–2 screen se bahar.
- **Fix:** `templates/_installjs.html` init par — event wiring se pehle — backdrop element ko utha kar `document.body` ke aakhir me laga deta hai (`document.body.appendChild(backdrop)`), taake fixed positioning hamesha viewport ke hisaab se ho, header ke asar se bilkul bahar. Baqi sheet/native-prompt logic unchanged.
- **Tests:** nayi Node suite `tests/test_install_sheet_js.js` + Python suite (`test_install_button.py`) — tamam suites PASS.
- **Live retest PASS:** sheet ab neeche se sahi ubharti hai, poori screen par dimming aati hai, title, × button aur teeno steps saaf dikhte hain, aur × se band bhi ho jati hai.
