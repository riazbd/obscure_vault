"""
╔══════════════════════════════════════════════════════════════╗
║           OBSCURA VAULT — Automated Video Pipeline           ║
║     History They Buried. We Dig It Up.                       ║
╚══════════════════════════════════════════════════════════════╝

USAGE:
    python pipeline.py

    You will be prompted to enter:
      1. Video title
      2. Your script (paste it in, type END on a new line when done)

    The pipeline will then automatically:
      → Generate voiceover via Edge TTS (free, no signup)
      → Download footage from Pexels API (free)
      → Mix background music from your /music folder
      → Assemble final 1080p video with FFmpeg
      → Generate thumbnail
      → Save YouTube-ready metadata

REQUIREMENTS:
    pip install edge-tts moviepy requests Pillow
    ffmpeg must be installed on your system (sudo apt install ffmpeg)

FIRST TIME SETUP:
    1. Edit config.py and add your free Pexels API key (pexels.com/api)
    2. Drop dark ambient MP3s into the /music/ folder
    3. Run: python pipeline.py
"""

import os
import sys
import re
import json
import random
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import edge_tts

# ─────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
try:
    import config as cfg
except ImportError:
    print("ERROR: config.py not found. Copy config.example.py to config.py and fill in your API key.")
    sys.exit(1)


# ─────────────────────────────────────────────
# Pexels keyword map — picks search terms based
# on words found in your video title
# ─────────────────────────────────────────────
KEYWORD_MAP = {
    "war":         ["war ruins smoke", "battlefield", "military ruins"],
    "secret":      ["dark corridor", "vault door", "shadow mystery"],
    "death":       ["graveyard fog", "dark cemetery", "abandoned"],
    "disappear":   ["fog forest", "dark lake mist", "abandoned building"],
    "prison":      ["dark prison", "stone dungeon", "iron bars"],
    "ancient":     ["ancient ruins", "stone temple", "archaeology site"],
    "soviet":      ["soviet era building", "cold war bunker", "communist architecture"],
    "plague":      ["medieval street dark", "dramatic storm clouds", "empty city"],
    "nasa":        ["space dark", "night sky stars", "rocket launch"],
    "cia":         ["government building", "dark hallway", "washington monument"],
    "nuclear":     ["explosion cloud", "nuclear plant", "dramatic storm"],
    "experiment":  ["laboratory dark", "science equipment", "medical dark"],
    "cult":        ["dark forest night", "abandoned church", "fog night"],
    "ship":        ["stormy ocean", "shipwreck underwater", "dark sea"],
    "mountain":    ["mountain fog", "blizzard snow", "dark alpine"],
    "gold":        ["dark cave tunnel", "treasure", "mine tunnel"],
    "church":      ["gothic cathedral dark", "old monastery", "church interior"],
    "king":        ["medieval castle", "throne room", "royal fortress"],
    "hospital":    ["abandoned hospital", "dark corridor", "old medical"],
    "island":      ["isolated island fog", "remote coast dark", "ocean mist"],
    "code":        ["ancient scroll", "old manuscripts", "cryptic writing"],
    "spy":         ["dark alley", "surveillance camera", "city night shadows"],
    "cave":        ["dark cave", "underground cavern", "spelunking"],
    "poison":      ["laboratory chemicals", "dark liquid", "mysterious vial"],
    "default":     ["dramatic dark clouds", "abandoned historical building",
                    "old architecture mysterious", "dark fog landscape"],
}

ATMOSPHERIC = [
    "candle flame dark background",
    "old map parchment texture",
    "dramatic light rays dark room",
    "silhouette person mystery",
    "dark water reflection",
    "ancient stone wall texture",
    "dramatic thunderstorm",
    "foggy forest path night",
]


# ════════════════════════════════════════════════════════
#  STEP 1 — Collect title and script from user
# ════════════════════════════════════════════════════════

def collect_input():
    print("\n" + "═" * 58)
    print("  OBSCURA VAULT — Video Pipeline")
    print("  History They Buried. We Dig It Up.")
    print("═" * 58)

    title = input("\n📌 Enter video TITLE:\n> ").strip()
    if not title:
        print("Error: Title cannot be empty.")
        sys.exit(1)

    print("\n📝 Paste your SCRIPT below.")
    print("   Type  END  on its own line when done.\n")

    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)

    script = "\n".join(lines).strip()
    if len(script) < 100:
        print("Error: Script too short (min 100 characters).")
        sys.exit(1)

    wc  = len(script.split())
    est = int(wc / 2.4)   # ~144 wpm for Guy Neural
    print(f"\n✅ Script: {wc} words → ~{est//60}m {est%60}s narration")

    if wc < 700:
        print("⚠️  Warning: May produce video under 5 minutes (need ~720 words).")
    if wc > 2300:
        print("⚠️  Warning: May produce video over 15 minutes (need ~2160 words).")

    return title, script


# ════════════════════════════════════════════════════════
#  STEP 2 — Voiceover via Edge TTS
# ════════════════════════════════════════════════════════

async def _tts_async(script: str, path: Path):
    comm = edge_tts.Communicate(script, cfg.TTS_VOICE)
    await comm.save(str(path))

def generate_voiceover(script: str, workspace: Path) -> Path:
    print("\n🎙️  Generating voiceover (Edge TTS)...")
    out = workspace / "voiceover.mp3"
    asyncio.run(_tts_async(script, out))
    kb = out.stat().st_size // 1024
    print(f"   ✅ voiceover.mp3 ({kb} KB)")
    return out


# ════════════════════════════════════════════════════════
#  STEP 3 — Get audio duration
# ════════════════════════════════════════════════════════

def get_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    return float(r.stdout.strip())


# ════════════════════════════════════════════════════════
#  STEP 4 — Pick Pexels search keywords from title
# ════════════════════════════════════════════════════════

def pick_keywords(title: str) -> list:
    title_lower = title.lower()
    found = []
    for trigger, queries in KEYWORD_MAP.items():
        if trigger in title_lower:
            found.extend(random.sample(queries, min(2, len(queries))))
    if not found:
        found = list(KEYWORD_MAP["default"])
    found += random.sample(ATMOSPHERIC, 3)
    # deduplicate
    seen, unique = set(), []
    for k in found:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


# ════════════════════════════════════════════════════════
#  STEP 5 — Fetch footage from Pexels
# ════════════════════════════════════════════════════════

def pexels_search(query: str, n: int = 3) -> list:
    if not cfg.PEXELS_API_KEY or cfg.PEXELS_API_KEY == "YOUR_PEXELS_API_KEY_HERE":
        return []
    headers = {"Authorization": cfg.PEXELS_API_KEY}
    params  = {"query": query, "per_page": n,
                "orientation": "landscape", "size": "medium"}
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                         headers=headers, params=params, timeout=15)
        r.raise_for_status()
        clips = []
        for v in r.json().get("videos", []):
            files = sorted(
                [f for f in v.get("video_files", []) if f.get("width", 0) <= 1920],
                key=lambda x: x.get("width", 0), reverse=True
            )
            if files:
                clips.append({"id": v["id"], "url": files[0]["link"],
                               "duration": v.get("duration", 8), "q": query})
        return clips
    except Exception as e:
        print(f"   ⚠️  Pexels '{query}': {e}")
        return []


def download_clip(meta: dict, dest: Path) -> Path | None:
    path = dest / f"clip_{meta['id']}.mp4"
    if path.exists():
        return path
    try:
        r = requests.get(meta["url"], stream=True, timeout=60)
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                f.write(chunk)
        return path
    except Exception as e:
        print(f"   ⚠️  Download fail clip {meta['id']}: {e}")
        return None


def fetch_footage(title: str, workspace: Path, need_secs: float) -> list:
    print(f"\n🎬  Fetching footage (~{need_secs:.0f}s needed)...")
    dest = workspace / "footage"
    dest.mkdir(exist_ok=True)

    if not cfg.PEXELS_API_KEY or cfg.PEXELS_API_KEY == "YOUR_PEXELS_API_KEY_HERE":
        print("   ⚠️  No Pexels key — will use dark background instead.")
        return []

    keywords = pick_keywords(title)
    print(f"   Keywords: {', '.join(keywords[:5])}...")

    all_meta, total = [], 0.0
    for kw in keywords:
        results = pexels_search(kw, n=3)
        all_meta.extend(results)
        if len(all_meta) >= cfg.MAX_CLIPS:
            break

    random.shuffle(all_meta)
    paths = []
    for meta in all_meta:
        if total >= need_secs * 1.5:
            break
        p = download_clip(meta, dest)
        if p:
            paths.append(p)
            total += meta["duration"]
            print(f"   ↳ {p.name} ({meta['duration']}s) [{meta['q']}]")

    print(f"   ✅ {len(paths)} clips, ~{total:.0f}s")
    return paths


# ════════════════════════════════════════════════════════
#  STEP 6 — Pick background music
# ════════════════════════════════════════════════════════

def pick_music() -> Path | None:
    music_dir = Path(cfg.MUSIC_DIR)
    if not music_dir.exists():
        return None
    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav"))
    if not tracks:
        print("   ℹ️  No music in /music folder — video will have voiceover only.")
        return None
    chosen = random.choice(tracks)
    print(f"\n🎵  Music: {chosen.name}")
    return chosen


# ════════════════════════════════════════════════════════
#  STEP 7a — Scale & colour-grade each clip
# ════════════════════════════════════════════════════════

COLOR_GRADE = (
    "colorchannelmixer=rr=1.05:gg=0.95:bb=0.88,"
    "curves=all='0/0 0.25/0.18 0.75/0.65 1/0.90',"
    "eq=saturation=0.78:brightness=-0.04:contrast=1.10"
)

def clip_real_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True)
        return float(r.stdout.strip())
    except Exception:
        return 8.0


def make_dark_card(duration: float, out: Path):
    W, H = cfg.VIDEO_RESOLUTION
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0a0a0a:size={W}x{H}:rate=30:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out)
    ], capture_output=True)


def build_footage_track(clip_paths: list, total_duration: float,
                        workspace: Path) -> Path:
    proc_dir = workspace / "processed"
    proc_dir.mkdir(exist_ok=True)
    W, H = cfg.VIDEO_RESOLUTION

    scaled = []
    for i, cp in enumerate(clip_paths):
        out = proc_dir / f"s{i:03d}.mp4"
        if not out.exists():
            subprocess.run([
                "ffmpeg", "-y", "-i", str(cp),
                "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                        f"crop={W}:{H},setsar=1,{COLOR_GRADE}"),
                "-an", "-c:v", "libx264", "-preset", "fast",
                "-crf", "23", "-r", "30", "-pix_fmt", "yuv420p",
                str(out)
            ], capture_output=True)
        if out.exists():
            scaled.append(out)

    if not scaled:
        fallback = proc_dir / "fallback.mp4"
        make_dark_card(total_duration, fallback)
        return fallback

    # Build concat list, looping clips until we exceed needed duration
    concat_txt = workspace / "concat.txt"
    lines, current, idx = [], 0.0, 0
    while current < total_duration + 5:
        p = scaled[idx % len(scaled)]
        lines.append(f"file '{p.resolve()}'")
        current += clip_real_duration(p)
        idx += 1
    concat_txt.write_text("\n".join(lines))

    raw = proc_dir / "concat_raw.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt), "-c", "copy", str(raw)
    ], capture_output=True)

    trimmed = proc_dir / "footage_trimmed.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(raw),
        "-t", str(total_duration), "-c", "copy", str(trimmed)
    ], capture_output=True)

    return trimmed


# ════════════════════════════════════════════════════════
#  STEP 7b — Final assembly
# ════════════════════════════════════════════════════════

def assemble_video(footage: Path, voice: Path, music: Path | None,
                   duration: float, output: Path):
    print("\n🔧  Assembling final video...")

    if music:
        audio_in     = ["-i", str(voice), "-i", str(music)]
        audio_filter = (
            f"[1:a]aloop=loop=-1:size=2e+09,volume={cfg.MUSIC_VOLUME}[m];"
            f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=3[aout]"
        )
        audio_map    = ["-filter_complex", audio_filter, "-map", "0:v", "-map", "[aout]"]
    else:
        audio_in     = ["-i", str(voice)]
        audio_filter = None
        audio_map    = ["-map", "0:v", "-map", "1:a"]

    cmd = [
        "ffmpeg", "-y",
        "-i", str(footage),
        *audio_in,
        "-t", str(duration),
        *audio_map,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(output)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ FFmpeg error:")
        print(result.stderr[-3000:])
        sys.exit(1)

    mb = output.stat().st_size / 1024 / 1024
    print(f"   ✅ {output.name} ({mb:.1f} MB)")


# ════════════════════════════════════════════════════════
#  STEP 8 — Thumbnail
# ════════════════════════════════════════════════════════

def generate_thumbnail(title: str, footage_paths: list,
                        workspace: Path, out_path: Path):
    print("\n🖼️   Generating thumbnail...")
    W, H = 1280, 720
    img  = Image.new("RGB", (W, H), (10, 8, 12))

    # Extract a frame from first footage clip
    if footage_paths:
        try:
            frame = workspace / "tframe.jpg"
            subprocess.run([
                "ffmpeg", "-y", "-i", str(footage_paths[0]),
                "-ss", "00:00:04", "-vframes", "1",
                "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                str(frame)
            ], capture_output=True)
            if frame.exists():
                bg = Image.open(frame).convert("RGB")
                bg = ImageEnhance.Brightness(bg).enhance(0.30)
                bg = bg.filter(ImageFilter.GaussianBlur(2))
                img.paste(bg)
        except Exception:
            pass

    draw = ImageDraw.Draw(img)

    # Vignette
    vig = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd  = ImageDraw.Draw(vig)
    for i in range(280):
        alpha = int((i / 280) ** 1.9 * 210)
        vd.rectangle([i, i, W-i, H-i], outline=(0, 0, 0, alpha))
    img.paste(Image.new("RGB", (W, H), (0,0,0)), mask=vig.split()[3])

    # Accent bars
    draw.rectangle([0, 0, W, 7], fill=(190, 18, 18))
    draw.rectangle([0, H-7, W, H], fill=(190, 18, 18))

    # Fonts — fallback to default if system fonts unavailable
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    bold_font_path = next((f for f in font_paths if Path(f).exists()), None)

    try:
        f_small = ImageFont.truetype(bold_font_path, 24) if bold_font_path else ImageFont.load_default()
        f_title = ImageFont.truetype(bold_font_path, 76) if bold_font_path else ImageFont.load_default()
        f_tag   = ImageFont.truetype(bold_font_path, 26) if bold_font_path else ImageFont.load_default()
    except Exception:
        f_small = f_title = f_tag = ImageFont.load_default()

    # Channel name watermark
    draw.text((30, 24), "OBSCURA VAULT", font=f_small, fill=(190, 18, 18))

    # Wrap title — max ~22 chars per line
    words, lines, current = title.upper().split(), [], ""
    for word in words:
        test = (current + " " + word).strip()
        if len(test) <= 22:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    lh      = 90
    total_h = len(lines) * lh
    start_y = (H - total_h) // 2 - 30

    for i, line in enumerate(lines):
        y = start_y + i * lh
        # Drop shadow
        draw.text((54, y + 5), line, font=f_title, fill=(0, 0, 0))
        # Title text — warm cream
        draw.text((52, y), line, font=f_title, fill=(248, 240, 220))

    # Tagline
    draw.text((30, H - 52), "History They Buried. We Dig It Up.",
              font=f_tag, fill=(155, 135, 100))

    img.save(str(out_path), "JPEG", quality=95)
    print(f"   ✅ thumbnail.jpg saved")


# ════════════════════════════════════════════════════════
#  STEP 9 — Metadata
# ════════════════════════════════════════════════════════

def save_metadata(title: str, workspace: Path, duration: float):
    m, s   = int(duration // 60), int(duration % 60)
    ts_10  = f"10:00 – Modern Implications\n" if m > 10 else ""

    description = f"""{title}

What really happened? This is one of history's most suppressed and mysterious events — and mainstream sources rarely discuss it in full detail.

Obscura Vault digs into the archives, declassified documents, and eyewitness accounts to uncover what has been buried from public view.

━━━━━━━━━━━━━━━━━━━━━━━━━
TIMESTAMPS
00:00 – Introduction
01:30 – Background & Context
04:00 – The Hidden Truth
07:00 – The Cover-Up
{ts_10}━━━━━━━━━━━━━━━━━━━━━━━━━

🔔 Subscribe for buried history every week — Obscura Vault.

#ObscuraVault #HiddenHistory #DarkHistory #MysteriousEvents #TrueHistory
#UntoldHistory #HistoryUncovered #DarkDocumentary #ConspiracyFacts #LostHistory
""".strip()

    tags = [
        "hidden history", "dark history", "mysterious events", "obscura vault",
        "untold history", "suppressed history", "history documentary",
        "dark documentary", "history they dont teach", "conspiracy facts",
        title.lower(), *[w.lower() for w in title.split() if len(w) > 3]
    ]

    meta = {
        "title":       title,
        "description": description,
        "tags":        list(dict.fromkeys(tags)),
        "category":    "27",
        "duration_s":  round(duration),
        "duration":    f"{m}:{s:02d}",
    }

    (workspace / "metadata.json").write_text(json.dumps(meta, indent=2))
    (workspace / "description.txt").write_text(description)
    print("   ✅ metadata.json + description.txt saved")
    return meta


# ════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:55]


def cleanup_raw_footage(workspace: Path):
    footage_dir = workspace / "footage"
    if footage_dir.exists():
        deleted = sum(1 for f in footage_dir.iterdir() if f.unlink() is None)
        print(f"\n🗑️   Cleaned {deleted} raw footage files")


# ════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════

def main():
    title, script = collect_input()

    slug      = slugify(title)
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    job       = f"{ts}_{slug}"
    workspace = Path(cfg.WORKSPACE_DIR) / job
    out_dir   = Path(cfg.OUTPUT_DIR)

    workspace.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    Path(cfg.MUSIC_DIR).mkdir(parents=True, exist_ok=True)

    print(f"\n📁  Job: {job}")
    (workspace / "script.txt").write_text(script)

    # ── Voiceover ───────────────────────────────────────
    vo       = generate_voiceover(script, workspace)
    duration = get_duration(vo)
    m, s     = int(duration // 60), int(duration % 60)
    print(f"   ⏱  Duration: {m}m {s}s")

    # ── Footage ─────────────────────────────────────────
    footage_paths = fetch_footage(title, workspace, duration)

    # ── Music ───────────────────────────────────────────
    music = pick_music()

    # ── Build footage track ─────────────────────────────
    print("\n🔄  Processing footage clips...")
    footage_track = build_footage_track(footage_paths, duration, workspace)

    # ── Final video ─────────────────────────────────────
    final_mp4 = out_dir / f"{job}.mp4"
    assemble_video(footage_track, vo, music, duration, final_mp4)

    # ── Thumbnail ───────────────────────────────────────
    thumb = out_dir / f"{job}_thumbnail.jpg"
    generate_thumbnail(title, footage_paths, workspace, thumb)

    # ── Metadata ────────────────────────────────────────
    save_metadata(title, workspace, duration)

    # ── Cleanup raw downloads ───────────────────────────
    cleanup_raw_footage(workspace)

    # ── Summary ─────────────────────────────────────────
    mb = final_mp4.stat().st_size / 1024 / 1024
    print("\n" + "═" * 58)
    print("  ✅  DONE")
    print("═" * 58)
    print(f"\n  📹  VIDEO     : output/{final_mp4.name}")
    print(f"  🖼️   THUMBNAIL : output/{thumb.name}")
    print(f"  📄  METADATA  : workspace/{job}/metadata.json")
    print(f"  📝  DESCRIP.  : workspace/{job}/description.txt")
    print(f"\n  Duration : {m}m {s}s  |  Size : {mb:.1f} MB")
    print("\n  ➡️  Review video → upload to YouTube → paste description.txt")
    print("═" * 58 + "\n")


if __name__ == "__main__":
    main()
