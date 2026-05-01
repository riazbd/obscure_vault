"""
OBSCURA VAULT — Web UI Backend Server
Serves the UI and exposes REST API endpoints that run the pipeline.
Cross-platform: Windows, Mac, Linux.
"""

import os
import sys
import re
import json
import shutil
import asyncio
import subprocess
import threading
import random
import platform
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, send_file

app = Flask(__name__, static_folder="ui")
BASE_DIR   = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
MUSIC_DIR  = BASE_DIR / "music"
OUTPUT_DIR = BASE_DIR / "output"
WORKSPACE  = BASE_DIR / "workspace"

for d in [MUSIC_DIR, OUTPUT_DIR, WORKSPACE]:
    d.mkdir(exist_ok=True)

# ── Job state (in-memory, single job at a time) ──────────
jobs = {}   # job_id -> {status, progress, log, result}


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
        "max_clips": 25
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

def run_pipeline_thread(job_id: str, title: str, script: str, cfg: dict):
    """Runs the full pipeline in a background thread, updating jobs[job_id]."""
    import requests as req_lib
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    import edge_tts

    job = jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[{job_id}] {msg}")

    def progress(pct, stage):
        job["progress"] = pct
        job["stage"] = stage
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
            comm = edge_tts.Communicate(script, cfg.get("tts_voice", "en-US-GuyNeural"))
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

        # ── Step 2: Footage ──────────────────────────────
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

        # ── Step 3: Music ────────────────────────────────
        progress(42, "Selecting background music...")
        music_path = None
        tracks = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
        if tracks:
            music_path = random.choice(tracks)
            log(f"✅ Music: {music_path.name}")
        else:
            log("ℹ️ No music files — voiceover only")

        # ── Step 4: Process footage ──────────────────────
        progress(45, "Processing and colour-grading footage clips...")
        proc_dir = workspace / "processed"
        proc_dir.mkdir(exist_ok=True)
        W, H = cfg.get("video_resolution", [1920, 1080])

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

        # Build footage track
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
            # Concat list
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

        # ── Step 5: Final assembly ───────────────────────
        progress(70, "Assembling final video...")
        final_mp4 = OUTPUT_DIR / f"{job_name}.mp4"
        music_vol = cfg.get("music_volume", 0.12)

        if music_path:
            audio_in  = ["-i", str(vo_path), "-i", str(music_path)]
            af        = (f"[1:a]aloop=loop=-1:size=2e+09,volume={music_vol}[m];"
                         f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=3[aout]")
            audio_map = ["-filter_complex", af, "-map", "0:v", "-map", "[aout]"]
        else:
            audio_in  = ["-i", str(vo_path)]
            audio_map = ["-map", "0:v", "-map", "1:a"]

        cmd = [
            "ffmpeg", "-y",
            "-i", str(footage_track),
            *audio_in,
            "-t", str(duration),
            *audio_map,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-pix_fmt", "yuv420p",
            str(final_mp4)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg assembly failed:\n{result.stderr[-2000:]}")

        mb = final_mp4.stat().st_size / 1024 / 1024
        log(f"✅ Video: {final_mp4.name} ({mb:.1f} MB)")
        progress(88, "Generating thumbnail...")

        # ── Step 6: Thumbnail ────────────────────────────
        thumb = OUTPUT_DIR / f"{job_name}_thumbnail.jpg"
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
        for f in footage_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass
        log("🗑️ Raw footage cleaned up")

        # ── Done ─────────────────────────────────────────
        job["result"] = {
            "video":       final_mp4.name,
            "thumbnail":   thumb.name,
            "description": description,
            "tags":        meta["tags"],
            "duration":    f"{m}:{s:02d}",
            "size_mb":     round(mb, 1),
            "job_name":    job_name,
        }
        progress(100, "Complete! 🎬")
        job["status"] = "done"

    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"]  = str(e)
        job["log"].append(f"❌ ERROR: {e}")
        job["log"].append(traceback.format_exc())


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
    dest = MUSIC_DIR / f.filename
    f.save(str(dest))
    return jsonify({"ok": True, "name": f.filename})

@app.route("/api/music/delete", methods=["POST"])
def delete_music():
    name = request.json.get("name", "")
    path = MUSIC_DIR / name
    if path.exists() and path.parent == MUSIC_DIR:
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
    path = OUTPUT_DIR / filename
    if path.exists():
        return send_file(str(path), as_attachment=True)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/outputs/thumbnail/<filename>")
def get_thumbnail(filename):
    path = OUTPUT_DIR / filename
    if path.exists():
        return send_file(str(path), mimetype="image/jpeg")
    return jsonify({"error": "Not found"}), 404

@app.route("/api/outputs/delete", methods=["POST"])
def delete_output():
    name  = request.json.get("name", "")
    path  = OUTPUT_DIR / name
    thumb = OUTPUT_DIR / name.replace(".mp4", "_thumbnail.jpg")
    if path.exists():
        path.unlink()
    if thumb.exists():
        thumb.unlink()
    return jsonify({"ok": True})

# ── Description for a video ──────────────────────────────
@app.route("/api/outputs/description/<job_name>")
def get_description(job_name):
    desc_path = WORKSPACE / job_name / "description.txt"
    if desc_path.exists():
        return jsonify({"description": desc_path.read_text()})
    return jsonify({"description": ""})

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

    # Check if a job is already running
    for jid, j in jobs.items():
        if j["status"] == "running":
            return jsonify({"error": "A video is already being generated. Please wait."}), 409

    job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg    = load_config()
    jobs[job_id] = {
        "status": "running", "progress": 0, "stage": "Starting...",
        "log": [], "result": None, "error": None, "duration": None
    }

    t = threading.Thread(target=run_pipeline_thread,
                         args=(job_id, title, script, cfg), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status":   job["status"],
        "progress": job["progress"],
        "stage":    job["stage"],
        "log":      job["log"][-30:],   # last 30 log lines
        "result":   job["result"],
        "error":    job["error"],
        "duration": job.get("duration"),
    })

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


def _run_script_job(job_id: str, idea: str, minutes: float, api_key: str):
    from engines import script as script_engine
    from engines import seo    as seo_engine
    job = script_jobs[job_id]

    def log(msg):
        job["log"].append(msg)
        print(f"[script {job_id}] {msg}")

    try:
        if not api_key:
            raise RuntimeError("OpenRouter key not set in Settings.")

        sc = script_engine.generate_script(api_key, idea, minutes, on_log=log)

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
        args=(job_id, idea, minutes, api_key),
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


if __name__ == "__main__":
    import webbrowser
    print("\n" + "═"*55)
    print("  OBSCURA VAULT — Starting UI Server")
    print("  Opening http://localhost:5050 in your browser...")
    print("═"*55 + "\n")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5050")).start()
    app.run(host="0.0.0.0", port=5050, debug=False)
