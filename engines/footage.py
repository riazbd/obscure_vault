"""
FootageEngine — semantic per-chunk B-roll.

Pipeline:
  1. Split the narration script into ~10-second chunks aligned to the
     known voiceover duration.
  2. ONE batched LLM call returns 1-2 concrete cinematographic search
     queries per chunk.
  3. Search Pexels (primary) and optionally Pixabay (secondary) for each
     query in parallel-ish, gather candidates.
  4. Pick one clip per chunk: avoid reuse, prefer 1080p, prefer duration
     close to chunk length, fall back to looping/cycling.
  5. Process each clip with the channel colour grade trimmed to its
     chunk duration, then concat. Output a single MP4 ready for the
     final assembly step.
"""

import re
import json
import random
import hashlib
import subprocess
from pathlib import Path

import requests

import llm


COLOR_GRADE = (
    "colorchannelmixer=rr=1.05:gg=0.95:bb=0.88,"
    "curves=all='0/0 0.25/0.18 0.75/0.65 1/0.90',"
    "eq=saturation=0.78:brightness=-0.04:contrast=1.10"
)


# ════════════════════════════════════════════════════════
#  Chunking
# ════════════════════════════════════════════════════════

def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p for p in parts if p]


def chunk_script_by_time(script: str, total_seconds: float,
                         target_chunk_secs: float = 10.0) -> list[dict]:
    """
    Returns: [{id, text, start, end, duration}, ...] covering exactly
    total_seconds.  Sentence-grouped; durations are scaled so the sum
    matches total_seconds exactly.
    """
    sentences = _split_sentences(script)
    if not sentences:
        return [{"id": 1, "text": script, "start": 0.0,
                 "end": total_seconds, "duration": total_seconds}]

    total_words  = sum(len(s.split()) for s in sentences) or 1
    sec_per_word = total_seconds / total_words

    raw_chunks = []
    cur_text, cur_words = [], 0
    for s in sentences:
        sw = len(s.split())
        cur_text.append(s)
        cur_words += sw
        if cur_words * sec_per_word >= target_chunk_secs:
            raw_chunks.append({"text": " ".join(cur_text), "words": cur_words})
            cur_text, cur_words = [], 0
    if cur_text:
        if raw_chunks:
            raw_chunks[-1]["text"]  += " " + " ".join(cur_text)
            raw_chunks[-1]["words"] += cur_words
        else:
            raw_chunks.append({"text": " ".join(cur_text), "words": cur_words})

    # Convert to timed
    out, cursor = [], 0.0
    for i, c in enumerate(raw_chunks, 1):
        dur = c["words"] * sec_per_word
        out.append({
            "id": i, "text": c["text"],
            "start": cursor, "end": cursor + dur, "duration": dur,
        })
        cursor += dur

    # Re-scale to hit total_seconds exactly (rounding drift)
    scale = total_seconds / max(cursor, 0.001)
    cursor = 0.0
    for c in out:
        c["duration"] *= scale
        c["start"]    = cursor
        c["end"]      = cursor + c["duration"]
        cursor        = c["end"]
    return out


# ════════════════════════════════════════════════════════
#  LLM — batched query generation
# ════════════════════════════════════════════════════════

def generate_visual_queries(api_key: str, chunks: list[dict],
                            channel_style: str = None) -> dict[int, list[str]]:
    """
    One batched LLM call. Returns {chunk_id: [query, ...]}.
    """
    style = channel_style or (
        "dark history documentary, mysterious, atmospheric, cinematic, "
        "dramatic lighting, fog, shadows, period-appropriate scenes"
    )
    msgs = [
        {"role": "system", "content":
            "You write search queries for stock footage libraries. "
            "Output ONLY valid JSON."},
        {"role": "user", "content": f"""
Channel style: {style}

For each script chunk below, write 2 stock-footage search queries.
Each query is a short phrase (3 to 6 words) describing concrete visuals
that would match the moment. Be cinematographic, not literal — describe
what the camera would SHOW, not the topic name.

Examples of good queries:
  "abandoned soviet bunker dim corridor"
  "fog over still mountain lake dawn"
  "old typewriter close up dim room"
  "gothic cathedral interior empty pews"

Bad queries (do not produce these):
  "history", "war", "mystery", "documentary", "the truth"

Chunks:
{json.dumps([{"id": c["id"], "text": c["text"][:400]} for c in chunks],
            indent=2, ensure_ascii=False)}

Return JSON:
{{
  "chunks": [
    {{"id": 1, "queries": ["query a", "query b"]}},
    ...
  ]
}}
""".strip()}]

    res = llm.call(api_key, msgs, json_mode=True, temperature=0.6,
                   max_tokens=3500)
    out = {}
    data = res["json"] or {}
    for item in data.get("chunks", []):
        if "id" in item and "queries" in item:
            qs = [q for q in item["queries"] if isinstance(q, str) and q.strip()]
            if qs:
                out[int(item["id"])] = qs
    return out


# ════════════════════════════════════════════════════════
#  Provider searches
# ════════════════════════════════════════════════════════

def search_pexels(query: str, key: str, n: int = 4) -> list[dict]:
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={"query": query, "per_page": n,
                    "orientation": "landscape", "size": "medium"},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        clips = []
        for v in r.json().get("videos", []):
            files = sorted(
                [f for f in v.get("video_files", []) if f.get("width", 0) <= 1920],
                key=lambda x: x.get("width", 0), reverse=True
            )
            if not files:
                continue
            clips.append({
                "id":       f"px_{v['id']}",
                "url":      files[0]["link"],
                "duration": v.get("duration", 8),
                "width":    files[0].get("width", 0),
                "height":   files[0].get("height", 0),
                "query":    query,
                "source":   "pexels",
            })
        return clips
    except requests.RequestException:
        return []


def search_pixabay(query: str, key: str, n: int = 4) -> list[dict]:
    if not key:
        return []
    try:
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": key, "q": query, "per_page": max(3, n),
                    "video_type": "film", "safesearch": "true",
                    "orientation": "horizontal"},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        clips = []
        for v in r.json().get("hits", []):
            videos = v.get("videos", {})
            # prefer 'large' (often 1080p), fall back to medium then small
            for size_key in ("large", "medium", "small"):
                vf = videos.get(size_key) or {}
                if vf.get("url"):
                    clips.append({
                        "id":       f"pb_{v.get('id')}",
                        "url":      vf["url"],
                        "duration": v.get("duration", 8),
                        "width":    vf.get("width", 0),
                        "height":   vf.get("height", 0),
                        "query":    query,
                        "source":   "pixabay",
                    })
                    break
        return clips
    except requests.RequestException:
        return []


# ════════════════════════════════════════════════════════
#  Selection + ranking
# ════════════════════════════════════════════════════════

def _score(clip: dict, chunk_dur: float, used_ids: set, query_idx: int) -> float:
    s = 0.0
    # Resolution
    s += min(clip.get("width", 0) / 1920.0, 1.0) * 0.25
    # Duration close to chunk (penalise much-shorter clips)
    cd = max(clip.get("duration", 1), 1)
    if cd >= chunk_dur:
        s += 0.35
    else:
        s += (cd / chunk_dur) * 0.25
    # Earlier query (LLM's first query is usually more specific)
    s += max(0.0, 0.20 - query_idx * 0.10)
    # Reuse penalty
    if clip["id"] in used_ids:
        s -= 0.50
    return s


def pick_clips_for_chunks(
    chunks: list[dict],
    queries_per_chunk: dict[int, list[str]],
    pexels_key: str,
    pixabay_key: str,
    on_log=None,
) -> list[dict]:
    """
    Returns: [{chunk_id, query, clip}|None for each chunk]
    """
    log = on_log or (lambda m: None)
    used_ids = set()
    plan = []

    # Cache by query so repeats across chunks share results
    cache: dict[str, list[dict]] = {}

    def search_query(q: str) -> list[dict]:
        if q in cache:
            return cache[q]
        results = search_pexels(q, pexels_key, n=4) + search_pixabay(q, pixabay_key, n=3)
        cache[q] = results
        return results

    for c in chunks:
        queries = queries_per_chunk.get(c["id"], [])
        if not queries:
            queries = [c["text"][:60]]   # fallback: literal first words

        candidates = []
        for qi, q in enumerate(queries):
            for cl in search_query(q):
                candidates.append((qi, cl))

        if not candidates:
            log(f"   ⚠️  chunk {c['id']}: no clips found")
            plan.append({"chunk": c, "clip": None, "query": queries[0] if queries else ""})
            continue

        candidates.sort(key=lambda t: _score(t[1], c["duration"], used_ids, t[0]),
                        reverse=True)
        best = candidates[0][1]
        used_ids.add(best["id"])
        plan.append({"chunk": c, "clip": best, "query": best["query"]})
        log(f"   ↳ chunk {c['id']:>2d} ({c['duration']:5.1f}s) ← {best['source']:7s} "
            f"[{best['query'][:40]}]")

    return plan


# ════════════════════════════════════════════════════════
#  Download + assembly
# ════════════════════════════════════════════════════════

def _download(url: str, dest: Path, clip_meta: dict | None = None) -> bool:
    """Download url → dest; register in clip library on success."""
    if dest.exists():
        return True
    # Check library cache first (clips shared across renders)
    if clip_meta:
        try:
            from engines import clip_library as _cl
            cached = _cl.find_cached(clip_meta["id"])
            if cached and cached != dest:
                import shutil as _shutil
                _shutil.copy2(str(cached), str(dest))
                return True
        except Exception:
            pass
    try:
        r = requests.get(url, stream=True, timeout=90)
        if r.status_code != 200:
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                f.write(chunk)
        # Register in persistent library so future renders can reuse it
        if clip_meta:
            try:
                from engines import clip_library as _cl
                _cl.register(
                    clip_meta["id"], url, clip_meta.get("source", ""),
                    dest, clip_meta.get("query", ""),
                    clip_meta.get("duration", 0),
                    clip_meta.get("width", 0), clip_meta.get("height", 0),
                )
            except Exception:
                pass
        return True
    except requests.RequestException:
        return False


def _process_clip_segment(src: Path, out: Path, duration: float,
                          width: int, height: int,
                          motion: str = "pan") -> bool:
    """
    Trim/loop src to exact duration, scale+crop to W×H, apply colour grade.
    motion: "off"   — flat scale+crop (legacy)
            "pan"   — slow horizontal Ken-Burns drift (default)
            "zoom"  — slow centered zoom-in (best for stills)
    """
    if motion == "off":
        vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
              f"crop={width}:{height},setsar=1,{COLOR_GRADE}")
    elif motion == "zoom":
        # Headroom + slow centered zoom from 1.0× to 1.10× over the chunk.
        # `zoompan` only samples the first frame on video input — it really
        # only suits stills; we expose it but default to "pan".
        scaled_w = (int(width  * 1.20) // 2) * 2
        scaled_h = (int(height * 1.20) // 2) * 2
        zoom_max = 1.10
        zoom_per_frame = (zoom_max - 1.0) / max(1.0, duration * 30)
        vf = (f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
              f"zoompan=z='min(zoom+{zoom_per_frame:.6f},{zoom_max})'"
              f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d=1:fps=30:s={width}x{height},"
              f"setsar=1,{COLOR_GRADE}")
    else:
        # "pan" — work on video too. Scale ~10% larger than canvas, then
        # crop with a slow sinusoidal x offset so the picture drifts.
        head_w = (int(width  * 1.12) // 2) * 2
        head_h = (int(height * 1.12) // 2) * 2
        # Phase signs alternate per call site; here we go with a positive
        # cosine so the drift starts at left, sweeps right, returns near
        # centre — looks natural at any duration.
        vf = (
            f"scale={head_w}:{head_h}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
            f":x='(iw-{width})/2*(1+cos(t*PI/{max(duration, 0.1):.3f}))'"
            f":y='(ih-{height})/2',"
            f"setsar=1,{COLOR_GRADE}"
        )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-r", "30", "-pix_fmt", "yuv420p",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode == 0 and out.exists():
        return True
    # If the fancy filter chain failed (rare — usually a weird source clip),
    # retry with the flat scale+crop so the chunk still ships.
    if motion != "off":
        return _process_clip_segment(src, out, duration, width, height,
                                     motion="off")
    return False


def build_footage_track(plan: list[dict], workspace: Path,
                        width: int, height: int,
                        motion: str = "pan",
                        on_log=None) -> Path:
    """
    Download every plan clip (parallel, I/O-bound), render segments
    (sequential, CPU-bound FFmpeg), then concat.
    Returns the trimmed final footage track path.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    log = on_log or (lambda m: None)
    raw_dir  = workspace / "footage"
    proc_dir = workspace / "processed"
    raw_dir.mkdir(exist_ok=True)
    proc_dir.mkdir(exist_ok=True)

    # Phase 1: download all clips in parallel (skip already-cached files)
    # Carry full clip metadata so _download() can consult the clip library.
    to_dl: dict[str, tuple[str, Path, dict]] = {}
    for item in plan:
        clip = item.get("clip")
        if clip:
            src = raw_dir / f"{clip['id']}.mp4"
            if not src.exists():
                to_dl[clip["id"]] = (clip["url"], src, clip)

    if to_dl:
        log(f"   📥 downloading {len(to_dl)} clips (up to 4 in parallel)...")
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {pool.submit(_download, url, dest, meta): cid
                    for cid, (url, dest, meta) in to_dl.items()}
            for fut in as_completed(futs):
                cid = futs[fut]
                if not fut.result():
                    log(f"      ⚠️  download failed: {cid}")

    segments: list[Path] = []

    for i, item in enumerate(plan):
        chunk = item["chunk"]
        clip  = item.get("clip")
        seg   = proc_dir / f"chunk_{chunk['id']:03d}.mp4"

        if clip is None:
            # Make a dark card for this chunk
            log(f"   🟥 chunk {chunk['id']}: dark card ({chunk['duration']:.1f}s)")
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=0x0a0a0a:size={width}x{height}:rate=30:duration={chunk['duration']:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg),
            ], capture_output=True)
            if seg.exists():
                segments.append(seg)
            continue

        suffix = ".mp4"
        src = raw_dir / f"{clip['id']}{suffix}"
        if not _download(clip["url"], src, clip):
            log(f"   ⚠️  download failed: {clip['id']}; falling back to dark card")
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=0x0a0a0a:size={width}x{height}:rate=30:duration={chunk['duration']:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg),
            ], capture_output=True)
        else:
            ok = _process_clip_segment(src, seg, chunk["duration"],
                                       width, height, motion=motion)
            if not ok:
                log(f"   ⚠️  process failed: {clip['id']}")
                continue

        if seg.exists():
            segments.append(seg)

    if not segments:
        # Total fallback: one dark card spanning total duration
        total = sum(p["chunk"]["duration"] for p in plan) or 60
        fallback = proc_dir / "fallback.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x0a0a0a:size={width}x{height}:rate=30:duration={total:.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(fallback),
        ], capture_output=True)
        return fallback

    # Concat segments — same codec/params, stream-copy is safe
    concat_txt = workspace / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in segments))
    out = proc_dir / "footage_track.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt), "-c", "copy", str(out),
    ], capture_output=True)
    return out


# ════════════════════════════════════════════════════════
#  Top-level
# ════════════════════════════════════════════════════════

def build(
    *,
    script: str,
    duration: float,
    workspace: Path,
    openrouter_key: str,
    pexels_key: str,
    pixabay_key: str = "",
    width: int = 1920,
    height: int = 1080,
    target_chunk_secs: float = 10.0,
    motion: str = "pan",
    on_log=None,
) -> dict:
    log = on_log or (lambda m: None)

    log(f"🎬  Smart B-roll: chunking script (~{target_chunk_secs:.0f}s targets)...")
    chunks = chunk_script_by_time(script, duration, target_chunk_secs)
    log(f"   ✅ {len(chunks)} chunks covering {duration:.0f}s")

    log("🔎 Generating visual queries (one batched LLM call)...")
    qpc = generate_visual_queries(openrouter_key, chunks)
    if not qpc:
        raise RuntimeError("LLM returned no usable visual queries")
    log(f"   ✅ queries for {len(qpc)} chunks")

    log("🛰️  Searching providers + picking clips per chunk...")
    plan = pick_clips_for_chunks(chunks, qpc, pexels_key, pixabay_key,
                                 on_log=log)

    log(f"🎞️  Downloading + processing clips (motion={motion})...")
    track = build_footage_track(plan, workspace, width, height,
                                motion=motion, on_log=log)

    return {
        "track":  track,
        "plan":   plan,
        "chunks": chunks,
    }
