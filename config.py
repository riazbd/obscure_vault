# ─────────────────────────────────────────────────────────
#  OBSCURA VAULT — Configuration
#  Edit this file before running pipeline.py
# ─────────────────────────────────────────────────────────

import os
from dotenv import load_dotenv

load_dotenv()

# Get your FREE Pexels API key at: https://www.pexels.com/api/
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "YOUR_PEXELS_API_KEY_HERE")

# OpenRouter API key — free models only by default.
# Get yours at: https://openrouter.ai/keys
# Used by: idea / script / SEO engines.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Edge TTS voice — documentary-style picks:
#   en-US-GuyNeural      ← deep, authoritative (DEFAULT)
#   en-US-EricNeural     ← warm, measured
#   en-GB-RyanNeural     ← British, formal
#   en-GB-ThomasNeural   ← deep British, great for history
#   en-US-DavisNeural    ← slightly gravelly, dramatic
#
# Preview all voices: run  edge-tts --list-voices  in terminal
TTS_VOICE = "en-US-GuyNeural"

# Folders (no need to change these)
OUTPUT_DIR    = "output"      # Final MP4 + thumbnail saved here
WORKSPACE_DIR = "workspace"   # Temporary working files
MUSIC_DIR     = "music"       # Drop your dark ambient MP3s here

# Video settings
VIDEO_RESOLUTION = (1920, 1080)
MUSIC_VOLUME     = 0.12        # 0.0 = silent, 1.0 = full volume
MAX_CLIPS        = 25          # Max Pexels clips to download per video
