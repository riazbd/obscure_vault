"""
CaptionEngine — local speech-to-text via faster-whisper, then styled
.ass + plain .srt output for burn-in and YouTube upload.

faster-whisper is heavy (~200 MB deps + ~140 MB model on first use), so it
is imported lazily and the engine no-ops cleanly if it isn't installed.
"""

import re
from pathlib import Path


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


# Module-level model cache — avoids the ~20 s cold-start on every pipeline run
_whisper_cache: dict[str, "faster_whisper.WhisperModel"] = {}


def _get_model(model_name: str):
    if model_name not in _whisper_cache:
        from faster_whisper import WhisperModel
        _whisper_cache[model_name] = WhisperModel(
            model_name, device="cpu", compute_type="int8"
        )
    return _whisper_cache[model_name]


# ════════════════════════════════════════════════════════
#  Transcription
# ════════════════════════════════════════════════════════

def transcribe(audio_path: Path, model_name: str = "base.en",
               on_log=None) -> list[dict]:
    """
    Returns a list of segments: [{start: float, end: float, text: str}, ...]
    Each segment is one short phrase suitable for a single subtitle line.
    """
    log = on_log or (lambda m: None)

    log(f"   📥 loading whisper model '{model_name}' (first run downloads ~140 MB)...")
    model = _get_model(model_name)

    log("   🎧 transcribing voiceover...")
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=1,
        vad_filter=True,
        word_timestamps=True,
    )

    out = []
    for seg in segments:
        out.append({
            "start": float(seg.start),
            "end":   float(seg.end),
            "text":  seg.text.strip(),
            "words": [
                {"start": float(w.start), "end": float(w.end), "word": w.word}
                for w in (seg.words or [])
            ],
        })
    log(f"   ✅ {len(out)} segments, ~{info.duration:.1f}s")
    return out


# ════════════════════════════════════════════════════════
#  Re-chunk into 2-line, ≤32-char-per-line cards
# ════════════════════════════════════════════════════════

MAX_CHARS_PER_LINE = 32
MAX_LINES          = 2
MIN_DURATION       = 1.0
MAX_DURATION       = 5.5


def _wrap_two_lines(text: str) -> list[str]:
    text  = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if len(test) <= MAX_CHARS_PER_LINE:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
        if len(lines) == MAX_LINES:
            break
    if cur and len(lines) < MAX_LINES:
        lines.append(cur)
    # If overflow, append remaining onto last line (will exceed; that's fine for very long words)
    return lines or [""]


def chunk_words_into_cards(segments: list[dict]) -> list[dict]:
    """Repack word-level timing into 2-line subtitle cards under MAX_DURATION."""
    cards = []

    # Flatten to word stream
    words = []
    for s in segments:
        if s.get("words"):
            words.extend(s["words"])
        else:
            # No word timing — fall back to whole-segment card
            cards.append({"start": s["start"], "end": s["end"], "text": s["text"]})
    if not words:
        return cards

    cur_words = []
    cur_start = words[0]["start"]
    line_chars = 0

    def flush(end_t: float):
        nonlocal cur_words, cur_start, line_chars
        if not cur_words:
            return
        text = " ".join(w["word"].strip() for w in cur_words).strip()
        cards.append({"start": cur_start, "end": end_t, "text": text})
        cur_words, line_chars = [], 0

    for w in words:
        word_text = w["word"].strip()
        # Estimate chars per line for the next state
        prospective = line_chars + len(word_text) + 1
        duration    = w["end"] - cur_start

        if cur_words and (
            prospective > MAX_CHARS_PER_LINE * MAX_LINES
            or duration   > MAX_DURATION
            or word_text.endswith((".", "!", "?")) and duration >= MIN_DURATION
        ):
            flush(cur_words[-1]["end"])
            cur_start = w["start"]

        cur_words.append(w)
        line_chars += len(word_text) + 1

    if cur_words:
        flush(cur_words[-1]["end"])

    # Enforce minimum visible duration
    for c in cards:
        if c["end"] - c["start"] < MIN_DURATION:
            c["end"] = c["start"] + MIN_DURATION
    return cards


# ════════════════════════════════════════════════════════
#  .srt and .ass writers
# ════════════════════════════════════════════════════════

def _srt_time(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_srt(cards: list[dict], path: Path):
    out = []
    for i, c in enumerate(cards, 1):
        text  = "\n".join(_wrap_two_lines(c["text"]))
        out.append(f"{i}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n{text}\n")
    Path(path).write_text("\n".join(out), encoding="utf-8")


# Long-form: 1920x1080, smaller, lower-third
ASS_TEMPLATE_LONG = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,58,&H00F8F0DC,&H000000FF,&H00000000,&H8C000000,1,0,0,0,100,100,0,0,3,3,2,2,80,80,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Shorts: 1080x1920, big bold cyan-on-black box, vertically centered
ASS_TEMPLATE_SHORTS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,90,&H00FFFFFF,&H000000FF,&H00000000,&HCC000000,1,0,0,0,100,100,0,0,3,5,2,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_escape(text: str) -> str:
    # Escape for ASS dialog line: replace newlines with \N
    text = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
    return text.replace("\n", "\\N")


def write_ass(cards: list[dict], path: Path, *, style: str = "long"):
    body = ASS_TEMPLATE_SHORTS if style == "shorts" else ASS_TEMPLATE_LONG
    # Shorts: shorter line lengths so text fits the 1080-wide canvas
    max_chars = 18 if style == "shorts" else MAX_CHARS_PER_LINE
    for c in cards:
        words = re.sub(r"\s+", " ", c["text"]).strip().split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if len(test) <= max_chars:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
            if len(lines) == MAX_LINES:
                break
        if cur and len(lines) < MAX_LINES:
            lines.append(cur)
        text = _ass_escape("\\N".join(lines or [""]))
        body += (
            f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},"
            f"Default,,0,0,0,,{text}\n"
        )
    Path(path).write_text(body, encoding="utf-8")


# ════════════════════════════════════════════════════════
#  Top-level
# ════════════════════════════════════════════════════════

def build(audio_path: Path, workspace: Path,
          model_name: str = "base.en",
          style: str = "long",
          on_log=None) -> dict:
    """
    Transcribe audio_path and write {workspace}/captions.ass + captions.srt.
    style="shorts" → big vertical-friendly subtitle styling.
    Returns: {ass: Path, srt: Path, cards: int}
    Raises ImportError if faster-whisper is not installed.
    """
    log = on_log or (lambda m: None)
    log("📝 Building captions...")

    segments = transcribe(Path(audio_path), model_name=model_name, on_log=log)
    cards    = chunk_words_into_cards(segments)
    log(f"   ✏️  {len(cards)} caption cards")

    ass_path = Path(workspace) / "captions.ass"
    srt_path = Path(workspace) / "captions.srt"
    write_ass(cards, ass_path, style=style)
    write_srt(cards, srt_path)
    log(f"   ✅ {ass_path.name} + {srt_path.name} (style={style})")

    return {"ass": ass_path, "srt": srt_path, "cards": len(cards)}
