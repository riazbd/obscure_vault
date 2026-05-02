# Graph Report - .  (2026-05-03)

## Corpus Check
- 43 files · ~51,106 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 389 nodes · 688 edges · 28 communities detected
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 130 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Server Orchestration & Routes|Server Orchestration & Routes]]
- [[_COMMUNITY_Analytics & Review Loop|Analytics & Review Loop]]
- [[_COMMUNITY_LLM Interface & Scripting|LLM Interface & Scripting]]
- [[_COMMUNITY_Idea Harvesting & Scoring|Idea Harvesting & Scoring]]
- [[_COMMUNITY_Research & Fact Extraction|Research & Fact Extraction]]
- [[_COMMUNITY_YouTube Upload & Auth|YouTube Upload & Auth]]
- [[_COMMUNITY_Branding & Pipeline Entry|Branding & Pipeline Entry]]
- [[_COMMUNITY_Core Pipeline Assembly|Core Pipeline Assembly]]
- [[_COMMUNITY_Footage Generation|Footage Generation]]
- [[_COMMUNITY_Scheduler & State Management|Scheduler & State Management]]
- [[_COMMUNITY_Storage Management|Storage Management]]
- [[_COMMUNITY_Thumbnail Creation|Thumbnail Creation]]
- [[_COMMUNITY_Job History (SQLite)|Job History (SQLite)]]
- [[_COMMUNITY_Captions & Transcription|Captions & Transcription]]
- [[_COMMUNITY_System Design Docs|System Design Docs]]
- [[_COMMUNITY_Startup & CLI|Startup & CLI]]
- [[_COMMUNITY_Content Generation Modules|Content Generation Modules]]
- [[_COMMUNITY_Persistence & UI|Persistence & UI]]
- [[_COMMUNITY_Pexels API Config|Pexels API Config]]
- [[_COMMUNITY_OpenRouter API Config|OpenRouter API Config]]
- [[_COMMUNITY_Voiceover Gen|Voiceover Gen]]
- [[_COMMUNITY_Footage Fetch|Footage Fetch]]
- [[_COMMUNITY_Obscura Vault Pipeline|Obscura Vault Pipeline]]
- [[_COMMUNITY_YouTube Engine Readme|YouTube Engine Readme]]
- [[_COMMUNITY_Python Dependencies|Python Dependencies]]
- [[_COMMUNITY_Branding Stings|Branding Stings]]
- [[_COMMUNITY_SEO Scoring|SEO Scoring]]
- [[_COMMUNITY_Resumable Upload|Resumable Upload]]

## God Nodes (most connected - your core abstractions)
1. `start()` - 21 edges
2. `call()` - 19 edges
3. `run_pipeline_thread()` - 15 edges
4. `run_harvest()` - 15 edges
5. `run_short_pipeline_thread()` - 14 edges
6. `load_config()` - 13 edges
7. `generate_script()` - 13 edges
8. `main()` - 12 edges
9. `build()` - 12 edges
10. `build_research_pack()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `Whisper Transcription & Burn-in` --semantically_similar_to--> `Single-File Pipeline UI`  [INFERRED] [semantically similar]
  docs/captions.md → ui/index.html
- `generate_visual_queries()` --calls--> `call()`  [INFERRED]
  engines\footage.py → llm.py
- `score_with_llm()` --calls--> `call()`  [INFERRED]
  engines\ideas.py → llm.py
- `extract_facts()` --calls--> `call()`  [INFERRED]
  engines\research.py → llm.py
- `review()` --calls--> `call()`  [INFERRED]
  engines\review.py → llm.py

## Hyperedges (group relationships)
- **Core Orchestration** — server_run_pipeline_thread, pipeline_core_generate_voiceover, engines_jobs_upsert_job [INFERRED 0.90]
- **Content Generation** — engines_script_generate_script, engines_research_build_research_pack, engines_footage_build, engines_thumbnail_generate, engines_seo_build_seo_pack [INFERRED 0.90]
- **Autonomous Content Lifecycle** — ideas_niche_fit, research_fact_grounding, script_quality_gates, footage_semantic_broll, thumbnail_composition, upload_resumable [EXTRACTED 0.95]
- **Performance Optimization Loop** — upload_resumable, analytics_token_signals, review_llm_scorecard, ideas_niche_fit [INFERRED 0.90]
- **Resource-Constrained Architecture** — plan_obscura_vault, llm_free_cascade, storage_output_cap, branding_stings [INFERRED 0.85]

## Communities

### Community 0 - "Server Orchestration & Routes"
Cohesion: 0.05
Nodes (30): Start the scheduler thread.       get_cfg() -> dict   — current config snapshot, start(), analytics_refresh(), branding_upload(), captions_install(), check_ffmpeg(), check_package(), check_pexels_key() (+22 more)

### Community 1 - "Analytics & Review Loop"
Cohesion: 0.08
Nodes (38): _build_youtube_analytics(), _build_youtube_data(), compute_token_signals(), _fetch_analytics(), _fetch_data_stats(), list_metrics(), list_uploads(), _load_metrics() (+30 more)

### Community 2 - "LLM Interface & Scripting"
Cohesion: 0.09
Nodes (35): _draft_prompt(), generate_outline(), generate_script(), generate_short_script(), _outline_prompt(), _quality_check(), ScriptEngine — turn an idea into an outline + full narration script.  Two-pass, One-shot script for a 30–55 second YouTube Short.     Returns: {script, word_co (+27 more)

### Community 3 - "Idea Harvesting & Scoring"
Cohesion: 0.14
Nodes (25): delete(), _filter_obviously_bad(), harvest_reddit(), harvest_wikipedia(), harvest_youtube_suggest(), _id_for(), _is_duplicate(), _jaccard() (+17 more)

### Community 4 - "Research & Fact Extraction"
Cohesion: 0.11
Nodes (21): build_research_pack(), _cache_path(), ddg_search(), dedup_claims(), extract_facts(), fetch_url_text(), html_to_text(), _jaccard() (+13 more)

### Community 5 - "YouTube Upload & Auth"
Cohesion: 0.15
Nodes (22): authorize(), _build_youtube(), channel_info(), has_secrets(), has_token(), is_installed(), _load_creds(), publish() (+14 more)

### Community 6 - "Branding & Pipeline Entry"
Cohesion: 0.14
Nodes (21): apply_branding(), apply_for_video_kind(), delete_slot(), has_slot(), list_slots(), normalize_clip(), _probe_duration(), BrandingEngine — normalize user-supplied intro/outro stings, then concat them a (+13 more)

### Community 7 - "Core Pipeline Assembly"
Cohesion: 0.19
Nodes (19): assemble_video(), build_footage_track(), cleanup_raw_footage(), clip_real_duration(), collect_input(), download_clip(), fetch_footage(), generate_thumbnail() (+11 more)

### Community 8 - "Footage Generation"
Cohesion: 0.15
Nodes (16): build(), build_footage_track(), chunk_script_by_time(), _download(), generate_visual_queries(), pick_clips_for_chunks(), _process_clip_segment(), FootageEngine — semantic per-chunk B-roll.  Pipeline:   1. Split the narratio (+8 more)

### Community 9 - "Scheduler & State Management"
Cohesion: 0.18
Nodes (16): _compute_next_run(), get_state(), _is_due(), _load_state(), _log(), SchedulerEngine — single-process tick loop that fires recurring tasks.  Tasks, Pick the best pending idea and start the full pipeline., Manually fire a task (button in UI). Returns the run record. (+8 more)

### Community 10 - "Storage Management"
Cohesion: 0.2
Nodes (17): task_storage_cleanup(), cleanup_all_workspaces(), cleanup_workspace(), _du(), enforce_output_cap(), estimate_freeable(), _mb(), StorageEngine — disk usage reporting + cleanup tasks.  T480 has ~200 GB usable (+9 more)

### Community 11 - "Thumbnail Creation"
Cohesion: 0.18
Nodes (16): _avg_luminance(), compose_thumbnail(), _ensure_dark(), _font(), generate(), generate_image_prompt(), generate_punchline(), _img_cache_key() (+8 more)

### Community 12 - "Job History (SQLite)"
Cohesion: 0.25
Nodes (15): append_log(), _conn(), delete_old(), _ensure_schema(), get_job(), list_jobs(), mark_orphans_failed(), _now() (+7 more)

### Community 13 - "Captions & Transcription"
Cohesion: 0.23
Nodes (13): _ass_escape(), _ass_time(), build(), chunk_words_into_cards(), CaptionEngine — local speech-to-text via faster-whisper, then styled .ass + pla, Transcribe audio_path and write {workspace}/captions.ass + captions.srt.     st, Returns a list of segments: [{start: float, end: float, text: str}, ...]     Ea, Repack word-level timing into 2-line subtitle cards under MAX_DURATION. (+5 more)

### Community 14 - "System Design Docs"
Cohesion: 0.33
Nodes (7): Token Performance Signals, Idea Niche Fit Scoring, Obscura Vault System, Phase Ledger, LLM Performance Scorecard, Autopilot Scheduler, Output Cap Enforcement

### Community 15 - "Startup & CLI"
Cohesion: 0.8
Nodes (5): check_ffmpeg(), check_packages(), check_python(), cprint(), main()

### Community 16 - "Content Generation Modules"
Cohesion: 0.4
Nodes (5): Semantic B-roll Engine, OpenRouter Free-Model Cascade, Citation-Grounded Fact Extraction, Script Quality Gates, AI Thumbnail Composition

### Community 18 - "Persistence & UI"
Cohesion: 0.67
Nodes (3): Whisper Transcription & Burn-in, SQLite Job History, Single-File Pipeline UI

### Community 21 - "Pexels API Config"
Cohesion: 1.0
Nodes (1): Pexels API Key

### Community 22 - "OpenRouter API Config"
Cohesion: 1.0
Nodes (1): OpenRouter API Key

### Community 23 - "Voiceover Gen"
Cohesion: 1.0
Nodes (1): Generate Voiceover

### Community 24 - "Footage Fetch"
Cohesion: 1.0
Nodes (1): Fetch Footage

### Community 25 - "Obscura Vault Pipeline"
Cohesion: 1.0
Nodes (1): Obscura Vault Pipeline

### Community 26 - "YouTube Engine Readme"
Cohesion: 1.0
Nodes (1): Automated YouTube Engine

### Community 27 - "Python Dependencies"
Cohesion: 1.0
Nodes (1): Python Dependencies

### Community 28 - "Branding Stings"
Cohesion: 1.0
Nodes (1): Channel Intro/Outro Stings

### Community 29 - "SEO Scoring"
Cohesion: 1.0
Nodes (1): SEO Scoring Rubric

### Community 30 - "Resumable Upload"
Cohesion: 1.0
Nodes (1): Resumable YouTube Upload

## Knowledge Gaps
- **89 isolated node(s):** `OpenRouter client with model cascade, file-based caching, and JSON parsing. Fre`, `Pull the first balanced {...} or [...] block out of the model output.`, `Call OpenRouter cascading through free models. Returns dict:       {text, json,`, `Quick check: send a tiny prompt and see if at least one free model responds.`, `╔══════════════════════════════════════════════════════════════╗ ║           OB` (+84 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Pexels API Config`** (1 nodes): `Pexels API Key`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OpenRouter API Config`** (1 nodes): `OpenRouter API Key`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voiceover Gen`** (1 nodes): `Generate Voiceover`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Footage Fetch`** (1 nodes): `Fetch Footage`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Obscura Vault Pipeline`** (1 nodes): `Obscura Vault Pipeline`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `YouTube Engine Readme`** (1 nodes): `Automated YouTube Engine`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Python Dependencies`** (1 nodes): `Python Dependencies`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Branding Stings`** (1 nodes): `Channel Intro/Outro Stings`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `SEO Scoring`** (1 nodes): `SEO Scoring Rubric`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Resumable Upload`** (1 nodes): `Resumable YouTube Upload`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_short_pipeline_thread()` connect `Branding & Pipeline Entry` to `Server Orchestration & Routes`, `LLM Interface & Scripting`, `YouTube Upload & Auth`, `Footage Generation`, `Storage Management`, `Thumbnail Creation`, `Job History (SQLite)`?**
  _High betweenness centrality (0.115) - this node is a cross-community bridge._
- **Why does `run_pipeline_thread()` connect `Branding & Pipeline Entry` to `Server Orchestration & Routes`, `Idea Harvesting & Scoring`, `YouTube Upload & Auth`, `Footage Generation`, `Storage Management`, `Thumbnail Creation`, `Job History (SQLite)`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `call()` connect `LLM Interface & Scripting` to `Analytics & Review Loop`, `Idea Harvesting & Scoring`, `Research & Fact Extraction`, `Footage Generation`, `Thumbnail Creation`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `start()` (e.g. with `run_short()` and `run_pipeline()`) actually correct?**
  _`start()` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `call()` (e.g. with `generate_visual_queries()` and `score_with_llm()`) actually correct?**
  _`call()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `run_pipeline_thread()` (e.g. with `upsert_job()` and `is_available()`) actually correct?**
  _`run_pipeline_thread()` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `run_harvest()` (e.g. with `_run_harvest()` and `compute_token_signals()`) actually correct?**
  _`run_harvest()` has 4 INFERRED edges - model-reasoned connections that need verification._