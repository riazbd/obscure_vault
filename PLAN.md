# OBSCURA VAULT — Autonomous YouTube Engine
## Master Plan: From Manual Pipeline → Self-Driving Channel

> Target: a 24/7, fully-autonomous YouTube engine running on a Lenovo T480
> (i5-7300U, 8 GB RAM, no GPU, 256 GB SSD), with **zero paid services**.
> Only free APIs, free tiers, and free local tooling. OpenRouter free models
> are the LLM backbone.

---

## 0. TL;DR — What This Plan Delivers

A modular, idempotent, queue-driven pipeline that, given only a *channel concept*,
will:

1. **Mine ideas** continuously from free trend sources.
2. **Score and rank** each idea for SEO viability + audience fit.
3. **Research** each idea by scraping public sources and summarising.
4. **Write** a long-form script with hook → retention curve → CTA structure.
5. **Generate SEO assets** — title (CTR-optimised), description (keyword-dense), tags, chapters, hashtags, end-screen text.
6. **Produce voiceover** with Edge TTS (free) or Piper TTS (offline).
7. **Compose visuals** by *semantic* B-roll matching per script chunk + Ken Burns + colour grade.
8. **Generate a real thumbnail** using a free image-gen API (Pollinations / Cloudflare Flux free / HF Spaces) + PIL composition with face/contrast checks.
9. **Burn in captions** generated locally by `whisper.cpp` (CPU, ~1 GB RAM).
10. **Render** with FFmpeg in tiers (preview → final).
11. **QA** automatically (silence, audio LUFS, duration drift, NSFW filter, copyright sanity).
12. **Upload** via YouTube Data API v3 (free quota), schedule, A/B thumbnail.
13. **Learn** from YouTube Analytics → feed CTR/AVD back into the idea ranker.

Everything runs from a single Flask UI + a background worker. State lives in
SQLite. No Docker, no cloud, no recurring fees.

---

## 1. Current State Audit (what already works)

| File | Role | Status |
|---|---|---|
| `pipeline_core.py` | TTS → Pexels → FFmpeg assemble → PIL thumbnail → metadata | ✅ Works, manual title+script |
| `server.py` | Flask backend + UI APIs | ✅ Works |
| `ui/index.html` | Single-file dark UI | ✅ Works |
| `config.py` / `config.json` | Static config | ✅ Works |
| `start.py` | Bootstrapper | ✅ Works |

**Gaps for full autonomy** (this plan fills all of these):

- ❌ No idea generation
- ❌ No research/source aggregation
- ❌ No script generation (user pastes scripts in)
- ❌ Thumbnail is text-on-blurred-frame — no real composition, no face, low CTR potential
- ❌ Title/description are static templates, not SEO-optimised per topic
- ❌ No captions / subtitle burn-in (huge AVD lift)
- ❌ B-roll keywords are crude `if "war" in title` substring matching, not semantic and not per-segment
- ❌ No YouTube upload, no scheduling, no analytics loop
- ❌ No queueing — one job at a time, blocking
- ❌ No QA gate — bad outputs ship
- ❌ No persistent job DB — only filesystem

---

## 2. Hardware & Budget Reality Check

### T480 budget (4 cores / 8 threads, no GPU, 8 GB RAM, ~200 GB usable SSD)

| Workload | Feasible locally? | Decision |
|---|---|---|
| Edge TTS | ✅ trivial CPU | **Keep** |
| Piper TTS (offline) | ✅ ~50 MB RAM | **Add as fallback** |
| Whisper.cpp `base.en` Q5 | ✅ ~600 MB, ~3× realtime on CPU | **Add for captions** |
| FFmpeg x264 1080p `medium` preset | ✅ ~5–10 min per minute of video | **Keep, tune presets** |
| Stable Diffusion locally | ❌ no GPU, 8 GB RAM | **Reject — use free APIs** |
| Local 7B LLM (llama.cpp Q4) | ⚠️ slow, ~3–5 tok/s, eats RAM | **Optional offline fallback** only |
| Cloud LLM via OpenRouter free tier | ✅ near-zero cost | **Primary** |
| Cloud image gen via Pollinations / Cloudflare / HF | ✅ free | **Primary thumbnail source** |

### RAM budget while a render is running
- FFmpeg x264 1080p: ~700 MB
- Python pipeline + Pillow: ~250 MB
- Whisper.cpp base: ~600 MB
- OS + browser closed: ~2.5 GB
- Headroom: ~3 GB → safe. **Never run two renders concurrently on this box.**

### SSD budget
- One finished 1080p video: ~1 GB
- Workspace per job (raw clips + processed + concat): ~3–5 GB
- **Hard rule: cleanup after every successful upload.** Keep only final MP4 + thumbnail + metadata. Cap output dir at 50 GB; auto-archive older items to a USB/HDD when over.

---

## 3. Free Resource Inventory (the entire free stack)

### LLMs (via OpenRouter free tier)
Primary: **DeepSeek V3 0324 free**, **Llama 3.3 70B Instruct free**, **Qwen 2.5 72B free**, **Gemini 2.0 Flash Experimental free**, **Mistral Small free**.
Strategy: cascade — cheaper/faster model first, escalate on low-quality output (judged by a rubric).
*Always assume rate limits — implement retry/backoff and key rotation.*

### Image generation (thumbnail backgrounds)
1. **Pollinations.ai** — `https://image.pollinations.ai/prompt/{prompt}` — no key, free, slow but reliable.
2. **Cloudflare Workers AI free tier** — 10k neurons/day; includes `@cf/black-forest-labs/flux-1-schnell` (excellent quality).
3. **Hugging Face Inference API free** — rate-limited; SDXL / Flux Schnell available.
4. **Together.ai free credits** (one-time but useful).
   *Always have ≥2 providers wired with fallback.*

### Footage
- **Pexels** (already wired) — free key
- **Pixabay video** — free key
- **Coverr.co** — free, no key
- **Wikimedia Commons** — public-domain HD clips
- **Internet Archive** (archive.org) — public-domain documentary footage
- **Videvo free tier**
- **NASA media library** — public-domain space/science

### Music
- **Pixabay Music** API
- **Free Music Archive** (CC0 filter)
- **Incompetech** (Kevin MacLeod CC-BY)
- **YouTube Audio Library** — manual download, store in `/music`

### Sound FX
- **Freesound.org** API (free, attribution sometimes)
- **Pixabay SFX**

### Trend / idea sources
- **Google Trends** via `pytrends` (unofficial but free)
- **YouTube search suggest** endpoint (`https://suggestqueries.google.com/complete/search?client=youtube&ds=yt&q=…`) — free, no key
- **Reddit** `.json` endpoints — no key, just User-Agent
- **Wikipedia** "On this day", "Did you know", random article API
- **RSS** of niche sites (history blogs, declassified-doc trackers)
- **HackerNews / ProductHunt** for tech niches

### SEO research
- **YouTube Data API v3** free quota (10k units/day) — search, video stats, comments
- **Google Suggest** — free
- **Wikipedia internal-link analysis** for entity expansion
- **`textstat`** library for readability

### Captions
- **whisper.cpp** with `ggml-base.en-q5_1.bin` (~60 MB)

### Upload
- **YouTube Data API v3** — free, OAuth2 (one-time install consent), 10k units/day
  Upload = 1600 units → ~6 uploads/day max. Ample.

### Analytics
- **YouTube Analytics API** + **YouTube Reporting API** — free

### Vector / similarity
- **`sentence-transformers/all-MiniLM-L6-v2`** (90 MB, CPU friendly) — for semantic B-roll matching, dedup, and idea-novelty checks.

---

## 4. Target Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       Flask UI  (existing)                       │
│  Dashboard │ Ideas │ Queue │ Library │ Settings │ Analytics      │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Orchestrator  (new)                           │
│  - Reads jobs from SQLite queue                                  │
│  - Dispatches to stage workers                                   │
│  - Persists per-stage artifacts                                  │
│  - Idempotent: re-running a job resumes at last good stage       │
└──────────────────────────────────────────────────────────────────┘
        │
        ├──► IdeaEngine        (cron: every 6h)
        ├──► ResearchEngine    (per idea)
        ├──► ScriptEngine      (LLM cascade)
        ├──► SEOEngine         (title/desc/tags/chapters)
        ├──► VoiceEngine       (Edge TTS / Piper)
        ├──► VisualEngine      (semantic B-roll + Ken Burns)
        ├──► ThumbnailEngine   (image-gen + PIL composition)
        ├──► CaptionEngine     (whisper.cpp + .ass burn-in)
        ├──► AssemblyEngine    (FFmpeg)
        ├──► QAEngine          (silence/LUFS/duration/contrast/face check)
        ├──► UploadEngine      (YT Data API v3)
        └──► AnalyticsEngine   (YT Analytics → feedback to IdeaEngine)
```

Storage layout:
```
data/
  obscura.db          # SQLite — single source of truth
  cache/
    llm/              # prompt-hash → response
    images/           # url-hash → bytes
    footage/          # query+id → mp4
    embeddings/       # parquet of script-chunk embeddings
  models/
    whisper-base.bin
    piper-voices/
    minilm/
output/               # final MP4 + thumb + metadata.json + caption.srt
workspace/<job_id>/   # ephemeral; deleted after upload
```

`obscura.db` tables: `ideas`, `jobs`, `stages`, `assets`, `uploads`,
`metrics_daily`, `cache_index`, `prompts`, `experiments`.

---

## 5. Module Specs

### 5.1 IdeaEngine
**Inputs:** channel niche profile (concept, banned topics, target persona).
**Sources (run in parallel, dedup by embedding similarity):**
- YouTube search suggest expanding from seed terms.
- Google Trends rising queries (filtered by niche).
- Reddit hot+rising in target subs (e.g. `r/AskHistorians`, `r/UnresolvedMysteries`, `r/declassified`).
- Wikipedia random + "On this day" filtered by niche keywords.
- Top-10 channels in niche (resolve via YT search by handle list) → list their last 30 videos → cluster titles.

**Scoring** (weighted sum, all 0–1 normalised):
- `search_demand` (YT autosuggest depth + Trends slope)
- `competition_gap` (1 − avg view-count of top 5 results / channel-avg-views)
- `recency_relevance` (anniversary-aware bump)
- `evergreen` (low decay)
- `novelty` (1 − max cosine similarity to last 200 produced ideas)
- `niche_fit` (LLM rubric, 0–1)

Top-N writes to `ideas` table with `status=pending`. UI surfaces these for human approval (toggleable to fully auto).

### 5.2 ResearchEngine
For an approved idea:
- LLM expands to 8–15 research questions.
- For each question: Wikipedia article + 3 top web results (DuckDuckGo HTML, no key) + Internet Archive.
- HTML→text via `trafilatura` (lightweight, CPU).
- LLM extracts atomic facts (`{claim, source_url, confidence}`).
- Dedup via embeddings; reject low-confidence claims.
- Output: a `research_pack.json` with grouped, cited facts.

**Hallucination guard:** every claim in the final script must trace to a research-pack id, or it's flagged. Soft enforcement via post-script verifier prompt; hard enforcement via sentence-level NLI when affordable.

### 5.3 ScriptEngine
Two-pass:
1. **Outline pass** — LLM produces beat sheet: hook (≤15s), promise, 4–8 acts, payoff, CTA. Each act references research-pack ids.
2. **Draft pass** — LLM expands per-act, narrator voice, simple-words rule, sentences ≤22 words median, retention hooks at 25%/50%/75% (mini-cliffhangers), pattern interrupts every ~90s.

**Quality gates:**
- Word count within 5% of target (target derived from desired duration ÷ 2.4 wpm).
- `textstat.flesch_reading_ease` ≥ 65.
- No banned phrases (configurable list).
- No first-person hallucinated claims.

If gate fails twice, escalate to a stronger free model in the cascade.

### 5.4 SEOEngine
**Title:** generate 12 candidates, score each with rubric (curiosity gap, keyword presence, length 50–65 char, no clickbait clichés, emotional valence). Pick top scorer; keep next 2 for thumbnail A/B variants.

**Description:**
- First 150 chars = hook + primary keyword (above-the-fold on YT).
- Body: 2–3 paragraphs with semantic-keyword variants pulled from research pack.
- Auto-generated chapters from the script's act timestamps.
- Source links (boosts E-E-A-T signals on YT).
- Affiliate/social/sub CTA block (configurable).
- Hashtags (3 max, the rest go in tags).

**Tags:** combine: primary keyword, 5 long-tails from YT autosuggest, 5 entity tags from research pack, channel-brand tag. Cap at 500 char total.

**End-screen / Pinned-comment text** auto-generated.

### 5.5 VoiceEngine
- Edge TTS primary (already working). Add SSML pacing: pause after each act marker, mild pitch dip on "however/but", slight rate slowdown on key facts.
- Piper TTS as offline fallback (no network).
- Per-channel voice profile.
- Output: `voice.wav` 24 kHz mono, then loudness-normalised to **-16 LUFS** integrated, **-1.5 dBTP** ceiling (ffmpeg `loudnorm` two-pass).

### 5.6 VisualEngine (semantic B-roll)
**Big upgrade over current substring matching.**

1. Split script into ~6–10 second chunks aligned to forced-aligned word timestamps (whisper.cpp on the generated voice).
2. Embed each chunk with MiniLM.
3. For each chunk, generate 1–2 visual queries via the LLM (concrete, cinematographic — *"slow drone shot foggy gothic cathedral exterior dusk"* not *"church"*).
4. Multi-source search (Pexels + Pixabay + Coverr + Wikimedia) parallel.
5. Rank candidates by:
   - CLIP-free heuristic: filename/title token overlap with chunk keywords.
   - Aesthetic priors (prefer landscape, ≥1080p, ≥6 s, low motion if dialogue-heavy).
   - Diversity: penalise reuse of same source clip.
6. Download, cache, colour-grade once, reuse across jobs (huge bandwidth save).
7. **Ken Burns** auto pan/zoom on still imagery to add motion.
8. Cross-fades only on act boundaries; hard cuts within acts (better retention).

Fallbacks: dark-card frame, then animated noise + vignette.

### 5.7 ThumbnailEngine
Three-layer composition:

**Layer 1 — Background**
Generate via free image API (Pollinations primary, Cloudflare Flux fallback). Prompt is built from: niche style guide + 1–3 visual nouns from title + cinematography descriptors ("dramatic lighting, cinematic, 35mm, dark teal-orange grade"). Resolution 1280×720 directly.

**Layer 2 — Subject (optional)**
For history/mystery niche: composite a silhouette or a high-contrast object using rembg (CPU, ~200 MB, has `u2netp` lite model 4 MB). Skip if no subject.

**Layer 3 — Text & Branding**
- 2–4 word punchy thumbnail line (LLM-derived, *not* the full title).
- Big, bold, high-contrast (cream on dark, with red accent word).
- Stroke + drop shadow for readability.
- Channel logo bottom-right, 8% width.
- Optional curiosity element: red circle, arrow, "?" stamp.

**Auto-QA on the thumbnail before accepting:**
- Average luminance ≤ 0.55 (we're a dark-history channel).
- Text contrast ratio ≥ 7:1.
- At 320×180 preview size, OCR (`tesseract`) must still read the text.
- No banned visual content (basic NSFW filter via `opennsfw` ONNX, ~25 MB).

If any fail → regenerate with adjusted prompt.

**A/B**: produce 3 thumbnails, ship the top-1 to YouTube, store the others for YouTube's native thumbnail test (free).

### 5.8 CaptionEngine
- whisper.cpp on the produced voiceover — fast and accurate, since input is clean TTS.
- Output `.srt` and `.ass` (styled).
- Burn-in style: bottom-third, semi-transparent black box, 2 lines max, ≤32 chars/line, ≥48 px font, white with slight yellow on emphasised words. Big AVD lift.
- Also upload `.srt` as a real caption track on YouTube.

### 5.9 AssemblyEngine
Two render tiers:
1. **Preview** — 720p, x264 `veryfast`, CRF 26, no captions. ~1× realtime on T480. Used for QA gate.
2. **Final** — 1080p, x264 `medium`, CRF 20, captions burned, audio normalised, `-movflags +faststart`.

Always single-pass concat with pre-processed clips so we don't re-encode 30 GB. Aim for **≤ 3× realtime on the T480** (10-min video → ≤ 30 min render).

### 5.10 QAEngine (auto gate before upload)
Block upload if any:
- Audio: silent gaps > 3 s, integrated LUFS not in [−17, −15], peak > −1 dBTP.
- Duration: not within 3% of target.
- Video: black-frame run > 1.5 s detected via `blackdetect`.
- Thumbnail: failed contrast/OCR/NSFW checks above.
- Caption desync > 600 ms (compare alignment to script).
- Description over 5000 chars; tags over 500 chars.
- Title 50–65 chars (warn outside).

Failures route back to the relevant engine for one auto-retry, then human notification.

### 5.11 UploadEngine
- YouTube Data API v3 OAuth installed app flow (one-time consent).
- Upload as **private**, set scheduled publish time, attach thumbnail, captions, chapters, tags, end-screen template, playlist add.
- Schedule per channel cadence (e.g. Mon/Wed/Fri 18:00 local).
- Mark `status=scheduled` and store `videoId`.

### 5.12 AnalyticsEngine (the closing of the loop)
Daily cron pulls:
- CTR, AVD, retention curve, watch time, subs gained, traffic sources.
- Per-video, store in `metrics_daily`.

Feeds back into IdeaEngine:
- Winning topics → boost similar embeddings in next batch.
- Losing topics → suppress.
- Bad CTR + good AVD → topic was right, thumbnail/title wrong → re-generate thumbnail variant for swap-in.
- Bad AVD → script structure issue → adjust ScriptEngine prompts (longer hook, more cliffhangers, etc.).

A weekly self-report (markdown, generated by LLM) summarises what worked.

### 5.13 Orchestrator
- SQLite-backed work queue (`jobs`, `stages` tables).
- Single-worker by default (T480 can't safely parallelise renders).
- Idempotency: each stage writes a marker file + DB row. Re-running picks up where it left off.
- Crash recovery: on start, scan `running` jobs, mark stale, requeue.
- Backoff for any 429/5xx from external APIs; rotate keys.

---

## 6. OpenRouter Free-Model Cascade

Wrap all LLM calls through one client with:
- **Model cascade** per task type:
  - `script.outline` → DeepSeek V3 free → Llama 3.3 70B free → Qwen 2.5 72B free
  - `script.draft` → DeepSeek V3 free (best long-form) → Llama 3.3 70B free
  - `seo.titles` → Gemini 2.0 Flash exp free (creative) → Mistral Small free
  - `seo.tags` → Mistral Small free (cheap, structured)
  - `research.extract` → Llama 3.3 70B free
  - `qa.judge` → Qwen 2.5 72B free
- **Caching** by `sha256(prompt + model + temp)`.
- **Rate-limit handling**: per-minute and per-day windows tracked in DB; if blocked, fall to next model.
- **JSON mode**: enforce via response schema + retry-on-parse-fail (max 2 retries with feedback).
- **Logging**: every call (model, latency, tokens, success) → `prompts` table for cost/quality analytics.

---

## 7. Phased Roadmap (incremental, each phase ships value)

### Phase 1 — Foundation (Week 1)
- [ ] Add SQLite + Alembic-free migration script.
- [ ] Add `llm.py` OpenRouter client with cascade + cache.
- [ ] Add `cache.py` content-hash cache layer.
- [ ] Refactor `pipeline_core.py` into stage modules.
- [ ] UI: add Queue tab.

### Phase 2 — Script + SEO autonomy (Week 2)
- [ ] ResearchEngine v0 (Wikipedia + DDG + trafilatura).
- [ ] ScriptEngine outline → draft with quality gates.
- [ ] SEOEngine title/desc/tags/chapters.
- [ ] UI: paste *idea only*, get full script + SEO.

### Phase 3 — Visual upgrade (Week 3)
- [ ] Whisper.cpp install + word-level timestamps on voiceover.
- [ ] VisualEngine semantic chunk → query → multi-source search.
- [ ] Ken Burns for stills.
- [ ] Caption burn-in.

### Phase 4 — Thumbnail v2 (Week 4)
- [ ] Pollinations + Cloudflare Flux clients with fallback.
- [ ] PIL three-layer composition.
- [ ] rembg subject extraction (optional).
- [ ] Auto-QA + regen loop.
- [ ] Generate 3 variants per video.

### Phase 5 — Idea engine (Week 5)
- [ ] YT suggest + Trends + Reddit + Wikipedia harvesters.
- [ ] Embedding-based dedup.
- [ ] Scoring + ranker.
- [ ] UI: Ideas tab with approve/reject; toggle full-auto.

### Phase 6 — Upload + scheduling (Week 6)
- [ ] YouTube OAuth installed-app flow.
- [ ] UploadEngine.
- [ ] Cadence scheduler.
- [ ] QAEngine gate.

### Phase 7 — Analytics loop (Week 7)
- [ ] Daily metrics pull.
- [ ] Topic-performance feedback into IdeaEngine.
- [ ] Auto thumbnail-swap on poor CTR.
- [ ] Weekly self-report.

### Phase 8 — Polish & scale (Week 8+)
- [ ] Multi-channel profiles (one DB, channel column).
- [ ] Shorts pipeline (vertical, 30–60 s, hook-only).
- [ ] Voice variants per channel.
- [ ] Auto-archive old jobs to external drive.
- [ ] Dark-mode UI dashboard charts.

Each phase is independently shippable — you can pause anywhere and still have a meaningfully better system.

---

## 8. Performance Budget (T480, 10-min final video)

| Stage | Target wall-time |
|---|---|
| Idea select | 0 s (pre-generated) |
| Research | 1–3 min |
| Script (LLM) | 1–2 min |
| SEO | 30 s |
| Voiceover (Edge TTS) | 30 s |
| Captions (whisper.cpp base) | ~3 min |
| Footage fetch (cached repo) | 1–4 min |
| Visual processing + Ken Burns | 6–10 min |
| Thumbnail (gen + compose + QA) | 1–2 min |
| Final assemble (1080p) | 8–12 min |
| QA gate | 30 s |
| Upload | 2–4 min (your bandwidth) |
| **Total** | **~25–40 min per video** |

Comfortably one finished video per ~45 min of wall-time, fully unattended.
3 videos/day per channel without breaking a sweat.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| OpenRouter free model deprecation | Cascade across ≥3 models; allow user to plug in any new free model in UI |
| Pollinations / CF Flux outage | At least 2 image-gen providers always wired |
| YT API quota exhaustion | One upload = 1600 units; monitor in DB; throttle |
| Copyright strike from music/footage | Whitelist sources; hash-check against Content ID known list (best-effort); always credit |
| Hallucinated facts | Research-pack citation requirement + post-script verifier |
| Pipeline crash mid-render | Stage idempotency + resume from last marker |
| SSD fills up | Hard 50 GB cap, auto-archive, aggressive workspace cleanup post-upload |
| AI-content disclosure | YouTube requires disclosure of altered/synthetic content — set `containsSyntheticMedia=true` in upload |
| Channel monotony | Vary act structure templates; rotate hooks; randomised pacing |
| Account ban for spammy automation | Cap to ≤3 uploads/day/channel, vary times ±20 min, never duplicate titles |

---

## 10. Success Metrics (track in dashboard)

- Videos shipped/week
- Avg CTR (target ≥ 6%)
- Avg AVD (target ≥ 50%)
- Subs gained / video
- Cost per video (should remain $0)
- Pipeline failure rate (target < 5% of jobs)
- Avg wall-time per video
- LLM cache-hit rate (target ≥ 30% — saves rate-limit budget)

---

## 11. Open Decisions (please confirm before Phase 1)

1. **Channel scope** — stick with Obscura Vault (dark history) only, or design schema for multi-channel from day one? (recommend multi-channel schema, single-channel data initially.)
2. **Auto-publish vs review-first** — default to *review-first* in UI, with a per-channel toggle to flip to full auto once you trust it.
3. **Captions burn-in** — burn AND upload .srt (recommended), or just upload .srt (preserves user toggle)?
4. **Voice per channel** — one fixed voice, or rotate among 2–3 to reduce monotony?
5. **Shorts** — in scope for Phase 8, or skip entirely?
6. **External archive drive** — confirm one is available so SSD doesn't fill.

---

## 12. Why This Beats Off-the-Shelf "AI YouTube" Tools

- **$0 forever** — every paid tool charges per video or per minute.
- **Full control** — your prompts, your style, your voice, your data.
- **Compounding moat** — the cache + analytics loop means each video makes the next one cheaper and better.
- **No vendor lock-in** — every external service is replaceable in one file.
- **Runs on the laptop you already own.**

---

*Plan committed on branch `claude/video-automation-planning-bWaaT`. Implementation
follows phase-by-phase; nothing here is built yet — this document is the
blueprint and the contract.*
