"""
OBSCURA VAULT — Web UI Backend Server
Serves the UI and exposes REST API endpoints that run the pipeline.
Cross-platform: Windows, Mac, Linux.
"""

import os
import sys
import re
import json
import queue as _queue
import shutil
import asyncio
import secrets
import subprocess
import threading
import random
import platform
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_from_directory, send_file, Response, stream_with_context

app = Flask(__name__, static_folder="ui")
BASE_DIR   = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
MUSIC_DIR  = BASE_DIR / "music"
OUTPUT_DIR = BASE_DIR / "output"
WORKSPACE  = BASE_DIR / "workspace"

for d in [MUSIC_DIR, OUTPUT_DIR, WORKSPACE]:
    d.mkdir(exist_ok=True)

# ── Job state ────────────────────────────────────────────
jobs = {}                   # job_id -> {status, progress, log, result}
jobs_lock = threading.RLock()
_running_job: set = set()   # at most one job_id while running
_job_queue: _queue.Queue = _queue.Queue()   # FIFO of (job_id, kind, args...)

# ── SSE event queues ──────────────────────────────────────
# Each connected EventSource client gets its own queue.
_sse_queues: dict[str, list[_queue.Queue]] = {}  # job_id -> [client queues]
_sse_lock = threading.Lock()


def _fire_webhook(cfg: dict, event: str, payload: dict) -> None:
    """POST to the configured webhook URL on job completion/failure (non-blocking)."""
    url = (cfg.get("webhook_url") or "").strip()
    if not url:
        return
    allowed = cfg.get("webhook_events") or ["done", "error"]
    if event not in allowed:
        return
    def _post():
        try:
            import requests as _req
            _req.post(url, json={"event": event, **payload}, timeout=10)
        except Exception:
            pass
    threading.Thread(target=_post, daemon=True).start()


def _sse_publish(job_id: str, event_type: str, data: dict) -> None:
    """Push an event to all SSE clients watching job_id."""
    with _sse_lock:
        queues = _sse_queues.get(job_id, [])
    payload = json.dumps({"type": event_type, **data})
    for q in queues:
        try:
            q.put_nowait(payload)
        except _queue.Full:
            pass


# ── Path safety helper ────────────────────────────────────
_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-\.]{1,200}$')

def _safe_name(name: str, allowed_dir: Path) -> Path:
    """Resolve *name* inside *allowed_dir*, raising 400 if traversal detected."""
    if not _SAFE_NAME_RE.match(name):
        from flask import abort
        abort(400, "Invalid filename")
    resolved = (allowed_dir / name).resolve()
    if not str(resolved).startswith(str(allowed_dir.resolve())):
        from flask import abort
        abort(400, "Invalid path")
    return resolved


# ════════════════════════════════════════════════════════
#  Config helpers
# ════════════════════════════════════════════════════════

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {
        "pexels_api_key": "",
        "openrouter_api_key": "",
        "tts_voice": "en-US-GuyNeural",
        "music_volume": 0.12,
        "video_resolution": [1920, 1080],
        "max_clips": 25,
        "use_ai_thumbnail": True,
        "thumbnail_variants": 1,
        "burn_captions": False,
        "caption_model": "base.en",
        "smart_broll": True,
        "pixabay_api_key": "",
        "chunk_seconds": 10,
        "auto_upload": False,
        "default_privacy": "private",
        "contains_synthetic_media": True,
        "use_research": False,
        "motion_effect": "pan",
        "audio_polish": True,
        "ducking_db": 8.0,
        "apply_branding": True,
        "auto_cleanup_workspace": True,
        "output_cap_gb": 30.0,
        "tts_voices": [],
        "daily_limit_long": 2,
        "daily_limit_short": 2,
    }

def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


# ════════════════════════════════════════════════════════
#  System check helpers
# ════════════════════════════════════════════════════════

def check_python():
    return {"ok": True, "version": platform.python_version()}

def check_ffmpeg():
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        line = r.stdout.splitlines()[0] if r.stdout else ""
        return {"ok": r.returncode == 0, "version": line.replace("ffmpeg version ", "").split(" ")[0]}
    except FileNotFoundError:
        return {"ok": False, "version": None}
    except Exception as e:
        return {"ok": False, "version": str(e)}

def check_package(pkg):
    try:
        __import__(pkg.replace("-", "_"))
        return True
    except ImportError:
        return False

def check_pexels_key(key):
    if not key or len(key) < 10:
        return False
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={"query": "nature", "per_page": 1},
            timeout=8
        )
        return r.status_code == 200
    except Exception:
        return False


# ════════════════════════════════════════════════════════
#  Pipeline runner (threaded)
# ════════════════════════════════════════════════════════

def _pick_voice(cfg: dict) -> str:
    """Single voice or rotation pool. Falls back to GuyNeural if none."""
    voices = cfg.get("tts_voices") or []
    voices = [v for v in voices if isinstance(v, str) and v.strip()]
    if voices:
        return random.choice(voices)
    return cfg.get("tts_voice") or "en-US-GuyNeural"


def run_pipeline_thread(job_id: str, title: str, script: str, cfg: dict):
    """Runs the full pipeline in a background thread, updating jobs[job_id]."""
    import requests as req_lib
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    import edge_tts
    from engines import jobs as jobs_db

    job = jobs[job_id]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jobs_db.upsert_job(job_id, kind="long", title=title, status="running",
                       progress=0, stage="Starting...", started_at=started)

    def log(msg):
        job["log"].append(msg)
        _sse_publish(job_id, "log", {"line": msg})
        try:
            jobs_db.append_log(job_id, msg)
        except Exception:
            pass
        print(f"[{job_id}] {msg}")

    def progress(pct, stage):
        job["progress"] = pct
        job["stage"] = stage
        _sse_publish(job_id, "progress", {"pct": pct, "stage": stage})
        try:
            jobs_db.upsert_job(job_id, status="running",
                               progress=pct, stage=stage)
        except Exception:
            pass
        log(f"[{pct}%] {stage}")

    try:
        slug      = re.sub(r"[^\w\s-]", "", title.lower())
        slug      = re.sub(r"[\s_-]+", "_", slug)[:50]
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_name  = f"{ts}_{slug}"
        workspace = WORKSPACE / job_name
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "script.txt").write_text(script)

        # ── Step 1: Voiceover ────────────────────────────
        progress(5, "Generating voiceover via Edge TTS...")
        vo_path = workspace / "voiceover.mp3"

        async def _tts():
            voice = _pick_voice(cfg)
            log(f"   🎙️ voice: {voice}")
            comm = edge_tts.Communicate(script, voice)
            await comm.save(str(vo_path))

        asyncio.run(_tts())
        log(f"✅ voiceover.mp3 ({vo_path.stat().st_size // 1024} KB)")

        # ── Get duration ─────────────────────────────────
        progress(12, "Analysing audio duration...")
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(vo_path)],
            capture_output=True, text=True
        )
        duration = float(r.stdout.strip())
        m, s = int(duration // 60), int(duration % 60)
        log(f"✅ Duration: {m}m {s}s")
        job["duration"] = f"{m}:{s:02d}"

        # ── Step 1b: Captions (optional, before footage so it can run concurrently
        #            on a faster box; here it's serial to spare RAM) ──
        captions_ass = None
        if cfg.get("burn_captions"):
            try:
                from engines import captions as cap_engine
                if not cap_engine.is_available():
                    log("⚠️  burn_captions enabled but faster-whisper not installed; skipping")
                else:
                    progress(14, "Generating captions...")
                    cap_result = cap_engine.build(
                        vo_path, workspace,
                        model_name=cfg.get("caption_model", "base.en"),
                        on_log=log,
                    )
                    captions_ass = cap_result["ass"]
                    # Copy .srt into output dir for YouTube upload
                    srt_dest = OUTPUT_DIR / f"{job_name}.srt"
                    try:
                        shutil.copyfile(cap_result["srt"], srt_dest)
                    except Exception:
                        pass
            except Exception as e:
                log(f"⚠️  caption build failed, continuing without burn-in: {e}")
                captions_ass = None

        # ── Step 2-4: Footage ────────────────────────────
        footage_track    = None
        footage_paths    = []
        used_smart_broll = False
        W, H = cfg.get("video_resolution", [1920, 1080])

        if (cfg.get("smart_broll", True)
            and cfg.get("openrouter_api_key", "")
            and cfg.get("pexels_api_key", "")):
            progress(18, "Smart B-roll: chunking script + querying LLM...")
            try:
                from engines import footage as footage_engine
                br = footage_engine.build(
                    script=script, duration=duration, workspace=workspace,
                    openrouter_key=cfg["openrouter_api_key"],
                    pexels_key=cfg["pexels_api_key"],
                    pixabay_key=cfg.get("pixabay_api_key", ""),
                    width=W, height=H,
                    target_chunk_secs=float(cfg.get("chunk_seconds", 10.0)),
                    motion=cfg.get("motion_effect", "pan"),
                    on_log=log,
                )
                footage_track    = br["track"]
                footage_paths    = sorted((workspace / "footage").glob("*.mp4"))
                used_smart_broll = True
                progress(65, f"Smart B-roll ready ({len(br['plan'])} chunks)")
            except Exception as e:
                log(f"⚠️  Smart B-roll failed, falling back to legacy: {e}")
                footage_track = None

        if not used_smart_broll:
            # ── Legacy: substring keywords → bulk Pexels → uniform process ──
            progress(18, "Searching Pexels for footage...")
            footage_dir = workspace / "footage"
            footage_dir.mkdir(exist_ok=True)
            footage_paths = []

            pexels_key = cfg.get("pexels_api_key", "")
            if pexels_key and len(pexels_key) > 10:
                KEYWORD_MAP = {
                    "war": ["war ruins smoke", "battlefield aerial", "military ruins"],
                    "secret": ["dark corridor", "vault door steel", "shadow mystery"],
                    "death": ["graveyard fog", "dark cemetery night", "abandoned place"],
                    "disappear": ["fog forest", "dark lake mist", "abandoned building"],
                    "prison": ["dark prison", "stone dungeon", "iron bars gate"],
                    "ancient": ["ancient ruins", "stone temple", "archaeology excavation"],
                    "soviet": ["soviet era building", "cold war bunker", "brutalist architecture"],
                    "plague": ["medieval architecture", "dramatic storm clouds", "empty town"],
                    "nasa": ["space dark", "night sky stars", "rocket launch"],
                    "cia": ["government building", "dark hallway", "city at night"],
                    "nuclear": ["explosion cloud", "power plant", "dramatic storm"],
                    "experiment": ["dark laboratory", "science equipment", "microscope"],
                    "cult": ["dark forest night", "abandoned church", "candlelight"],
                    "ship": ["stormy ocean", "shipwreck", "dark stormy sea"],
                    "mountain": ["mountain fog", "blizzard snow", "dark alpine peak"],
                    "default": ["dramatic dark clouds", "abandoned historical building",
                                "foggy landscape", "dark ruins"],
                }
                ATMOSPHERIC = [
                    "candle flame dark background", "old parchment texture",
                    "dramatic light rays", "dark water reflection",
                    "ancient stone texture", "dramatic thunderstorm",
                    "foggy forest path", "dark corridor light end",
                ]
                title_lower = title.lower()
                keywords = []
                for trigger, queries in KEYWORD_MAP.items():
                    if trigger in title_lower:
                        keywords.extend(random.sample(queries, min(2, len(queries))))
                if not keywords:
                    keywords = list(KEYWORD_MAP["default"])
                keywords += random.sample(ATMOSPHERIC, 3)

                all_meta = []
                for kw in keywords:
                    if len(all_meta) >= cfg.get("max_clips", 25):
                        break
                    try:
                        headers = {"Authorization": pexels_key}
                        params  = {"query": kw, "per_page": 3,
                                   "orientation": "landscape", "size": "medium"}
                        resp = req_lib.get("https://api.pexels.com/videos/search",
                                           headers=headers, params=params, timeout=15)
                        resp.raise_for_status()
                        for v in resp.json().get("videos", []):
                            files = sorted(
                                [f for f in v.get("video_files", []) if f.get("width", 0) <= 1920],
                                key=lambda x: x.get("width", 0), reverse=True
                            )
                            if files:
                                all_meta.append({"id": v["id"], "url": files[0]["link"],
                                                 "duration": v.get("duration", 8), "q": kw})
                    except Exception as e:
                        log(f"⚠️ Pexels '{kw}': {e}")

                random.shuffle(all_meta)
                total_secs, need = 0.0, duration * 1.5
                downloaded = 0
                for meta in all_meta:
                    if total_secs >= need:
                        break
                    dest = footage_dir / f"clip_{meta['id']}.mp4"
                    try:
                        r2 = req_lib.get(meta["url"], stream=True, timeout=60)
                        r2.raise_for_status()
                        with open(dest, "wb") as f:
                            for chunk in r2.iter_content(1024 * 256):
                                f.write(chunk)
                        footage_paths.append(dest)
                        total_secs += meta["duration"]
                        downloaded += 1
                        pct = 18 + int((downloaded / max(len(all_meta), 1)) * 22)
                        progress(min(pct, 40), f"Downloaded clip {downloaded}: {meta['q']}")
                    except Exception as e:
                        log(f"⚠️ Clip download fail: {e}")

                log(f"✅ {len(footage_paths)} clips, ~{total_secs:.0f}s footage")
            else:
                log("⚠️ No Pexels key — using dark background")

            # ── Step 4 (legacy): Process footage ─────────
            progress(45, "Processing and colour-grading footage clips...")
            proc_dir = workspace / "processed"
            proc_dir.mkdir(exist_ok=True)

            COLOR_GRADE = (
                "colorchannelmixer=rr=1.05:gg=0.95:bb=0.88,"
                "curves=all='0/0 0.25/0.18 0.75/0.65 1/0.90',"
                "eq=saturation=0.78:brightness=-0.04:contrast=1.10"
            )

            scaled = []
            for i, cp in enumerate(footage_paths):
                out = proc_dir / f"s{i:03d}.mp4"
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(cp),
                    "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                            f"crop={W}:{H},setsar=1,{COLOR_GRADE}"),
                    "-an", "-c:v", "libx264", "-preset", "fast",
                    "-crf", "23", "-r", "30", "-pix_fmt", "yuv420p", str(out)
                ], capture_output=True)
                if out.exists():
                    scaled.append(out)
                pct = 45 + int((i + 1) / max(len(footage_paths), 1) * 20)
                progress(min(pct, 65), f"Processed clip {i+1}/{len(footage_paths)}")

            if not scaled:
                progress(65, "Generating dark background card...")
                fallback = proc_dir / "fallback.mp4"
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"color=c=0x0a0a0a:size={W}x{H}:rate=30:duration={duration}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(fallback)
                ], capture_output=True)
                footage_track = fallback
            else:
                concat_txt = workspace / "concat.txt"
                lines, current, idx = [], 0.0, 0
                while current < duration + 5:
                    p = scaled[idx % len(scaled)]
                    lines.append(f"file '{p.resolve()}'")
                    try:
                        rd = subprocess.run(
                            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                            capture_output=True, text=True)
                        current += float(rd.stdout.strip())
                    except Exception:
                        current += 8.0
                    idx += 1
                concat_txt.write_text("\n".join(lines))

                progress(66, "Concatenating footage...")
                raw = proc_dir / "concat_raw.mp4"
                subprocess.run([
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_txt), "-c", "copy", str(raw)
                ], capture_output=True)

                trimmed = proc_dir / "footage_trimmed.mp4"
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(raw),
                    "-t", str(duration), "-c", "copy", str(trimmed)
                ], capture_output=True)
                footage_track = trimmed

        # ── Step 3: Music (independent of B-roll branch) ──
        progress(67, "Selecting background music...")
        music_path = None
        tracks = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
        if tracks:
            music_path = random.choice(tracks)
            log(f"✅ Music: {music_path.name}")
        else:
            log("ℹ️ No music files — voiceover only")

        # ── Step 5: Final assembly ───────────────────────
        progress(70, "Assembling final video...")
        final_mp4 = OUTPUT_DIR / f"{job_name}.mp4"
        music_vol     = cfg.get("music_volume", 0.12)
        audio_polish  = cfg.get("audio_polish", True)
        duck_db       = float(cfg.get("ducking_db", 8.0))      # dB the music
                                                                # drops when voice is loud
        # Sidechaincompress maps dB → ratio. ~8 dB of duck = ratio ~6-8.
        duck_ratio    = max(2.0, min(20.0, duck_db / 1.0))

        # If captions exist, copy the .ass into the workspace so we can
        # reference it by relative name (cwd=workspace) and avoid the
        # cross-platform horror of escaping a subtitle filter path.
        sub_chain = ""
        if captions_ass:
            sub_chain = "subtitles=captions.ass,"

        # Filter graph: video subtitle burn-in + voice loudnorm +
        # (optional) sidechain-ducked music mix.
        filter_parts = []
        if sub_chain:
            filter_parts.append(f"[0:v]{sub_chain[:-1]}[v]")
            video_map = ["-map", "[v]"]
        else:
            video_map = ["-map", "0:v"]

        if music_path:
            audio_in = ["-i", str(vo_path), "-i", str(music_path)]
            if audio_polish:
                # Voice → -16 LUFS, music ducks under voice via sidechain.
                # asplit so we can both feed the sidechain and keep the
                # voice signal for the final amix.
                filter_parts.append(
                    f"[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,asplit=2[voice][voice_sc];"
                    f"[2:a]aloop=loop=-1:size=2e+09,volume={music_vol}[m_raw];"
                    f"[m_raw][voice_sc]sidechaincompress="
                    f"threshold=0.05:ratio={duck_ratio:.1f}:attack=20:release=400[m_ducked];"
                    f"[voice][m_ducked]amix=inputs=2:duration=first:dropout_transition=3[aout]"
                )
            else:
                filter_parts.append(
                    f"[2:a]aloop=loop=-1:size=2e+09,volume={music_vol}[m];"
                    f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=3[aout]"
                )
            audio_map = ["-map", "[aout]"]
        else:
            audio_in = ["-i", str(vo_path)]
            if audio_polish:
                filter_parts.append(
                    "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
                )
                audio_map = ["-map", "[aout]"]
            else:
                audio_map = ["-map", "1:a"]

        cmd = ["ffmpeg", "-y", "-i", str(footage_track), *audio_in]
        if filter_parts:
            cmd += ["-filter_complex", ";".join(filter_parts)]
        cmd += [
            "-t", str(duration),
            *video_map, *audio_map,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-pix_fmt", "yuv420p",
            str(final_mp4),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                cwd=str(workspace))
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg assembly failed:\n{result.stderr[-2000:]}")

        # ── Step 5b: Optional branding (intro / outro) ──
        if cfg.get("apply_branding", True):
            try:
                from engines import branding
                if branding.has_slot("long_intro") or branding.has_slot("long_outro"):
                    progress(83, "Adding intro / outro stings...")
                    unbranded = workspace / "main_unbranded.mp4"
                    final_mp4.rename(unbranded)
                    branding.apply_for_video_kind(
                        unbranded, final_mp4,
                        kind="long", width=W, height=H, on_log=log,
                    )
            except Exception as e:
                log(f"⚠️  branding failed (video saved without it): {e}")

        mb = final_mp4.stat().st_size / 1024 / 1024
        log(f"✅ Video: {final_mp4.name} ({mb:.1f} MB)")
        progress(88, "Generating thumbnail...")

        # ── Step 6: Thumbnail ────────────────────────────
        thumb = OUTPUT_DIR / f"{job_name}_thumbnail.jpg"
        used_ai_thumb = False

        if cfg.get("use_ai_thumbnail") and cfg.get("openrouter_api_key"):
            try:
                from engines import thumbnail as thumb_engine
                thumb_engine.generate(
                    cfg["openrouter_api_key"], title, thumb,
                    variants=int(cfg.get("thumbnail_variants", 1) or 1),
                    on_log=log,
                )
                used_ai_thumb = True
            except Exception as e:
                log(f"⚠️  AI thumbnail failed, falling back to legacy: {e}")

        if not used_ai_thumb:
            TW, TH = 1280, 720
            img = Image.new("RGB", (TW, TH), (10, 8, 12))

            if footage_paths:
                try:
                    frame = workspace / "tframe.jpg"
                    subprocess.run([
                        "ffmpeg", "-y", "-i", str(footage_paths[0]),
                        "-ss", "00:00:04", "-vframes", "1",
                        "-vf", f"scale={TW}:{TH}:force_original_aspect_ratio=increase,crop={TW}:{TH}",
                        str(frame)
                    ], capture_output=True)
                    if frame.exists():
                        bg = Image.open(frame).convert("RGB")
                        bg = ImageEnhance.Brightness(bg).enhance(0.28)
                        bg = bg.filter(ImageFilter.GaussianBlur(2))
                        img.paste(bg)
                except Exception:
                    pass

            draw = ImageDraw.Draw(img)
            vig  = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
            vd   = ImageDraw.Draw(vig)
            for i in range(300):
                alpha = int((i / 300) ** 1.9 * 215)
                vd.rectangle([i, i, TW-i, TH-i], outline=(0, 0, 0, alpha))
            img.paste(Image.new("RGB", (TW, TH), (0,0,0)), mask=vig.split()[3])

            draw.rectangle([0, 0, TW, 7], fill=(190, 18, 18))
            draw.rectangle([0, TH-7, TW, TH], fill=(190, 18, 18))

            font_candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ]
            bold_font = next((f for f in font_candidates if Path(f).exists()), None)
            try:
                f_sm    = ImageFont.truetype(bold_font, 24) if bold_font else ImageFont.load_default()
                f_title = ImageFont.truetype(bold_font, 76) if bold_font else ImageFont.load_default()
                f_tag   = ImageFont.truetype(bold_font, 26) if bold_font else ImageFont.load_default()
            except Exception:
                f_sm = f_title = f_tag = ImageFont.load_default()

            draw.text((30, 24), "OBSCURA VAULT", font=f_sm, fill=(190, 18, 18))

            words, lines2, current2 = title.upper().split(), [], ""
            for word in words:
                test = (current2 + " " + word).strip()
                if len(test) <= 22:
                    current2 = test
                else:
                    if current2:
                        lines2.append(current2)
                    current2 = word
            if current2:
                lines2.append(current2)

            lh = 90
            start_y = (TH - len(lines2) * lh) // 2 - 30
            for i2, line in enumerate(lines2):
                y = start_y + i2 * lh
                draw.text((54, y+5), line, font=f_title, fill=(0,0,0))
                draw.text((52, y), line, font=f_title, fill=(248, 240, 220))

            draw.text((30, TH - 52), "History They Buried. We Dig It Up.",
                      font=f_tag, fill=(155, 135, 100))

            img.save(str(thumb), "JPEG", quality=95)

        log(f"✅ Thumbnail: {thumb.name}")

        # ── Step 7: Metadata ─────────────────────────────
        progress(95, "Saving YouTube metadata...")
        ts_10 = "10:00 – Modern Implications\n" if m > 10 else ""
        description = f"""{title}

What really happened? This is one of history's most suppressed and mysterious events — and mainstream sources rarely discuss it in full detail.

Obscura Vault digs into archives, declassified documents, and eyewitness accounts to uncover what has been buried from public view.

━━━━━━━━━━━━━━━━━━━━━━━━━
TIMESTAMPS
00:00 – Introduction
01:30 – Background & Context
04:00 – The Hidden Truth
07:00 – The Cover-Up
{ts_10}━━━━━━━━━━━━━━━━━━━━━━━━━

🔔 Subscribe for buried history every week — Obscura Vault.

#ObscuraVault #HiddenHistory #DarkHistory #MysteriousEvents #TrueHistory
#UntoldHistory #HistoryUncovered #DarkDocumentary #ConspiracyFacts #LostHistory""".strip()

        tags = ["hidden history", "dark history", "mysterious events", "obscura vault",
                "untold history", "suppressed history", "history documentary",
                "dark documentary", "conspiracy facts", "lost history",
                title.lower(), *[w.lower() for w in title.split() if len(w) > 3]]

        meta = {"title": title, "description": description,
                "tags": list(dict.fromkeys(tags)),
                "category": "27", "duration_s": round(duration),
                "duration": f"{m}:{s:02d}"}

        (workspace / "metadata.json").write_text(json.dumps(meta, indent=2))
        (workspace / "description.txt").write_text(description)

        # ── Cleanup raw footage ───────────────────────────
        raw_dir = workspace / "footage"
        if raw_dir.exists():
            for f in raw_dir.iterdir():
                try:
                    f.unlink()
                except Exception:
                    pass
            log("🗑️ Raw footage cleaned up")

        # ── Auto-upload to YouTube (if enabled) ──────────
        upload_result = None
        if cfg.get("auto_upload"):
            try:
                from engines import upload as up
                if up.is_installed() and up.has_token():
                    progress(98, "Uploading to YouTube...")
                    log("📤 Auto-upload starting...")
                    srt_sibling = OUTPUT_DIR / f"{job_name}.srt"
                    upload_result = up.publish(
                        final_mp4,
                        title=title,
                        description=description,
                        tags=meta["tags"],
                        thumbnail_path=(thumb if thumb.exists() else None),
                        caption_srt_path=(srt_sibling if srt_sibling.exists() else None),
                        privacy_status=cfg.get("default_privacy", "private"),
                        contains_synthetic_media=cfg.get(
                            "contains_synthetic_media", True),
                        idea_id=cfg.get("_idea_id"),
                        on_log=log,
                    )
                    # If this came from an idea, mark it produced.
                    if cfg.get("_idea_id"):
                        try:
                            from engines import ideas as _I
                            _I.update_status(
                                cfg["_idea_id"], "produced",
                                video_id=upload_result.get("video_id"))
                        except Exception:
                            pass
                    log(f"   ✅ live at {upload_result['url']}")
                else:
                    log("⚠️  auto-upload on but YouTube not authorized; skipping")
            except Exception as e:
                log(f"⚠️  auto-upload failed (video still saved locally): {e}")

        # ── Done ─────────────────────────────────────────
        job["result"] = {
            "video":       final_mp4.name,
            "thumbnail":   thumb.name,
            "description": description,
            "tags":        meta["tags"],
            "duration":    f"{m}:{s:02d}",
            "size_mb":     round(mb, 1),
            "job_name":    job_name,
            "youtube":     upload_result,
        }

        # ── Workspace storage cleanup ────────────────────
        if cfg.get("auto_cleanup_workspace", True):
            try:
                from engines import storage as storage_engine
                cr = storage_engine.cleanup_workspace(job_name)
                if cr.get("ok"):
                    log(f"🧹 freed {cr['freed_mb']} MB from workspace "
                        f"(kept {cr['kept_files']} small files)")
            except Exception as e:
                log(f"⚠️  workspace cleanup failed: {e}")

        # ── Output cap enforcement ───────────────────────
        try:
            from engines import storage as storage_engine
            cap_gb = float(cfg.get("output_cap_gb", 30.0))
            cap_r  = storage_engine.enforce_output_cap(cap_gb)
            if cap_r.get("deleted"):
                log(f"🧹 rolled output dir under {cap_gb} GB "
                    f"(deleted {cap_r['deleted']} oldest, "
                    f"freed {cap_r['freed_mb']} MB)")
        except Exception as e:
            log(f"⚠️  output cap enforcement failed: {e}")

        progress(100, "Complete! 🎬")
        job["status"] = "done"
        _sse_publish(job_id, "done", {"result": job["result"]})
        _fire_webhook(cfg, "done", {"job_id": job_id, "title": title,
                                    "result": job["result"]})
        try:
            jobs_db.upsert_job(
                job_id, status="done", progress=100,
                stage="Complete!",
                finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                result=job["result"],
                duration_s=int(round(duration)),
            )
        except Exception:
            pass

    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ ERROR: {e}")
        job["log"].append(traceback.format_exc())
        _sse_publish(job_id, "error", {"error": str(e)})
        _fire_webhook(cfg, "error", {"job_id": job_id, "title": title,
                                     "error": str(e)})
        try:
            jobs_db.upsert_job(
                job_id, status="error", error=str(e),
                finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            jobs_db.append_log(job_id, f"❌ ERROR: {e}")
        except Exception:
            pass
    finally:
        _running_job.discard(job_id)


# ════════════════════════════════════════════════════════
#  API Routes
# ════════════════════════════════════════════════════════

import requests as req_lib   # needed inside routes too

@app.route("/")
def index():
    return send_from_directory("ui", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("ui", path)

# ── Config ───────────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json
    save_config(data)
    return jsonify({"ok": True})

# ── System check ─────────────────────────────────────────
@app.route("/api/system-check", methods=["GET"])
def system_check():
    cfg = load_config()
    packages = ["edge_tts", "moviepy", "requests", "PIL"]
    return jsonify({
        "python":  check_python(),
        "ffmpeg":  check_ffmpeg(),
        "packages": {p: check_package(p) for p in packages},
        "pexels_key_set": bool(cfg.get("pexels_api_key", "")),
        "music_count": len(list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))),
    })

# ── Validate Pexels key ──────────────────────────────────
@app.route("/api/validate-pexels", methods=["POST"])
def validate_pexels():
    key = request.json.get("key", "")
    ok  = check_pexels_key(key)
    return jsonify({"valid": ok})

# ── TTS voices ───────────────────────────────────────────
@app.route("/api/voices", methods=["GET"])
def get_voices():
    return jsonify([
        {"id": "en-US-GuyNeural",     "label": "Guy (US) — Deep, Authoritative",   "flag": "🇺🇸"},
        {"id": "en-US-EricNeural",    "label": "Eric (US) — Warm, Measured",        "flag": "🇺🇸"},
        {"id": "en-US-DavisNeural",   "label": "Davis (US) — Gravelly, Dramatic",   "flag": "🇺🇸"},
        {"id": "en-GB-RyanNeural",    "label": "Ryan (UK) — British, Formal",       "flag": "🇬🇧"},
        {"id": "en-GB-ThomasNeural",  "label": "Thomas (UK) — Deep, Historical",    "flag": "🇬🇧"},
        {"id": "en-AU-WilliamNeural", "label": "William (AU) — Calm Authority",     "flag": "🇦🇺"},
        {"id": "en-US-AndrewNeural",  "label": "Andrew (US) — Clear, Crisp",        "flag": "🇺🇸"},
    ])

# ── Music library ────────────────────────────────────────
@app.route("/api/music", methods=["GET"])
def list_music():
    tracks = (list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav")))
    return jsonify([{"name": t.name, "size_kb": t.stat().st_size // 1024} for t in tracks])

@app.route("/api/music/upload", methods=["POST"])
def upload_music():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith((".mp3", ".wav")):
        return jsonify({"error": "Only MP3 or WAV files allowed"}), 400
    ext  = Path(f.filename).suffix.lower()
    safe = secrets.token_hex(12) + ext
    dest = MUSIC_DIR / safe
    f.save(str(dest))
    return jsonify({"ok": True, "name": safe})

@app.route("/api/music/delete", methods=["POST"])
def delete_music():
    name = (request.json or {}).get("name", "")
    path = _safe_name(name, MUSIC_DIR)
    if path.exists():
        path.unlink()
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404

# ── Output videos ────────────────────────────────────────
@app.route("/api/outputs", methods=["GET"])
def list_outputs():
    videos = list(OUTPUT_DIR.glob("*.mp4"))
    videos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    results = []
    for v in videos:
        thumb = OUTPUT_DIR / v.name.replace(".mp4", "_thumbnail.jpg")
        results.append({
            "name":      v.name,
            "size_mb":   round(v.stat().st_size / 1024 / 1024, 1),
            "created":   datetime.fromtimestamp(v.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "thumbnail": thumb.name if thumb.exists() else None,
        })
    return jsonify(results)

@app.route("/api/outputs/download/<filename>")
def download_output(filename):
    path = _safe_name(filename, OUTPUT_DIR)
    if path.exists():
        return send_file(str(path), as_attachment=True)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/outputs/thumbnail/<filename>")
def get_thumbnail(filename):
    path = _safe_name(filename, OUTPUT_DIR)
    if path.exists():
        return send_file(str(path), mimetype="image/jpeg")
    return jsonify({"error": "Not found"}), 404

@app.route("/api/outputs/delete", methods=["POST"])
def delete_output():
    name  = (request.json or {}).get("name", "")
    path  = _safe_name(name, OUTPUT_DIR)
    safe_thumb_name = name.replace(".mp4", "_thumbnail.jpg")
    thumb = _safe_name(safe_thumb_name, OUTPUT_DIR)
    if path.exists():
        path.unlink()
    if thumb.exists():
        thumb.unlink()
    return jsonify({"ok": True})

# ── Description for a video ──────────────────────────────
@app.route("/api/outputs/description/<job_name>")
def get_description(job_name):
    safe_dir  = _safe_name(job_name, WORKSPACE)
    desc_path = safe_dir / "description.txt"
    if desc_path.exists():
        return jsonify({"description": desc_path.read_text()})
    return jsonify({"description": ""})


# ════════════════════════════════════════════════════════
#  Shorts pipeline (vertical 1080x1920, 30–55s, hook-only)
# ════════════════════════════════════════════════════════

def run_short_pipeline_thread(job_id: str, idea: str, target_words: int,
                              cfg: dict):
    import requests as req_lib
    from PIL import Image
    import edge_tts
    from engines import jobs as jobs_db

    job = jobs[job_id]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jobs_db.upsert_job(job_id, kind="short", title=idea[:140],
                       status="running", progress=0,
                       stage="Starting Short...", started_at=started)

    def log(msg):
        job["log"].append(msg)
        _sse_publish(job_id, "log", {"line": msg})
        try:
            jobs_db.append_log(job_id, msg)
        except Exception:
            pass
        print(f"[{job_id}] {msg}")

    def progress(pct, stage):
        job["progress"] = pct
        job["stage"] = stage
        _sse_publish(job_id, "progress", {"pct": pct, "stage": stage})
        try:
            jobs_db.upsert_job(job_id, status="running",
                               progress=pct, stage=stage)
        except Exception:
            pass
        log(f"[{pct}%] {stage}")

    try:
        slug = re.sub(r"[^\w\s-]", "", idea.lower())
        slug = re.sub(r"[\s_-]+", "_", slug)[:40]
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_name = f"short_{ts}_{slug}"
        workspace = WORKSPACE / job_name
        workspace.mkdir(parents=True, exist_ok=True)

        W, H = 1080, 1920   # vertical

        # ── Step 1: Generate the 100-130 word script ─────
        progress(5, "Drafting Short script...")
        from engines import script as script_engine
        api_key = cfg.get("openrouter_api_key", "").strip()
        if not api_key:
            raise RuntimeError("OpenRouter key required for Shorts.")

        sc = script_engine.generate_short_script(api_key, idea,
                                                 target_words=target_words,
                                                 on_log=log)
        title  = sc["working_title"]
        script_text = sc["script"]
        if len(script_text) < 60:
            raise RuntimeError("Short script came back too tiny — try a different topic.")
        (workspace / "script.txt").write_text(script_text)

        # ── Step 2: Voiceover ────────────────────────────
        progress(15, "Generating voiceover...")
        vo_path = workspace / "voiceover.mp3"
        async def _tts():
            voice = _pick_voice(cfg)
            log(f"   🎙️ voice: {voice}")
            comm = edge_tts.Communicate(script_text, voice)
            await comm.save(str(vo_path))
        asyncio.run(_tts())

        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(vo_path)],
            capture_output=True, text=True,
        )
        duration = float(r.stdout.strip())
        log(f"✅ {duration:.1f}s narration")
        job["duration"] = f"0:{int(round(duration)):02d}"

        # ── Step 3: Captions (always on for Shorts) ──────
        captions_ass = None
        try:
            from engines import captions as cap_engine
            if cap_engine.is_available():
                progress(25, "Burning vertical captions...")
                cap_result = cap_engine.build(
                    vo_path, workspace,
                    model_name=cfg.get("caption_model", "base.en"),
                    style="shorts",
                    on_log=log,
                )
                captions_ass = cap_result["ass"]
                shutil.copyfile(cap_result["srt"], OUTPUT_DIR / f"{job_name}.srt")
            else:
                log("⚠️  faster-whisper not installed — skipping caption burn-in")
        except Exception as e:
            log(f"⚠️  caption build failed: {e}")

        # ── Step 4: Smart B-roll (vertical) ──────────────
        progress(35, "Fetching footage (vertical)...")
        footage_track = None
        if cfg.get("openrouter_api_key") and cfg.get("pexels_api_key"):
            try:
                from engines import footage as footage_engine
                br = footage_engine.build(
                    script=script_text, duration=duration, workspace=workspace,
                    openrouter_key=cfg["openrouter_api_key"],
                    pexels_key=cfg["pexels_api_key"],
                    pixabay_key=cfg.get("pixabay_api_key", ""),
                    width=W, height=H,
                    target_chunk_secs=8.0,
                    motion=cfg.get("motion_effect", "pan"),
                    on_log=log,
                )
                footage_track = br["track"]
            except Exception as e:
                log(f"⚠️  smart b-roll failed: {e}")

        if footage_track is None:
            # Fallback to a dark vertical card
            fallback = workspace / "processed" / "fallback.mp4"
            fallback.parent.mkdir(exist_ok=True)
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=0x0a0a0a:size={W}x{H}:rate=30:duration={duration}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(fallback),
            ], capture_output=True)
            footage_track = fallback

        # ── Step 5: Final assembly ───────────────────────
        progress(70, "Rendering Short...")
        final_mp4 = OUTPUT_DIR / f"{job_name}.mp4"
        sub_chain = "subtitles=captions.ass," if captions_ass else ""
        audio_polish = cfg.get("audio_polish", True)

        filter_parts = []
        if sub_chain:
            filter_parts.append(f"[0:v]{sub_chain[:-1]}[v]")
            video_map = ["-map", "[v]"]
        else:
            video_map = ["-map", "0:v"]

        # Shorts: no music, but still loudnorm the voice when polish is on.
        if audio_polish:
            filter_parts.append("[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
            audio_map = ["-map", "[aout]"]
        else:
            audio_map = ["-map", "1:a"]

        cmd = ["ffmpeg", "-y", "-i", str(footage_track), "-i", str(vo_path)]
        if filter_parts:
            cmd += ["-filter_complex", ";".join(filter_parts)]
        cmd += [
            "-t", f"{duration:.3f}",
            *video_map, *audio_map,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-pix_fmt", "yuv420p",
            str(final_mp4),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                cwd=str(workspace))
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed:\n{result.stderr[-1500:]}")

        # Optional Shorts branding (separate vertical slots)
        if cfg.get("apply_branding", True):
            try:
                from engines import branding
                if branding.has_slot("short_intro") or branding.has_slot("short_outro"):
                    progress(83, "Adding Shorts intro / outro...")
                    unbranded = workspace / "main_unbranded.mp4"
                    final_mp4.rename(unbranded)
                    branding.apply_for_video_kind(
                        unbranded, final_mp4,
                        kind="short", width=W, height=H, on_log=log,
                    )
            except Exception as e:
                log(f"⚠️  Shorts branding failed: {e}")

        # ── Step 6: Vertical thumbnail ───────────────────
        progress(88, "Generating vertical thumbnail...")
        thumb = OUTPUT_DIR / f"{job_name}_thumbnail.jpg"
        try:
            from engines import thumbnail as thumb_engine
            thumb_engine.generate(api_key, title, thumb, vertical=True,
                                  on_log=log)
        except Exception as e:
            log(f"⚠️  vertical thumbnail failed: {e}")

        # ── Step 7: Metadata ─────────────────────────────
        progress(95, "Saving metadata...")
        description = (
            f"{title}\n\n"
            f"{script_text[:200]}...\n\n"
            "🔔 Subscribe to Obscura Vault for buried history.\n\n"
            "#Shorts #ObscuraVault #HiddenHistory #DarkHistory"
        )
        tags = ["shorts", "obscura vault", "hidden history",
                "dark history", "untold history",
                *[w.lower() for w in title.split() if len(w) > 3]]
        meta = {"title": title, "description": description,
                "tags": list(dict.fromkeys(tags)), "category": "27",
                "duration_s": round(duration), "shorts": True}
        (workspace / "metadata.json").write_text(json.dumps(meta, indent=2))
        (workspace / "description.txt").write_text(description)

        # ── Step 8: Auto-upload (if enabled) ─────────────
        upload_result = None
        if cfg.get("auto_upload"):
            try:
                from engines import upload as up
                if up.is_installed() and up.has_token():
                    progress(98, "Uploading Short...")
                    srt_sib = OUTPUT_DIR / f"{job_name}.srt"
                    upload_result = up.publish(
                        final_mp4, title=title, description=description,
                        tags=meta["tags"],
                        thumbnail_path=(thumb if thumb.exists() else None),
                        caption_srt_path=(srt_sib if srt_sib.exists() else None),
                        privacy_status=cfg.get("default_privacy", "private"),
                        contains_synthetic_media=cfg.get(
                            "contains_synthetic_media", True),
                        idea_id=cfg.get("_idea_id"),
                        on_log=log,
                    )
            except Exception as e:
                log(f"⚠️  auto-upload failed: {e}")

        mb = final_mp4.stat().st_size / 1024 / 1024
        job["result"] = {
            "video":       final_mp4.name,
            "thumbnail":   thumb.name,
            "description": description,
            "tags":        meta["tags"],
            "duration":    f"0:{int(round(duration)):02d}",
            "size_mb":     round(mb, 1),
            "job_name":    job_name,
            "youtube":     upload_result,
            "shorts":      True,
        }

        # Workspace cleanup for Shorts too
        if cfg.get("auto_cleanup_workspace", True):
            try:
                from engines import storage as storage_engine
                cr = storage_engine.cleanup_workspace(job_name)
                if cr.get("ok"):
                    log(f"🧹 freed {cr['freed_mb']} MB from workspace")
            except Exception as e:
                log(f"⚠️  workspace cleanup failed: {e}")
        try:
            from engines import storage as storage_engine
            cap_gb = float(cfg.get("output_cap_gb", 30.0))
            cap_r  = storage_engine.enforce_output_cap(cap_gb)
            if cap_r.get("deleted"):
                log(f"🧹 rolled output under {cap_gb} GB ({cap_r['deleted']} deleted)")
        except Exception as e:
            log(f"⚠️  output cap enforcement failed: {e}")

        progress(100, "Short ready! 🎬")
        job["status"] = "done"
        _sse_publish(job_id, "done", {"result": job["result"]})
        try:
            jobs_db.upsert_job(
                job_id, status="done", progress=100, stage="Short ready!",
                finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                result=job["result"],
                duration_s=int(round(duration)),
            )
        except Exception:
            pass

    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ {e}")
        job["log"].append(traceback.format_exc())
        _sse_publish(job_id, "error", {"error": str(e)})
        try:
            jobs_db.upsert_job(
                job_id, status="error", error=str(e),
                finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            jobs_db.append_log(job_id, f"❌ ERROR: {e}")
        except Exception:
            pass
    finally:
        _running_job.discard(job_id)


@app.route("/api/run-short", methods=["POST"])
def run_short():
    data = request.json or {}
    idea = (data.get("idea") or "").strip()
    target_words = int(data.get("target_words") or 110)

    if len(idea) < 8:
        return jsonify({"error": "Idea too short (min 8 chars)."}), 400
    if not (60 <= target_words <= 220):
        return jsonify({"error": "target_words must be between 60 and 220"}), 400

    cfg = load_config()
    if not cfg.get("openrouter_api_key", "").strip():
        return jsonify({"error": "OpenRouter key required."}), 400

    job_id = "sh_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(4)
    queue_pos = _job_queue.qsize() + (1 if _running_job else 0)
    with jobs_lock:
        jobs[job_id] = {
            "status": "queued", "progress": 0,
            "stage": f"Queued (position {queue_pos + 1})",
            "log": [], "result": None, "error": None, "duration": None,
            "queue_pos": queue_pos,
        }
    _job_queue.put(("short", job_id, idea, target_words, cfg))
    return jsonify({"job_id": job_id, "queue_pos": queue_pos})


# ── Run pipeline ─────────────────────────────────────────
@app.route("/api/run", methods=["POST"])
def run_pipeline():
    data   = request.json
    title  = (data.get("title") or "").strip()
    script = (data.get("script") or "").strip()

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(script) < 100:
        return jsonify({"error": "Script too short (minimum 100 characters)"}), 400

    job_id    = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(4)
    cfg       = load_config()
    queue_pos = _job_queue.qsize() + (1 if _running_job else 0)
    with jobs_lock:
        jobs[job_id] = {
            "status": "queued", "progress": 0,
            "stage": f"Queued (position {queue_pos + 1})",
            "log": [], "result": None, "error": None, "duration": None,
            "queue_pos": queue_pos,
        }
    _job_queue.put(("long", job_id, title, script, cfg))
    return jsonify({"job_id": job_id, "queue_pos": queue_pos})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if job:
        return jsonify({
            "status":   job["status"],
            "progress": job["progress"],
            "stage":    job["stage"],
            "log":      job["log"][-30:],
            "result":   job["result"],
            "error":    job["error"],
            "duration": job.get("duration"),
        })
    # Fall back to SQLite — job may be from a previous server session
    from engines import jobs as jobs_db
    db_job = jobs_db.get_job(job_id)
    if not db_job:
        return jsonify({"error": "Job not found"}), 404
    log_lines = [l for l in (db_job.get("log") or "").split("\n") if l]
    return jsonify({
        "status":   db_job.get("status", "unknown"),
        "progress": db_job.get("progress", 0),
        "stage":    db_job.get("stage", ""),
        "log":      log_lines[-30:],
        "result":   db_job.get("result"),
        "error":    db_job.get("error"),
        "duration": db_job.get("duration_s"),
    })

# ── Server-Sent Events ───────────────────────────────────
@app.route("/api/events/<job_id>")
def job_events(job_id):
    """
    SSE stream for a single job.  The client receives:
      - "progress"  {pct, stage}        on every progress() call
      - "log"       {line}              on every log() call
      - "done"      {result}            when job finishes successfully
      - "error"     {error}             when job finishes with error
      - "ping"      {}                  every 15 s (keep-alive)
    """
    client_q: _queue.Queue = _queue.Queue(maxsize=200)
    with _sse_lock:
        _sse_queues.setdefault(job_id, []).append(client_q)

    # Immediately replay current state so a reconnecting client is in sync
    with jobs_lock:
        job = jobs.get(job_id)
    if job:
        for line in job["log"][-50:]:
            client_q.put_nowait(json.dumps({"type": "log", "line": line}))
        client_q.put_nowait(json.dumps({
            "type": "progress", "pct": job["progress"], "stage": job["stage"]
        }))
        if job["status"] == "done":
            client_q.put_nowait(json.dumps({"type": "done", "result": job["result"]}))
        elif job["status"] == "error":
            client_q.put_nowait(json.dumps({"type": "error", "error": job["error"]}))

    def generate():
        try:
            import time as _time
            last_ping = _time.monotonic()
            while True:
                try:
                    payload = client_q.get(timeout=15)
                    yield f"data: {payload}\n\n"
                    data = json.loads(payload)
                    if data.get("type") in ("done", "error"):
                        break
                except _queue.Empty:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        finally:
            with _sse_lock:
                lst = _sse_queues.get(job_id, [])
                if client_q in lst:
                    lst.remove(client_q)
                if not lst:
                    _sse_queues.pop(job_id, None)

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Install packages helper ──────────────────────────────
@app.route("/api/install", methods=["POST"])
def install_packages():
    packages = ["edge-tts", "moviepy", "requests", "Pillow", "flask"]
    cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages"] + packages
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return jsonify({"ok": result.returncode == 0, "output": result.stdout[-2000:]})

# ════════════════════════════════════════════════════════
#  AI / OpenRouter routes
# ════════════════════════════════════════════════════════

@app.route("/api/openrouter/validate", methods=["POST"])
def validate_openrouter():
    import llm
    key = (request.json or {}).get("key", "").strip()
    return jsonify({"valid": llm.validate_key(key)})


# Async script-generation jobs (separate from video pipeline jobs).
script_jobs = {}   # job_id -> {status, log, result, error}


def _run_script_job(job_id: str, idea: str, minutes: float, api_key: str,
                    use_research: bool = False):
    from engines import script as script_engine
    from engines import seo    as seo_engine
    job = script_jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[script {job_id}] {msg}")

    try:
        if not api_key:
            raise RuntimeError("OpenRouter key not set in Settings.")

        research_pack = None
        if use_research:
            from engines import research as research_engine
            research_pack = research_engine.build_research_pack(
                api_key, idea, on_log=log)

        sc = script_engine.generate_script(
            api_key, idea, minutes,
            research_pack=research_pack,
            on_log=log,
        )

        # Use planned duration to stamp chapters; the real audio duration
        # will be re-stamped by the video pipeline if it differs significantly.
        total_secs = (sc["word_count"] / script_engine.WORDS_PER_MINUTE) * 60
        seo = seo_engine.build_seo_pack(api_key, idea, sc["outline"],
                                        total_secs, on_log=log)

        job["result"] = {
            "title":               seo["title"],
            "title_alternatives":  seo["title_alternatives"],
            "script":              sc["script"],
            "word_count":          sc["word_count"],
            "outline":             sc["outline"],
            "description":         seo["description"],
            "tags":                seo["tags"],
            "chapters":            seo["chapters"],
            "primary_keyword":     seo["primary_keyword"],
            "model":               sc["model"],
            "warning":             sc.get("warning"),
        }
        job["status"] = "done"
        log("✅ done")

    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ {e}")
        job["log"].append(traceback.format_exc()[-1500:])


@app.route("/api/generate-script", methods=["POST"])
def generate_script_route():
    data    = request.json or {}
    idea    = (data.get("idea") or "").strip()
    minutes = float(data.get("minutes") or 10.0)
    use_research = bool(data.get("research", False))

    if len(idea) < 8:
        return jsonify({"error": "Idea is too short (min 8 chars)."}), 400
    if not (1 <= minutes <= 30):
        return jsonify({"error": "Minutes must be between 1 and 30."}), 400

    cfg = load_config()
    api_key = cfg.get("openrouter_api_key", "").strip()
    if not api_key:
        return jsonify({"error": "Set your OpenRouter key in Settings first."}), 400

    job_id = "s_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    script_jobs[job_id] = {
        "status": "running", "log": [], "result": None, "error": None,
    }
    threading.Thread(
        target=_run_script_job,
        args=(job_id, idea, minutes, api_key, use_research),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.route("/api/script-status/<job_id>")
def script_status(job_id):
    job = script_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "log":    job["log"][-30:],
        "result": job["result"],
        "error":  job["error"],
    })


# ── Standalone thumbnail preview (no full pipeline) ──────
thumb_jobs = {}   # job_id -> {status, log, result, error}


def _run_thumb_job(job_id: str, title: str, variants: int, api_key: str):
    from engines import thumbnail as thumb_engine
    job = thumb_jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[thumb {job_id}] {msg}")

    try:
        slug = re.sub(r"[^\w\-]+", "_", title.lower())[:40] or "preview"
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        out  = OUTPUT_DIR / f"preview_{ts}_{slug}.jpg"
        result = thumb_engine.generate(api_key, title, out,
                                       variants=variants, on_log=log)
        job["result"] = {
            "primary":      Path(result["primary"]).name,
            "variants":     [Path(p).name for p in result["variants"]],
            "punchline":    result["punchline"],
            "image_prompt": result["image_prompt"],
        }
        job["status"] = "done"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ {e}")
        job["log"].append(traceback.format_exc()[-1500:])


@app.route("/api/test-thumbnail", methods=["POST"])
def test_thumbnail():
    data     = request.json or {}
    title    = (data.get("title") or "").strip()
    variants = int(data.get("variants") or 1)

    if len(title) < 4:
        return jsonify({"error": "Title too short."}), 400
    cfg = load_config()
    api_key = cfg.get("openrouter_api_key", "").strip()
    if not api_key:
        return jsonify({"error": "Set OpenRouter key in Settings first."}), 400

    job_id = "t_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    thumb_jobs[job_id] = {
        "status": "running", "log": [], "result": None, "error": None,
    }
    threading.Thread(
        target=_run_thumb_job,
        args=(job_id, title, max(1, min(variants, 3)), api_key),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.route("/api/thumb-status/<job_id>")
def thumb_status(job_id):
    job = thumb_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "log":    job["log"][-30:],
        "result": job["result"],
        "error":  job["error"],
    })


# ── Captions: status + install dependency ───────────────
@app.route("/api/captions/status", methods=["GET"])
def captions_status():
    from engines import captions as cap
    return jsonify({"available": cap.is_available()})


# Install jobs (so the UI can stream pip output without a long blocking req)
install_jobs = {}


def _run_install_captions(job_id: str):
    job = install_jobs[job_id]
    cmd = [sys.executable, "-m", "pip", "install",
           "--break-system-packages", "faster-whisper"]
    job["log"].append("$ " + " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        try:
            stdout, _ = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
            job["log"].append("⚠️ Install timed out (5 min)")
        for line in stdout.splitlines():
            if line.strip():
                job["log"].append(line)
        if len(job["log"]) > 400:
            job["log"] = job["log"][-300:]
        job["status"] = "done" if proc.returncode == 0 else "error"
        if proc.returncode != 0:
            job["error"] = f"pip exited {proc.returncode}"
    except Exception as e:
        job["status"] = "error"
        job["error"]  = str(e)


@app.route("/api/captions/install", methods=["POST"])
def captions_install():
    job_id = "i_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    install_jobs[job_id] = {"status": "running", "log": [], "error": None}
    threading.Thread(target=_run_install_captions, args=(job_id,),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/captions/install-status/<job_id>")
def captions_install_status(job_id):
    job = install_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "log":    job["log"][-50:],
        "error":  job["error"],
    })


# ════════════════════════════════════════════════════════
#  YouTube upload routes
# ════════════════════════════════════════════════════════

@app.route("/api/youtube/status", methods=["GET"])
def yt_status():
    from engines import upload as up
    info = up.channel_info() if (up.is_installed() and up.has_token()) else None
    return jsonify({
        "installed":   up.is_installed(),
        "has_secrets": up.has_secrets(),
        "has_token":   up.has_token(),
        "channel":     info,
    })


def _run_install_youtube(job_id: str):
    job = install_jobs[job_id]
    cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages",
           "google-api-python-client", "google-auth-oauthlib", "google-auth-httplib2"]
    job["log"].append("$ " + " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        try:
            stdout, _ = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
            job["log"].append("⚠️ Install timed out (5 min)")
        for line in stdout.splitlines():
            if line.strip():
                job["log"].append(line)
        if len(job["log"]) > 400:
            job["log"] = job["log"][-300:]
        job["status"] = "done" if proc.returncode == 0 else "error"
        if proc.returncode != 0:
            job["error"] = f"pip exited {proc.returncode}"
    except Exception as e:
        job["status"] = "error"
        job["error"]  = str(e)


@app.route("/api/youtube/install", methods=["POST"])
def yt_install():
    job_id = "yi_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    install_jobs[job_id] = {"status": "running", "log": [], "error": None}
    threading.Thread(target=_run_install_youtube, args=(job_id,),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/youtube/install-status/<job_id>")
def yt_install_status(job_id):
    job = install_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "log":    job["log"][-50:],
        "error":  job["error"],
    })


@app.route("/api/youtube/upload-secrets", methods=["POST"])
def yt_upload_secrets():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    raw = f.read()
    try:
        parsed = json.loads(raw)
    except Exception:
        return jsonify({"error": "Not valid JSON."}), 400
    if not (parsed.get("installed") or parsed.get("web")):
        return jsonify({"error": "Doesn't look like an OAuth client_secrets file."}), 400

    from engines import upload as up
    up.SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    up.CLIENT_SECRETS_PATH.write_bytes(raw)
    # Wipe any old token — wrong client.
    if up.TOKEN_PATH.exists():
        up.TOKEN_PATH.unlink()
    return jsonify({"ok": True})


# Authorization is async because run_local_server() blocks on the
# user clicking through the consent screen.
auth_jobs = {}


def _run_authorize(job_id: str):
    from engines import upload as up
    job = auth_jobs[job_id]
    try:
        up.authorize(open_browser=True)
        job["status"] = "done"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(traceback.format_exc()[-1500:])


@app.route("/api/youtube/authorize", methods=["POST"])
def yt_authorize():
    from engines import upload as up
    if not up.is_installed():
        return jsonify({"error": "Install YouTube libs first."}), 400
    if not up.has_secrets():
        return jsonify({"error": "Upload client_secrets.json first."}), 400

    job_id = "ya_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    auth_jobs[job_id] = {"status": "running", "log": [], "error": None}
    threading.Thread(target=_run_authorize, args=(job_id,), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/youtube/auth-status/<job_id>")
def yt_auth_status(job_id):
    job = auth_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "log":    job["log"][-30:],
        "error":  job["error"],
    })


@app.route("/api/youtube/revoke", methods=["POST"])
def yt_revoke():
    from engines import upload as up
    up.revoke_token()
    return jsonify({"ok": True})


# Upload jobs (real video → YouTube)
yt_upload_jobs = {}


def _run_yt_upload(job_id: str, video_filename: str, options: dict):
    from engines import upload as up
    job = yt_upload_jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[yt-up {job_id}] {msg}")

    def progress(pct):
        job["progress"] = pct

    try:
        video_path = OUTPUT_DIR / video_filename
        if not video_path.exists():
            raise FileNotFoundError(f"video not found: {video_filename}")

        # Look for sibling assets
        stem  = video_path.stem
        thumb = OUTPUT_DIR / f"{stem}_thumbnail.jpg"
        srt   = OUTPUT_DIR / f"{stem}.srt"

        # Pull metadata from workspace if it exists (best source for title/desc/tags)
        workspace_meta = WORKSPACE / stem / "metadata.json"
        if workspace_meta.exists():
            meta = json.loads(workspace_meta.read_text())
        else:
            meta = {
                "title": options.get("title") or stem,
                "description": options.get("description") or "",
                "tags": options.get("tags") or [],
            }

        title       = options.get("title")       or meta.get("title")       or stem
        description = options.get("description") or meta.get("description") or ""
        tags        = options.get("tags")        or meta.get("tags")        or []

        result = up.publish(
            video_path,
            title=title, description=description, tags=tags,
            thumbnail_path=(thumb if thumb.exists() else None),
            caption_srt_path=(srt if srt.exists() else None),
            privacy_status=options.get("privacy_status", "private"),
            publish_at=options.get("publish_at") or None,
            contains_synthetic_media=options.get("contains_synthetic_media", True),
            on_progress=progress, on_log=log,
        )
        job["result"] = result
        job["status"] = "done"

    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ {e}")
        job["log"].append(traceback.format_exc()[-1500:])


@app.route("/api/youtube/upload-video", methods=["POST"])
def yt_upload_video():
    data = request.json or {}
    video_filename = data.get("video", "")
    if not video_filename:
        return jsonify({"error": "video filename required"}), 400

    from engines import upload as up
    if not (up.is_installed() and up.has_token()):
        return jsonify({"error": "YouTube not authorized."}), 400

    options = {
        "title":          data.get("title"),
        "description":    data.get("description"),
        "tags":           data.get("tags"),
        "privacy_status": data.get("privacy_status", "private"),
        "publish_at":     data.get("publish_at"),
        "contains_synthetic_media": data.get("contains_synthetic_media", True),
    }

    job_id = "yu_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    yt_upload_jobs[job_id] = {
        "status": "running", "progress": 0, "log": [], "result": None, "error": None,
    }
    threading.Thread(target=_run_yt_upload,
                     args=(job_id, video_filename, options), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/youtube/upload-status/<job_id>")
def yt_upload_status(job_id):
    job = yt_upload_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status":   job["status"],
        "progress": job.get("progress", 0),
        "log":      job["log"][-30:],
        "result":   job["result"],
        "error":    job["error"],
    })


# ════════════════════════════════════════════════════════
#  Idea engine routes
# ════════════════════════════════════════════════════════

idea_jobs = {}   # harvest jobs


def _run_harvest(job_id: str, params: dict, openrouter_key: str):
    from engines import ideas as I
    job = idea_jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[ideas {job_id}] {msg}")

    try:
        result = I.run_harvest(
            yt_seeds=params.get("yt_seeds") or None,
            subreddits=params.get("subreddits") or None,
            include_wikipedia=bool(params.get("include_wikipedia", True)),
            score_with_openrouter_key=openrouter_key,
            niche=params.get("niche") or I.DEFAULT_NICHE,
            on_log=log,
        )
        job["result"] = result
        job["status"] = "done"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ {e}")
        job["log"].append(traceback.format_exc()[-1500:])


@app.route("/api/ideas/harvest", methods=["POST"])
def ideas_harvest():
    data = request.json or {}
    cfg  = load_config()
    job_id = "h_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    idea_jobs[job_id] = {
        "status": "running", "log": [], "result": None, "error": None,
    }
    threading.Thread(
        target=_run_harvest,
        args=(job_id, data, cfg.get("openrouter_api_key", "").strip()),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.route("/api/ideas/harvest-status/<job_id>")
def ideas_harvest_status(job_id):
    job = idea_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "log":    job["log"][-30:],
        "result": job["result"],
        "error":  job["error"],
    })


@app.route("/api/ideas/list", methods=["GET"])
def ideas_list():
    from engines import ideas as I
    items = I.list_all()
    status_filter = request.args.get("status", "")
    if status_filter:
        items = [it for it in items if it.get("status") == status_filter]
    return jsonify(items)


@app.route("/api/ideas/<idea_id>/status", methods=["POST"])
def ideas_set_status(idea_id):
    from engines import ideas as I
    new_status = (request.json or {}).get("status", "")
    if new_status not in {"pending", "approved", "rejected", "produced"}:
        return jsonify({"error": "bad status"}), 400
    patch = {}
    for k in ("job_name", "video_id"):
        if k in (request.json or {}):
            patch[k] = request.json[k]
    it = I.update_status(idea_id, new_status, **patch)
    if not it:
        return jsonify({"error": "not found"}), 404
    return jsonify(it)


@app.route("/api/ideas/<idea_id>", methods=["DELETE"])
def ideas_delete(idea_id):
    from engines import ideas as I
    if I.delete(idea_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


# Approve & Generate: chain idea → script → video pipeline.
def _run_idea_to_video(job_id: str, idea: dict, minutes: float, cfg: dict):
    from engines import script as script_engine
    from engines import seo    as seo_engine
    from engines import ideas  as I

    job = script_jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[idea-pipe {job_id}] {msg}")

    try:
        api_key = cfg.get("openrouter_api_key", "").strip()
        if not api_key:
            raise RuntimeError("OpenRouter key missing")

        log(f"📜 generating script for: {idea['title'][:90]}")
        research_pack = None
        if cfg.get("use_research", False):
            from engines import research as research_engine
            research_pack = research_engine.build_research_pack(
                api_key, idea["title"], on_log=log)

        sc = script_engine.generate_script(api_key, idea["title"], minutes,
                                           research_pack=research_pack,
                                           on_log=log)
        total_secs = (sc["word_count"] / script_engine.WORDS_PER_MINUTE) * 60
        seo = seo_engine.build_seo_pack(api_key, idea["title"], sc["outline"],
                                        total_secs, on_log=log)

        # Now kick off the actual video pipeline
        log("🎬 starting video pipeline...")
        pipeline_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        jobs[pipeline_id] = {
            "status": "running", "progress": 0, "stage": "Starting...",
            "log": [], "result": None, "error": None, "duration": None,
        }
        # Carry the idea_id transiently so auto-upload can record it
        # for analytics token-signal correlation.
        pipeline_cfg = dict(cfg)
        pipeline_cfg["_idea_id"] = idea["id"]
        t = threading.Thread(
            target=run_pipeline_thread,
            args=(pipeline_id, seo["title"], sc["script"], pipeline_cfg),
            daemon=True,
        )
        t.start()

        # Mark idea as approved → produced (we don't wait for the
        # pipeline to finish; UI tracks the pipeline separately).
        I.update_status(idea["id"], "approved",
                        pipeline_job=pipeline_id,
                        scripted_title=seo["title"])
        job["result"] = {
            "title":       seo["title"],
            "pipeline_id": pipeline_id,
            "word_count":  sc["word_count"],
        }
        job["status"] = "done"
        log(f"   ✅ pipeline {pipeline_id} running in background")

    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ {e}")
        job["log"].append(traceback.format_exc()[-1500:])


# ════════════════════════════════════════════════════════
#  Analytics routes
# ════════════════════════════════════════════════════════

analytics_jobs = {}


def _run_analytics_refresh(job_id: str):
    from engines import analytics
    job = analytics_jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[analytics {job_id}] {msg}")

    try:
        result = analytics.refresh_metrics(on_log=log)
        job["result"] = result
        job["status"] = "done"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ {e}")
        job["log"].append(traceback.format_exc()[-1500:])


@app.route("/api/analytics/refresh", methods=["POST"])
def analytics_refresh():
    job_id = "an_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    analytics_jobs[job_id] = {
        "status": "running", "log": [], "result": None, "error": None,
    }
    threading.Thread(target=_run_analytics_refresh, args=(job_id,),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/analytics/refresh-status/<job_id>")
def analytics_refresh_status(job_id):
    job = analytics_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "log":    job["log"][-30:],
        "result": job["result"],
        "error":  job["error"],
    })


@app.route("/api/analytics/list", methods=["GET"])
def analytics_list():
    from engines import analytics
    return jsonify({
        "uploads": analytics.list_uploads(),
        "metrics": analytics.list_metrics(),
    })


@app.route("/api/analytics/signals", methods=["GET"])
def analytics_signals():
    from engines import analytics
    return jsonify(analytics.compute_token_signals())


@app.route("/api/ideas/<idea_id>/produce", methods=["POST"])
def ideas_produce(idea_id):
    from engines import ideas as I
    minutes = float((request.json or {}).get("minutes") or 10.0)

    items = [it for it in I.list_all() if it["id"] == idea_id]
    if not items:
        return jsonify({"error": "idea not found"}), 404
    idea = items[0]

    cfg = load_config()
    if not cfg.get("openrouter_api_key", "").strip():
        return jsonify({"error": "OpenRouter key missing"}), 400

    # Check no other pipeline running
    for jid, j in jobs.items():
        if j["status"] == "running":
            return jsonify({"error": "A video is already being generated."}), 409

    job_id = "ip_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    script_jobs[job_id] = {
        "status": "running", "log": [], "result": None, "error": None,
    }
    threading.Thread(
        target=_run_idea_to_video,
        args=(job_id, idea, minutes, cfg),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


# ════════════════════════════════════════════════════════
#  Scheduler routes
# ════════════════════════════════════════════════════════

def _scheduler_produce_idea(idea: dict, minutes: float, video_format: str = "long"):
    """Runtime callback the scheduler uses to start the produce flow."""
    from engines import ideas as I
    cfg = load_config()

    if video_format == "short":
        pipeline_id = "sh_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        jobs[pipeline_id] = {
            "status": "running", "progress": 0, "stage": "Starting Short...",
            "log": [], "result": None, "error": None, "duration": None,
        }
        pipeline_cfg = dict(cfg)
        pipeline_cfg["_idea_id"] = idea["id"]
        
        # Mark as approved so the scheduler doesn't pick it again
        I.update_status(idea["id"], "approved", pipeline_job=pipeline_id)
        
        threading.Thread(
            target=run_short_pipeline_thread,
            args=(pipeline_id, idea["title"], 110, pipeline_cfg),
            daemon=True,
        ).start()
    else:
        job_id = "ip_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        script_jobs[job_id] = {
            "status": "running", "log": [], "result": None, "error": None,
        }
        threading.Thread(
            target=_run_idea_to_video,
            args=(job_id, idea, minutes, cfg),
            daemon=True,
        ).start()


def _scheduler_runtime():
    return {
        "pipeline_jobs": lambda: jobs,
        "produce_idea":  _scheduler_produce_idea,
    }


# ════════════════════════════════════════════════════════
#  Branding (intro / outro stings)
# ════════════════════════════════════════════════════════

BRANDING_UPLOADS = BASE_DIR / "data" / "branding" / "_uploads"
BRANDING_UPLOADS.mkdir(parents=True, exist_ok=True)
brand_jobs = {}


@app.route("/api/branding/list", methods=["GET"])
def branding_list():
    from engines import branding
    return jsonify(branding.list_slots())


def _run_branding_normalize(job_id: str, src_path: Path, slot: str):
    from engines import branding
    job = brand_jobs[job_id]
    try:
        branding.normalize_clip(src_path, slot)
        try:
            src_path.unlink()
        except Exception:
            pass
        job["status"] = "done"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(traceback.format_exc()[-1500:])


@app.route("/api/branding/upload", methods=["POST"])
def branding_upload():
    from engines import branding
    slot = request.form.get("slot", "")
    if slot not in branding.VALID_SLOTS:
        return jsonify({"error": "bad slot"}), 400
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".m4v")):
        return jsonify({"error": "needs to be mp4/mov/mkv/webm/m4v"}), 400

    tmp = BRANDING_UPLOADS / f"upload_{slot}_{int(datetime.now().timestamp())}{Path(f.filename).suffix}"
    f.save(str(tmp))

    job_id = "br_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    brand_jobs[job_id] = {"status": "running", "log": [], "error": None}
    threading.Thread(target=_run_branding_normalize,
                     args=(job_id, tmp, slot), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/branding/upload-status/<job_id>")
def branding_upload_status(job_id):
    job = brand_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "error":  job["error"],
    })


@app.route("/api/branding/<slot>", methods=["DELETE"])
def branding_delete(slot):
    from engines import branding
    if slot not in branding.VALID_SLOTS:
        return jsonify({"error": "bad slot"}), 400
    branding.delete_slot(slot)
    return jsonify({"ok": True})


@app.route("/api/branding/preview/<slot>")
def branding_preview(slot):
    from engines import branding
    if slot not in branding.VALID_SLOTS:
        return jsonify({"error": "bad slot"}), 400
    p = branding.slot_path(slot)
    if not p.exists():
        return jsonify({"error": "not found"}), 404
    return send_file(str(p), mimetype="video/mp4")


# ════════════════════════════════════════════════════════
#  Performance Review (LLM scorecard)
# ════════════════════════════════════════════════════════

review_jobs = {}


def _run_review(job_id: str, video_filename: str, api_key: str):
    from engines import review as rev
    job = review_jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[review {job_id}] {msg}")

    try:
        result = rev.review(api_key, video_filename, on_log=log)
        job["result"] = result
        job["status"] = "done"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ {e}")
        job["log"].append(traceback.format_exc()[-1500:])


@app.route("/api/review-video", methods=["POST"])
def review_video_route():
    data = request.json or {}
    video = (data.get("video") or "").strip()
    if not video:
        return jsonify({"error": "video required"}), 400

    cfg = load_config()
    api_key = cfg.get("openrouter_api_key", "").strip()
    if not api_key:
        return jsonify({"error": "OpenRouter key missing"}), 400

    job_id = "rv_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    review_jobs[job_id] = {
        "status": "running", "log": [], "result": None, "error": None,
    }
    threading.Thread(target=_run_review,
                     args=(job_id, video, api_key), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/review-status/<job_id>")
def review_status_route(job_id):
    job = review_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "log":    job["log"][-30:],
        "result": job["result"],
        "error":  job["error"],
    })


@app.route("/api/jobs/list", methods=["GET"])
def jobs_list_endpoint():
    from engines import jobs as jobs_db
    status = request.args.get("status") or None
    kind   = request.args.get("kind")   or None
    limit  = min(int(request.args.get("limit", 100)), 500)
    return jsonify(jobs_db.list_jobs(status=status, kind=kind, limit=limit))


@app.route("/api/jobs/<job_id>", methods=["GET"])
def jobs_get_endpoint(job_id):
    from engines import jobs as jobs_db
    item = jobs_db.get_job(job_id)
    if not item:
        return jsonify({"error": "not found"}), 404
    return jsonify(item)


@app.route("/api/jobs/cleanup", methods=["POST"])
def jobs_cleanup_endpoint():
    from engines import jobs as jobs_db
    keep = int((request.json or {}).get("keep_recent", 200))
    deleted = jobs_db.delete_old(keep_recent=keep)
    return jsonify({"deleted": deleted})


# ════════════════════════════════════════════════════════
#  Storage routes
# ════════════════════════════════════════════════════════

@app.route("/api/storage/usage", methods=["GET"])
def storage_usage_route():
    from engines import storage
    out = storage.usage()
    out["freeable"] = storage.estimate_freeable()
    return jsonify(out)


@app.route("/api/storage/cleanup", methods=["POST"])
def storage_cleanup_route():
    from engines import storage
    data = request.json or {}
    older = int(data.get("older_than_days", 0))
    cap_gb = data.get("output_cap_gb")
    out = {}
    out["workspaces"] = storage.cleanup_all_workspaces(older_than_days=older)
    if cap_gb is not None:
        out["output"] = storage.enforce_output_cap(float(cap_gb))
    return jsonify(out)


@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    from engines import analytics, ideas as I, scheduler as sched
    cfg = load_config()

    metrics = analytics.list_metrics()
    by_vid  = (metrics.get("by_video") or {})
    uploads = analytics.list_uploads()
    signals = analytics.compute_token_signals()
    sched_state = sched.get_state(cfg.get("scheduler", {}))
    all_ideas   = I.list_all()

    # Channel summary
    total_views = sum((m.get("views") or 0) for m in by_vid.values())
    total_subs  = sum((m.get("subs_gained") or 0) for m in by_vid.values())
    ctrs = [m.get("ctr") for m in by_vid.values() if m.get("ctr")]
    avd  = [m.get("avg_view_percent") for m in by_vid.values() if m.get("avg_view_percent")]
    avg_ctr = round(sum(ctrs) / len(ctrs), 2) if ctrs else 0
    avg_avd = round(sum(avd) / len(avd), 2) if avd else 0

    # Recent uploads (last 10)
    recent = sorted(uploads, key=lambda u: u.get("uploaded_at", ""),
                    reverse=True)[:10]
    for u in recent:
        u["metrics"] = by_vid.get(u.get("video_id"), {})

    # Top + bottom token signals (10 each)
    tok_items = sorted(
        signals.get("tokens", {}).items(),
        key=lambda x: x[1]["multiplier"], reverse=True,
    )
    top_tokens    = [{"token": t, **m} for t, m in tok_items[:10]]
    bottom_tokens = [{"token": t, **m} for t, m in tok_items[-10:]
                     if m.get("multiplier", 1) < 1.0]

    # Idea pool snapshot
    by_status = {"pending": 0, "approved": 0, "produced": 0, "rejected": 0}
    for it in all_ideas:
        by_status[it.get("status", "pending")] = by_status.get(
            it.get("status", "pending"), 0) + 1

    # Pipeline activity today
    today = datetime.now().strftime("%Y%m%d")
    todays_jobs = [j for jid, j in jobs.items() if jid.startswith(today)]
    done = sum(1 for j in todays_jobs if j.get("status") == "done")
    err  = sum(1 for j in todays_jobs if j.get("status") == "error")
    running = sum(1 for j in todays_jobs if j.get("status") == "running")

    # ── Storage usage ───────────────────────────────────
    storage_usage = {}
    try:
        from engines import storage as _storage
        storage_usage = _storage.usage()
        storage_usage["freeable"] = _storage.estimate_freeable()
    except Exception:
        pass

    # ── 14-day activity from jobs.db ────────────────────
    daily = []
    try:
        from engines import jobs as _jobs
        all_jobs = _jobs.list_jobs(limit=500)
        # bucket by yyyy-mm-dd
        from collections import defaultdict
        bucket = defaultdict(lambda: {"done": 0, "error": 0})
        for j in all_jobs:
            ts = (j.get("started_at") or "")[:10]
            if not ts:
                continue
            if j.get("status") == "done":
                bucket[ts]["done"] += 1
            elif j.get("status") == "error":
                bucket[ts]["error"] += 1
        # Generate the last 14 days even if some are zero
        from datetime import timedelta as _td
        today_d = datetime.now(timezone.utc).date()
        for i in range(13, -1, -1):
            d = (today_d - _td(days=i)).isoformat()
            daily.append({"date": d, "done": bucket[d]["done"],
                          "error": bucket[d]["error"]})
    except Exception:
        pass

    return jsonify({
        "channel": {
            "uploads_tracked":  len(uploads),
            "total_views":      total_views,
            "subs_gained":      total_subs,
            "avg_ctr":          avg_ctr,
            "avg_view_percent": avg_avd,
            "metrics_refreshed_at": metrics.get("refreshed_at"),
        },
        "recent_uploads":  recent,
        "top_tokens":      top_tokens,
        "bottom_tokens":   bottom_tokens,
        "idea_pool":       by_status,
        "scheduler":       sched_state["tasks"],
        "today_pipeline":  {"done": done, "errors": err, "running": running,
                            "total": len(todays_jobs)},
        "storage":         storage_usage,
        "daily_activity":  daily,
    })


@app.route("/api/scheduler/state", methods=["GET"])
def scheduler_state():
    from engines import scheduler as sched
    cfg = load_config()
    return jsonify(sched.get_state(cfg.get("scheduler", {})))


@app.route("/api/scheduler/trigger/<task_name>", methods=["POST"])
def scheduler_trigger(task_name):
    from engines import scheduler as sched
    res = sched.trigger_now(task_name, load_config, _scheduler_runtime())
    if "error" in res:
        return jsonify(res), 400
    return jsonify(res)


def _queue_worker() -> None:
    """Single background thread that serialises pipeline jobs from _job_queue."""
    while True:
        item = _job_queue.get()
        if item is None:
            break
        kind = item[0]
        try:
            if kind == "long":
                _, job_id, title, script, cfg = item
                with jobs_lock:
                    _running_job.add(job_id)
                    if job_id in jobs:
                        jobs[job_id]["status"] = "running"
                        jobs[job_id]["stage"]  = "Starting..."
                run_pipeline_thread(job_id, title, script, cfg)
            elif kind == "short":
                _, job_id, idea, target_words, cfg = item
                with jobs_lock:
                    _running_job.add(job_id)
                    if job_id in jobs:
                        jobs[job_id]["status"] = "running"
                        jobs[job_id]["stage"]  = "Starting Short..."
                run_short_pipeline_thread(job_id, idea, target_words, cfg)
        except Exception:
            pass
        finally:
            _job_queue.task_done()


if __name__ == "__main__":
    import webbrowser
    from engines import scheduler as sched
    from engines import jobs as jobs_db
    jobs_db.mark_orphans_failed()
    sched.start(load_config, _scheduler_runtime())

    # Start the serialised job queue worker
    threading.Thread(target=_queue_worker, daemon=True, name="job-queue-worker").start()

    print("\n" + "═"*55)
    print("  OBSCURA VAULT — Starting UI Server")
    print("  Opening http://localhost:5050 in your browser...")
    print("═"*55 + "\n")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5050")).start()
    host = "0.0.0.0" if "--lan" in sys.argv else "127.0.0.1"
    app.run(host=host, port=5050, debug=False)
