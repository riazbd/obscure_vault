"""
BrandingEngine — normalize user-supplied intro/outro stings, then concat
them around a rendered main video with bulletproof codec matching.

Normalization on upload: re-encodes the user file to the canonical spec
(canvas WxH, 30 fps, libx264 yuv420p, AAC 44.1 kHz stereo) so the
final concat can use stream-copy demuxer concat — no re-encode of the
big main video, no quality loss.

Files live at data/branding/<slot>.mp4 where <slot> is one of:
  long_intro, long_outro, short_intro, short_outro

Falls back to filter-concat with re-encode if stream-copy concat
fails (rare; usually means the source had unexpected metadata).
"""

import re
import json
import shutil
import subprocess
from pathlib import Path


BASE_DIR     = Path(__file__).resolve().parent.parent
BRANDING_DIR = BASE_DIR / "data" / "branding"
BRANDING_DIR.mkdir(parents=True, exist_ok=True)

VALID_SLOTS = {"long_intro", "long_outro", "short_intro", "short_outro"}


# ════════════════════════════════════════════════════════
#  Slot management
# ════════════════════════════════════════════════════════

def slot_path(slot: str) -> Path:
    if slot not in VALID_SLOTS:
        raise ValueError(f"unknown slot: {slot}")
    return BRANDING_DIR / f"{slot}.mp4"


def has_slot(slot: str) -> bool:
    return slot_path(slot).exists()


def list_slots() -> dict:
    out = {}
    for s in VALID_SLOTS:
        p = slot_path(s)
        if p.exists():
            out[s] = {
                "filename":   p.name,
                "size_kb":    p.stat().st_size // 1024,
                "duration":   _probe_duration(p),
            }
        else:
            out[s] = None
    return out


def delete_slot(slot: str) -> bool:
    p = slot_path(slot)
    if p.exists():
        p.unlink()
        return True
    return False


def _probe_duration(path: Path) -> float | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return round(float(r.stdout.strip()), 2)
    except Exception:
        return None


# ════════════════════════════════════════════════════════
#  Normalize on upload
# ════════════════════════════════════════════════════════

def normalize_clip(src_path: Path, slot: str, *,
                   width: int = 1920, height: int = 1080,
                   fps: int = 30) -> Path:
    """
    Re-encode src_path to canonical spec for `slot` and save at
    BRANDING_DIR/<slot>.mp4. Width/height come from the slot:
      long_*  → 1920x1080
      short_* → 1080x1920
    """
    if slot not in VALID_SLOTS:
        raise ValueError(f"unknown slot: {slot}")

    if slot.startswith("short_"):
        width, height = 1080, 1920

    dest = slot_path(slot)
    tmp  = dest.with_suffix(".tmp.mp4")

    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
          f"setsar=1,fps={fps}")

    cmd = [
        "ffmpeg", "-y", "-i", str(src_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        # If the source has no audio, generate silence so concat-copy works.
        "-af", "apad",
        "-shortest",
        str(tmp),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not tmp.exists():
        # Retry without audio padding (some sources reject -af apad).
        cmd2 = [
            "ffmpeg", "-y", "-i", str(src_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(tmp),
        ]
        r = subprocess.run(cmd2, capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not tmp.exists():
            raise RuntimeError(f"normalize failed: {r.stderr[-1500:]}")

    if dest.exists():
        dest.unlink()
    tmp.rename(dest)
    return dest


# ════════════════════════════════════════════════════════
#  Apply branding to a finished main video
# ════════════════════════════════════════════════════════

def apply_branding(
    main_path: Path,
    out_path: Path,
    *,
    intro_path: Path | None = None,
    outro_path: Path | None = None,
    width: int = 1920,
    height: int = 1080,
    on_log=None,
) -> Path:
    """
    Concatenate [intro?] + main + [outro?] into out_path.
    Both stream-copy concat and filter concat are tried. Returns out_path.
    No-ops (copies main → out) if neither intro nor outro is provided.
    """
    log  = on_log or (lambda m: None)
    main = Path(main_path)
    out  = Path(out_path)

    parts = [p for p in (intro_path, Path(main_path), outro_path) if p]
    parts = [Path(p) for p in parts if Path(p).exists()]
    if len(parts) < 2:
        # Nothing to brand — just copy
        if str(main) != str(out):
            shutil.copyfile(main, out)
        return out

    log(f"🎨 branding: {len(parts)} parts → {out.name}")

    # Try the cheap path first: concat demuxer with stream copy.
    list_path = main.parent / f".{out.stem}_concat.txt"
    list_path.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_path), "-c", "copy",
        "-movflags", "+faststart", str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    list_path.unlink(missing_ok=True)
    if r.returncode == 0 and out.exists():
        log("   ✅ stream-copy concat ok")
        return out

    # Fallback: re-encode via concat filter. Slower but bulletproof.
    log("   ⚠️  stream-copy concat failed, re-encoding...")
    inputs = []
    fc_in  = ""
    for i, p in enumerate(parts):
        inputs += ["-i", str(p)]
        fc_in  += f"[{i}:v:0][{i}:a:0]"
    fc = f"{fc_in}concat=n={len(parts)}:v=1:a=1[v][a]"

    cmd2 = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out),
    ]
    r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
    if r2.returncode != 0 or not out.exists():
        raise RuntimeError(f"branding failed: {r2.stderr[-1500:]}")
    log("   ✅ filter concat ok")
    return out


def apply_for_video_kind(main_path: Path, out_path: Path, *,
                         kind: str = "long",
                         width: int = 1920, height: int = 1080,
                         on_log=None) -> Path:
    """
    Convenience: applies the matching slots for kind ∈ {long, short}.
    Returns out_path even if no branding was applied.
    """
    intro = slot_path(f"{kind}_intro") if has_slot(f"{kind}_intro") else None
    outro = slot_path(f"{kind}_outro") if has_slot(f"{kind}_outro") else None
    return apply_branding(main_path, out_path,
                          intro_path=intro, outro_path=outro,
                          width=width, height=height, on_log=on_log)
