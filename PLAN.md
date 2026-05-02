# OBSCURA VAULT — Plan v3
### Current state + what remains

> v1 was a feature blueprint. v2 was an audit and a re-plan. v3 is what
> the system actually is today, with the honest list of what's
> outstanding.

---

## 0. What this is

A fully local, fully free YouTube engine for the Obscura Vault channel
(buried / dark / forgotten history). Built to run on a Lenovo T480
(i5-7300U, 8 GB RAM, no GPU, 256 GB SSD). No paid APIs, no recurring
bills. The only cloud calls are to free tiers of OpenRouter, Pexels,
and Pollinations.

Single Flask server (`server.py`), 16 engine modules, single-file
HTML/JS UI, SQLite for job history, JSON files for everything else.

---

## 1. Phase ledger (planned vs shipped)

### Phase 1 — Foundation
- ✅ `llm.py` — OpenRouter chat client with 5-model free-tier cascade,
  sha256 file cache, JSON extraction, per-model retry/backoff
- ✅ Project scaffolding (`engines/` package, `data/` directory, `.gitignore`)

### Phase 2 — Script + SEO
- ✅ `engines/script.py` — outline + draft pass, quality gates
  (word-count window, banned-pattern guard, sentence sanity)
- ✅ `engines/seo.py` — 12-candidate title scoring, SEO description with
  keyword pack, tag list capped at 480 chars, chapter timestamps
- ✅ `engines/research.py` — Wikipedia + DuckDuckGo HTML scrape, stdlib
  HTML→text, atomic-fact extraction with source URLs, token-Jaccard
  dedup, persisted research_packs
- ✅ Script engine consumes research packs, grounds claims to `[fX]` ids

### Phase 3 — Captions + B-roll
- ✅ `engines/captions.py` — `faster-whisper` lazy import, int8
  CPU-quantised transcription, word-level → 2-line cards, `.srt` and
  styled `.ass` outputs (long + shorts variants)
- ✅ FFmpeg subtitle burn-in via filter graph with `cwd=workspace`
- ✅ `engines/footage.py` — sentence-grouped script chunking,
  batched LLM cinematographic queries, Pexels + Pixabay search,
  per-chunk scoring (resolution, duration fit, query rank, reuse),
  download + colour-grade + concat

### Phase 4 — AI thumbnail
- ✅ `engines/thumbnail.py` — LLM punchline + LLM image prompt →
  Pollinations.ai background → PIL three-layer composition (vignette,
  accent bars, text slab + drop shadow + stroke), auto-darken to
  ≤0.40 luminance, vertical (1080×1920) and horizontal (1280×720) modes

### Phase 5 — Idea engine
- ✅ `engines/ideas.py` — keyless harvesters (YouTube Suggest letter
  expansion, Reddit `.json` listings, Wikipedia on-this-day), junk
  filter, token-Jaccard dedup, batched LLM niche scoring, ranked_score
  combining LLM + analytics signals
- ✅ Lifecycle: pending → approved → produced (or rejected)
- ✅ "Generate" button chains idea → script → SEO → render

### Phase 6 — Upload
- ✅ `engines/upload.py` — Google API client lazy import, OAuth
  installed-app loopback flow, resumable upload with transient retry,
  thumbnail + caption attachment, AI-disclosure flag, scheduled-publish
- ✅ Per-video manual upload + auto-upload toggle on every render
- ✅ Idea_id correlation: upload records the originating idea so
  analytics can later attribute performance

### Phase 7 — Analytics feedback loop
- ✅ `engines/analytics.py` — append-only upload registry, Data API
  v3 + Analytics v2 puller, token-level confidence-shrunk multipliers
  (0.5–1.6), `predict_score_for_idea()` for the harvester
- ✅ Idea engine applies signals → `ranked_score = niche_fit × multiplier`

### Phase 8 — Polish & scale (original v1 list)
- ✅ Shorts pipeline (`run_short_pipeline_thread`, vertical 1080×1920,
  hook-only narration, big captions, vertical thumbnail, `#Shorts` tagging)
- ✅ Cron scheduler (`engines/scheduler.py`) — 4 tasks: harvest,
  produce, refresh-analytics, storage-cleanup; per-task interval +
  state persistence; orphan-recovery on boot
- ✅ Dashboard with charts — 14-day stacked-bar pipeline activity,
  per-video horizontal-bar view counts, top/bottom token signals as
  proportional bars, storage-usage breakdown
- ✅ Voice variants — random rotation pool of Edge TTS voices per render
- ✅ Auto-archive — workspace cleanup post-render, configurable
  output cap (30 GB default), scheduler-driven N-day prune
- ❌ **Multi-channel profiles** — explicitly skipped per user request
  (single channel use case)

### Bonus phases (added beyond v1 plan)
- ✅ 8d Audio polish — voice loudnorm to −16 LUFS, sidechain music
  ducking 3–18 dB
- ✅ 8e Branding — 4 intro/outro slots (long + Shorts), upload-time
  normalization, stream-copy concat
- ✅ 8f Persistent jobs — SQLite-backed job history, Jobs tab UI,
  boot-time orphan recovery
- ✅ 8h Performance review — LLM scorecard for any video against
  channel baseline, 6-dimension rubric + 3 actionable improvements

### Reverted phases (never wanted)
- ↩ 8g Multi-language pipeline (revert `cd175f4`) — channel is English-only
- ↩ 8i Bulk auto-translate (revert `cfdb3d0`) — same reason

---

## 2. What's remaining

### Functionally — almost nothing.
The system is feature-complete to the original spec, plus four bonus
phases. The deliberate skip is multi-channel.

### Operationally — what hasn't actually been verified
- **No end-to-end run.** Every commit AST-parses; storage tested with
  synthetic data. Nothing has been executed with a real OpenRouter
  key, real FFmpeg binary, real Pexels footage, real Pollinations,
  real Whisper.cpp, real YouTube OAuth.
- **No tests.** Smoke tests have all been ad-hoc in chat output.
- **First-run UX is undocumented** beyond the README.

### Risks still ticking
1. **OpenRouter daily-quota cap.** The 5-model cascade silently falls
   to slower fallbacks; sustained scheduler runs will hit the cap.
   No tracker. Mitigation TBD.
2. **Pollinations rate-limits.** 3-retry backoff exists but no
   long-window throttling; bursty days may stall thumbnail generation.
3. **YouTube quota** = 10 000 units/day = ~6 uploads/day per project.
   Hard ceiling; no warning UI.
4. **Whisper-model first-download** is unverified. It downloads ~140 MB
   on first transcription; if it fails the pipeline silently skips
   captions.

These are documented but **not fixed**. Track-S work in plan v2
listed remediation; nothing has been done yet.

---

## 3. Codebase shape

```
obscure_vault/
├── PLAN.md                  this file
├── README.md                user manual (rewritten)
├── docs/                    per-engine docs (one .md per engine)
│   ├── llm.md
│   ├── script.md
│   ├── ... etc
├── llm.py                   OpenRouter client
├── server.py                Flask app + 2 pipeline threads + 50+ endpoints
├── start.py                 launcher
├── config.py / config.json  settings
├── requirements.txt         Pillow, edge-tts, requests, flask
├── engines/                 pipeline stages
│   ├── analytics.py
│   ├── branding.py
│   ├── captions.py
│   ├── footage.py
│   ├── ideas.py
│   ├── jobs.py
│   ├── research.py
│   ├── review.py
│   ├── scheduler.py
│   ├── script.py
│   ├── seo.py
│   ├── storage.py
│   ├── thumbnail.py
│   └── upload.py
├── ui/index.html            single-file Flask-served UI
├── data/                    state (JSON + SQLite)
│   ├── ideas.json
│   ├── uploads.json
│   ├── metrics.json
│   ├── scheduler.json
│   ├── jobs.db
│   ├── branding/<slot>.mp4
│   ├── research_packs/
│   ├── youtube/{client_secrets, token}.json
│   └── cache/
│       ├── llm/<sha>.json
│       ├── images/<sha>.png
│       └── research/<sha>.txt
├── workspace/               per-job intermediates (auto-cleaned)
├── output/                  finished MP4s + thumbnails + .srt
└── music/                   user-supplied background music
```

**Numbers:** 16 engines, ~5,800 lines Python, ~3,000 lines UI, ~50
endpoints, 4 dependencies (Pillow, edge-tts, requests, flask), 2
optional dependencies (faster-whisper for captions, google-api-python-client
for upload).

---

## 4. What you should do next

In order:

1. **Run it.** `python start.py` on the T480, paste your OpenRouter
   and Pexels keys, generate one test video at 5-min length with
   defaults. See what breaks.

2. **Fix what broke** — paste back the errors here, we patch.

3. **(optional) Address the risks** in §2.3: OpenRouter quota tracker,
   Pollinations long-window throttling, YouTube quota warning UI.

4. **(optional) Multi-channel** — only if Obscura Vault becomes 2+
   channels. It's a real refactor; don't do it speculatively.

Documentation is now in place (`README.md` as user manual,
`docs/<engine>.md` for each module). The system is buildable, the
plan is clear, the list is short. Time to actually run it.
