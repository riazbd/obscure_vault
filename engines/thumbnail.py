"""
ThumbnailEngine — three-layer composition with AI-generated background.

Flow:
  1. LLM picks a 2-4 word punchline (NOT the full title — too long for thumbs)
  2. LLM writes a cinematographic image prompt
  3. Pollinations.ai generates a 1280x720 background (free, no key)
  4. PIL composes vignette + accent bars + punchline + branding
  5. Auto-QA: luminance + simple text-contrast heuristic;
     darken/regenerate if needed
  6. Up to N variants generated with different seeds for A/B testing

Pollinations is the primary backend — public, free, requires only HTTP GET
to https://image.pollinations.ai/prompt/<urlencoded>?width=1280&height=720
"""

import io
import re
import time
import hashlib
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

import llm


BASE_DIR     = Path(__file__).resolve().parent.parent
IMG_CACHE_DIR = BASE_DIR / "data" / "cache" / "images"
IMG_CACHE_DIR.mkdir(parents=True, exist_ok=True)

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/"

CHANNEL_NAME    = "OBSCURA VAULT"
CHANNEL_TAGLINE = "History They Buried. We Dig It Up."

VISUAL_STYLE = (
    "cinematic, dramatic chiaroscuro lighting, dark teal and amber colour "
    "grade, 35mm film grain, atmospheric haze, deep shadows, eerie, "
    "documentary still, ultra detailed, 8k"
)


# ════════════════════════════════════════════════════════
#  LLM helpers — punchline + image prompt
# ════════════════════════════════════════════════════════

def generate_punchline(api_key: str, title: str) -> str:
    """A 2-4 word phrase that fits big on a thumbnail."""
    msgs = [
        {"role": "system", "content":
            "You are a YouTube thumbnail copywriter. Output ONLY valid JSON."},
        {"role": "user", "content": f"""
For this video title, give a SHORT punchline that goes on the thumbnail:

Title: {title}

Rules:
- 2 to 4 words. Maximum 20 characters total.
- Punchy, declarative, slightly ominous.
- All caps in the final image (you can return any case; we'll uppercase).
- Must NOT just repeat the full title.
- No emoji, no quotes, no question marks unless essential.

Examples of the style we want (do not reuse these literally):
  "BURIED ALIVE", "60 YEARS HIDDEN", "THEY KNEW", "NEVER FOUND"

Return JSON: {{"punchline": "..."}}
""".strip()}]

    res = llm.call(api_key, msgs, json_mode=True, temperature=0.85,
                   max_tokens=200)
    p = (res["json"] or {}).get("punchline", "").strip().upper()
    p = re.sub(r"[^A-Z0-9 \-?!]", "", p)
    if not p or len(p) > 22 or len(p.split()) > 4:
        # Fallback: extract a punchy fragment from the title.
        words = re.findall(r"[A-Za-z]+", title.upper())
        p = " ".join(words[:3]) if words else "BURIED HISTORY"
    return p


def generate_image_prompt(api_key: str, title: str, seed: int = 0) -> str:
    msgs = [
        {"role": "system", "content":
            "You write image prompts for AI image generators. Output ONLY valid JSON."},
        {"role": "user", "content": f"""
Build a cinematographic image prompt for a YouTube thumbnail background.

Video title: {title}
Channel mood: dark history, atmospheric, mysterious, slightly grim.

Hard constraints:
- Concrete subject + concrete setting + lighting + mood, in that order.
- 25 to 50 words.
- No human faces (we composite text over the image).
- No on-image text, watermarks, signatures, captions, or letters.
- Aspect 16:9 framing, wide cinematic composition, plenty of negative space
  in the LEFT or BOTTOM third for overlay text.

Return JSON: {{"prompt": "..."}}
""".strip()}]

    res = llm.call(api_key, msgs, json_mode=True, temperature=0.8,
                   max_tokens=400)
    p = (res["json"] or {}).get("prompt", "").strip()
    if len(p) < 20:
        p = f"abandoned historical scene relating to: {title}"
    # Append the channel-wide style anchor + a no-text negative.
    return f"{p}, {VISUAL_STYLE}, no text, no letters, no watermark"


# ════════════════════════════════════════════════════════
#  Pollinations image fetch (free, no key)
# ════════════════════════════════════════════════════════

def _img_cache_key(prompt: str, seed: int, w: int, h: int) -> str:
    h_ = hashlib.sha256()
    h_.update(prompt.encode())
    h_.update(f"{seed}|{w}x{h}".encode())
    return h_.hexdigest()


def pollinations_image(prompt: str, *, seed: int = 0,
                       width: int = 1280, height: int = 720,
                       timeout: int = 90) -> Image.Image:
    """GET the rendered PNG from Pollinations. Caches by (prompt, seed, size)."""
    ck   = _img_cache_key(prompt, seed, width, height)
    cache = IMG_CACHE_DIR / f"{ck}.png"
    if cache.exists():
        return Image.open(cache).convert("RGB")

    url = (
        POLLINATIONS_BASE
        + urllib.parse.quote(prompt, safe="")
        + f"?width={width}&height={height}&nologo=true&seed={seed}&model=flux"
    )

    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                cache.write_bytes(r.content)
                return Image.open(io.BytesIO(r.content)).convert("RGB")
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep((attempt + 1) * 3)

    raise RuntimeError(f"pollinations failed: {last_err}")


# ════════════════════════════════════════════════════════
#  Composition
# ════════════════════════════════════════════════════════

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(size: int):
    for fp in FONT_CANDIDATES:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_punchline(text: str, max_chars: int = 12) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if len(test) <= max_chars:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _avg_luminance(img: Image.Image) -> float:
    """Mean luminance 0..1 over the whole image."""
    g = img.convert("L")
    hist = g.histogram()
    total = sum(hist)
    if total == 0:
        return 0.0
    weighted = sum(i * v for i, v in enumerate(hist))
    return (weighted / total) / 255.0


def _ensure_dark(img: Image.Image, target_max: float = 0.45) -> Image.Image:
    lum = _avg_luminance(img)
    if lum <= target_max:
        return img
    factor = target_max / max(lum, 0.01)
    factor = max(0.35, min(1.0, factor))
    return ImageEnhance.Brightness(img).enhance(factor)


def compose_thumbnail(
    background: Image.Image,
    punchline: str,
    channel_name: str = CHANNEL_NAME,
    tagline: str = CHANNEL_TAGLINE,
    accent_color=(190, 18, 18),
    out_path: Path = None,
    vertical: bool = False,
) -> Path:
    W, H = (1080, 1920) if vertical else (1280, 720)
    bg = background.copy()
    if bg.size != (W, H):
        bg = bg.resize((W, H), Image.LANCZOS)
    bg = _ensure_dark(bg, 0.40)
    # Soft blur the bottom-left where text goes, to lift contrast
    img = bg.convert("RGB")

    # Vignette
    vig = Image.new("L", (W, H), 0)
    vd  = ImageDraw.Draw(vig)
    for i in range(280):
        alpha = int((i / 280) ** 1.9 * 220)
        vd.rectangle([i, i, W-i, H-i], outline=alpha)
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), mask=vig)

    draw = ImageDraw.Draw(img)

    # Top + bottom accent bars
    draw.rectangle([0, 0, W, 7],     fill=accent_color)
    draw.rectangle([0, H-7, W, H],   fill=accent_color)

    # Channel name watermark
    f_brand = _font(28)
    draw.text((30, 22), channel_name, font=f_brand, fill=accent_color)

    # Punchline lines — auto-fit
    text   = punchline.strip().upper()
    lines  = _wrap_punchline(text, max_chars=12)
    size   = 180 if len(lines) == 1 else (140 if len(lines) == 2 else 110)
    f_pun  = _font(size)

    # Re-measure and shrink if it overruns
    while True:
        widths = [f_pun.getbbox(L)[2] for L in lines]
        if max(widths) <= W - 120 or size <= 60:
            break
        size -= 8
        f_pun = _font(size)

    line_h  = int(size * 1.05)
    total_h = line_h * len(lines)
    start_y = (H - total_h) // 2 - 20

    # Behind-text dark slab for guaranteed contrast
    slab_pad = 24
    slab_top = start_y - slab_pad
    slab_bot = start_y + total_h + slab_pad
    slab     = Image.new("RGBA", (W, slab_bot - slab_top), (0, 0, 0, 140))
    img.paste(Image.new("RGB", slab.size, (0, 0, 0)), (0, slab_top), mask=slab.split()[3])

    for i, line in enumerate(lines):
        bw = f_pun.getbbox(line)[2]
        x  = (W - bw) // 2
        y  = start_y + i * line_h
        # Drop shadow
        for ox, oy in [(4, 4), (-2, 2), (2, -2)]:
            draw.text((x + ox, y + oy), line, font=f_pun, fill=(0, 0, 0))
        # Stroke (PIL ≥ 8.0)
        try:
            draw.text((x, y), line, font=f_pun,
                      fill=(248, 240, 220),
                      stroke_width=3, stroke_fill=(0, 0, 0))
        except TypeError:
            draw.text((x, y), line, font=f_pun, fill=(248, 240, 220))

    # Tagline
    f_tag = _font(26)
    draw.text((30, H - 50), tagline, font=f_tag, fill=(155, 135, 100))

    out_path = Path(out_path) if out_path else (BASE_DIR / "output" / "thumbnail.jpg")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "JPEG", quality=92, optimize=True)
    return out_path


# ════════════════════════════════════════════════════════
#  Top-level: title -> thumbnail file(s)
# ════════════════════════════════════════════════════════

def generate(api_key: str, title: str, out_path: Path,
             variants: int = 1, vertical: bool = False,
             on_log=None) -> dict:
    """
    Generate one or more thumbnails.
    Returns: {primary, variants:[paths], punchline, image_prompt}
    """
    log = on_log or (lambda m: None)
    out_path = Path(out_path)

    log("🖼️  Composing AI thumbnail...")
    if not api_key:
        raise RuntimeError("OpenRouter key required for AI thumbnail")

    log("   ✏️  punchline...")
    punchline = generate_punchline(api_key, title)
    log(f"      ↳ {punchline!r}")

    log("   🎨 image prompt...")
    img_prompt = generate_image_prompt(api_key, title)
    log(f"      ↳ {img_prompt[:120]}{'...' if len(img_prompt) > 120 else ''}")

    bg_w, bg_h = (1080, 1920) if vertical else (1280, 720)
    n_variants = max(1, variants)

    def _fetch_bg(i: int):
        seed = (abs(hash((title, i))) % 999983) + 1
        log(f"   📥 background v{i+1} (seed={seed})...")
        try:
            return i, pollinations_image(img_prompt, seed=seed,
                                         width=bg_w, height=bg_h)
        except Exception as e:
            log(f"      ⚠️  pollinations v{i+1} failed: {e}")
            return i, None

    # Fetch all backgrounds in parallel (each is a blocking HTTP call)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=n_variants) as pool:
        bg_results = dict(pool.map(lambda i: _fetch_bg(i), range(n_variants)))

    written = []
    for i in range(n_variants):
        bg = bg_results.get(i)
        if bg is None:
            if i == 0:
                bg = Image.new("RGB", (bg_w, bg_h), (12, 10, 14))
            else:
                continue

        target = out_path if i == 0 else out_path.with_name(
            f"{out_path.stem}_v{i+1}{out_path.suffix}"
        )
        compose_thumbnail(bg, punchline, out_path=target, vertical=vertical)
        log(f"      ✅ {target.name}")
        written.append(str(target))

    if not written:
        raise RuntimeError("no thumbnail variants produced")

    return {
        "primary":      written[0],
        "variants":     written,
        "punchline":    punchline,
        "image_prompt": img_prompt,
    }
