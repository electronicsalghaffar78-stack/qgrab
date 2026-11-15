# QGRAB FEATURE IDEA — "Video → Script + Prompt" (NOT BUILT — awaiting Qudoos's go-ahead from the main chat)
Noted: 2026-11-03 ~23:50 PKT (idea given by Qudoos in the MAIN chat; do NOT start building until the go-ahead arrives here. NO login/payment/API signup without his separate OK.)

## The idea
A featured tool on QGrab (top, above Popular Downloads): the user pastes a video link and instead of downloading the video, gets (1) the video's **script** — dialogue/narration in a clean readable format — and (2) **scene-by-scene AI-video-generation prompts** derived from it, so creators can make their own version. Qudoos's pitch: no other downloader offers this; it puts QGrab ahead, especially for creators.

## Honest feasibility (prepared, test-first — no promises made)
**Script part — EASY, substrate already live.** Subtitles/transcript download shipped and was verified today (a TED transcript came out at exactly 17,574 chars via both the yt-dlp cascade and the Invidious path). Turning that into a "script" = formatting only: timestamped lines, segmentation into scenes by caption time-gaps, cleaned punctuation. Limits: captions carry no speaker names (diarization is NOT possible from captions alone — lines can be time-coded, not reliably attributed); auto-captions garble names and Urdu — label output an "AI-cleaned draft".

**Videos WITHOUT captions:** yt-dlp cannot transcribe speech. Server-side Whisper on Render Free (512 MB RAM, weak CPU) is at best tiny-model on short clips — slow and unreliable; NOT a v1 promise. Honest v1 behaviour: a clear "is video ke subtitles nahi mile — script nahi ban sakti" message.

**Prompt part — needs an LLM API (none integrated yet).** Render Free can call external HTTPS APIs fine, and the payload is just transcript text, so bandwidth/compute on Render is trivial. Realistic routes, all requiring an account + API key (Qudoos's separate OK first):
- Google Gemini API free tier (AI Studio) — generous free text limits; paid Flash-class usage later costs only cents per long script.
- Groq free tier — fast, smaller daily token budget.
- OpenRouter free models / Cloudflare Workers AI free tier — alternates.
No-key scraping routes are fragile and ToS-grey — NOT recommended. Add per-IP soft rate limits against abuse; costs scale with usage, free tier plausibly covers launch traffic.

**Fit with Qudoos's own rules:** prompts must be written as scene descriptions for making an ORIGINAL version (his channels' originality rule), not frame-by-frame copying instructions; the personal-use disclaimer already on the site covers the transcript side (same as the shipped Transcript feature).

## If go-ahead arrives — test-first plan
1. ONE sample captioned YouTube video → produce script + prompts end-to-end (manual pipeline) → show Qudoos.
2. On his approval: build the page + API wiring (needs the API-key OK), i18n keys for all 30 languages, rate limits.
3. Ship via the usual flow: snapshot push (his approval tap) → Render deploy → live verify → refresh the backup ZIP.
