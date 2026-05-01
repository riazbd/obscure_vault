# OBSCURA VAULT — Automated Video Pipeline
### History They Buried. We Dig It Up.

A fully automated, local YouTube video generation pipeline with a beautiful dark UI.
Runs on **Windows, Mac, and Linux**. No VPS. No paid tools.

---

## WHAT IT DOES

Paste your video title and script → get a YouTube-ready 1080p video with:
- ✅ Professional narration (Edge TTS — free, no signup)
- ✅ Cinematic footage (Pexels API — free)
- ✅ Background music (your MP3 library)
- ✅ Dark colour grade (FFmpeg)
- ✅ Branded thumbnail (1280×720)
- ✅ YouTube description + tags

---

## QUICK START

### Step 1 — Install Python

**Windows/Mac:** Download from https://python.org/downloads
- ⚠️ Windows: Check "Add Python to PATH" during installation

**Linux/WSL:**
```bash
sudo apt update && sudo apt install python3 python3-pip -y
```

---

### Step 2 — Install FFmpeg

**Ubuntu/Debian/WSL:**
```bash
sudo apt install ffmpeg -y
```

**Mac (Homebrew):**
```bash
brew install ffmpeg
```

**Windows:**
1. Download from https://ffmpeg.org/download.html → click "Windows builds"
2. Extract the zip
3. Copy the `/bin` folder path (e.g. `C:\ffmpeg\bin`)
4. Open Start → search "Environment Variables" → Edit System PATH → Add new → paste path
5. Restart terminal and test: `ffmpeg -version`

---

### Step 3 — Get Your Free Pexels API Key

1. Go to https://www.pexels.com/api/
2. Click "Get Started" — sign up is free
3. After logging in, your API key is shown on the dashboard
4. Copy it — you'll paste it in the Settings tab of the app

---

### Step 4 — Launch the App

**Windows:** Double-click `START_WINDOWS.bat`

**Mac/Linux:**
```bash
chmod +x START_MAC_LINUX.sh
./START_MAC_LINUX.sh
```

**Any platform:**
```bash
python start.py
```

The launcher will:
- Check Python and FFmpeg
- Install all Python packages automatically
- Open the UI at http://localhost:5050

---

### Step 5 — Configure in the UI

1. Go to **Settings** tab → paste your Pexels API key → click Validate & Save
2. Choose your narrator voice (Guy Neural recommended for dark history)
3. Set music volume (12% default is good)

---

### Step 6 — Add Background Music

1. Go to **Music Library** tab
2. Upload dark ambient MP3 files
3. Free music sources:
   - **pixabay.com/music** — search "dark ambient", "mystery", "documentary"
   - **freemusicarchive.org** — filter by CC0 license

Aim for 5–10 tracks so the pipeline has variety to pick from.

---

### Step 7 — Generate Your First Video

1. Go to **Generate Video** tab
2. Paste your title (get this from Claude)
3. Paste your narration script (get this from Claude)
4. Click **Generate Video**
5. Watch the progress panel — takes 20–45 minutes on the T480
6. Download the MP4 and thumbnail when done
7. Copy the description and upload to YouTube

---

## FOLDER STRUCTURE

```
obscura_vault/
├── start.py              ← Run this to launch the app
├── server.py             ← Flask backend (auto-started by start.py)
├── requirements.txt      ← Python dependencies
├── START_WINDOWS.bat     ← Windows double-click launcher
├── START_MAC_LINUX.sh    ← Mac/Linux launcher
├── ui/
│   └── index.html        ← The full UI (single file)
├── music/                ← Drop your MP3s here (or use UI)
├── output/               ← Generated videos and thumbnails
├── workspace/            ← Temp files during render (auto-managed)
└── config.json           ← Saved settings (auto-created by UI)
```

---

## HARDWARE EXPECTATIONS (ThinkPad T480, i5 7th Gen, 8GB RAM)

| Stage                  | Time          |
|------------------------|---------------|
| Voiceover (TTS)        | 15–30 sec     |
| Footage download       | 3–10 min      |
| Clip colour grading    | 8–18 min      |
| Final video assembly   | 5–12 min      |
| Thumbnail generation   | 10–20 sec     |
| **Total**              | **~20–45 min**|

Tips:
- Close Chrome and heavy apps during rendering
- Raw footage files are deleted automatically after each run
- Final MP4 at 1080p = ~700MB–1.5GB per video

---

## CHANGING VOICES

In the Settings tab, pick any of these:

| Voice | Best For |
|-------|----------|
| Guy (US) | Deep, authoritative — default for Obscura Vault |
| Eric (US) | Warm, measured — good alternative |
| Thomas (UK) | Deep British — great for historical content |
| Ryan (UK) | Formal British accent |
| Davis (US) | Slightly gravelly, dramatic feel |

---

## TROUBLESHOOTING

**"python not found" on Windows**
→ Reinstall Python from python.org and check "Add to PATH"

**"ffmpeg not found"**
→ Re-read Step 2. FFmpeg bin folder must be in your system PATH.

**"Cannot connect to server" in the UI**
→ Make sure `start.py` is running in the terminal. Don't close it.

**Pexels key shows "Invalid"**
→ Check you copied the full key. Go to pexels.com, log in, copy again.

**Video is just a dark screen**
→ Pexels footage downloaded but FFmpeg clip processing failed.
   Run `ffmpeg -version` in terminal to confirm it's installed.

**Script too short warning**
→ A 5-min video = ~720 words | 10-min = ~1440 words | 15-min = ~2160 words

---

## SCRIPT WORD TARGETS

| Video Length | Words Needed |
|-------------|--------------|
| 5 minutes   | 720 words    |
| 7 minutes   | 1,008 words  |
| 10 minutes  | 1,440 words  |
| 12 minutes  | 1,728 words  |
| 15 minutes  | 2,160 words  |

---

Made for Obscura Vault — the YouTube channel for buried history.
