# Obscura Vault: End-to-End Automation Tutorial

Welcome to the Obscura Vault! This guide will take you from absolute scratch—having no YouTube channel—to running a fully automated, 24/7 background worker that researches, writes, edits, and publishes historical documentaries to your channel.

---

## Phase 1: Create Your YouTube Channel

Before the software can upload videos, you need a destination.

1. **Create a Google Account:** If you don't want to mix this with your personal email, create a fresh Gmail account.
2. **Create a YouTube Channel:** 
   - Go to [YouTube](https://www.youtube.com) and sign in.
   - Click your profile picture in the top right and select **Create a channel**.
   - Pick a name (e.g., "The Obscura Vault", "Buried History", "Echoes of the Past").
   - Complete the basic setup (upload a profile picture and banner).
3. **Verify Your Channel (Optional but Recommended):**
   - Go to YouTube Studio > Settings > Channel > Feature eligibility.
   - Verify your phone number to unlock intermediate features (like custom thumbnails, though Shorts don't strictly require them, it helps channel trust).

---

## Phase 2: Get Your Free API Keys

The software relies on three external services to do its job for free. You need to gather these keys.

### 1. Pexels (For Video B-Roll)
1. Go to [Pexels API](https://www.pexels.com/api/) and create a free account.
2. Request an API key. 
3. Copy the key and save it in a safe place.

### 2. OpenRouter (For the LLM Brain)
1. Go to [OpenRouter](https://openrouter.ai/) and create an account.
2. Navigate to **Keys** and click **Create Key**.
3. Copy the key (it starts with `sk-or-...`). The software uses a "cascade" of free models on OpenRouter, so you don't need to add a credit card.

### 3. Google Cloud Console (For YouTube Uploads)
This is the most complex step, but you only do it once.
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new Project (name it "Obscura Vault App").
3. Go to **APIs & Services** > **Library**. Search for **YouTube Data API v3** and click **Enable**.
4. Go to **OAuth consent screen**. 
   - Choose **External** and click Create.
   - Fill in the required app name and developer email (your email). 
   - Under "Test users", add the email address of the YouTube channel you created in Phase 1.
5. Go to **Credentials**.
   - Click **Create Credentials** > **OAuth client ID**.
   - Application type: **Desktop app**. Name: "Obscura Vault Uploader".
   - Click Create.
6. A window will pop up. Click **Download JSON**. 
7. Rename the downloaded file to exactly `client_secrets.json`. Keep it handy.

---

## Phase 3: Setup the Software

Now, let's configure Obscura Vault on your machine.

1. **Install Prerequisites:**
   - Install **Python 3.10+**.
   - Install **FFmpeg** (make sure it is added to your system PATH).
2. **Launch the App:**
   - Open a terminal or command prompt in the `obscure_vault` folder.
   - Run the command: `python start.py`
   - The terminal will install missing dependencies automatically and start a local web server.
3. **Open the Dashboard:**
   - Open your web browser and navigate to `http://localhost:5050`.

---

## Phase 4: Configure the App via the UI

Everything can now be configured directly through the web interface. Click on **Settings** in the left sidebar to begin.

### 1. Set and Save Your API Keys
You must provide the keys you gathered in Phase 2:
- **OpenRouter API Key:** Paste your key (`sk-or-...`) into the input box. Click the gold **Save / Validate** button next to it. The system will ping OpenRouter to verify it works.
- **Pexels API Key:** Paste your key into the input box. Click the gold **Save / Validate** button. 
- *(These are securely saved to a local `.env` file in the background and are never exposed).*

### 2. Configure Pipeline Settings
Review and adjust the core video generation settings in the main Settings panel:
- **TTS Voice:** Select the narrator's voice. `en-US-GuyNeural` is the default and sounds like a classic documentary narrator.
- **Video Resolution:** Leave at `1080x1920` (Vertical) for YouTube Shorts.
- **Background Music Volume:** Default is `0.12`. Adjust if the music overpowers the narrator.
- **Smart B-Roll:** Check this box to enable the LLM to pick cinematic clips based on the script's mood.
- **Burn Captions:** Check this box if you want hardcoded subtitles burned into the video (highly recommended for YouTube Shorts).
- **Audio Polish:** Check this box to enable audio ducking (lowering music volume when the narrator speaks).
- Once you have reviewed all toggles, scroll to the bottom and click the large **Save All Settings** button.

### 3. Connect Your YouTube Channel
Scroll down to the **YouTube API Integration** section. This is where you link the software to the channel you created:
- Click **1. Install libs** (if not already installed). This installs the Google authentication libraries.
- Click **2. Upload client_secrets.json** and select the file you downloaded from the Google Cloud Console in Phase 2.
- Click **3. Authorize**. A Google login window will open in your browser. 
- Log in with your YouTube channel's email. Google will warn you the app isn't verified (since you just made it). Click **Advanced** > **Go to Obscura Vault App (unsafe)**. Click **Allow**.
- The UI will now show a green "Authorized" badge. The software now has a local `token.json` file and can upload videos automatically.

### 4. Upload Your Branding & Music
To keep your channel copyright-safe and strongly branded:
- **Music:** Go to the **Music** tab. Drag and drop royalty-free dark ambient tracks (e.g., from the YouTube Audio Library or Epidemic Sound). The software randomly selects one for each video.
- **Branding (Intro/Outro):** Go to the **Settings** tab. Scroll to the **Branding Stings** section. 
  - Upload a **2-3 second intro clip** (e.g., your channel logo revealing).
  - Upload a **3-5 second outro clip** (e.g., "Subscribe for more history").
  - Make sure the "Apply branding stings" checkbox is checked in your main settings. The software will stitch these onto every video natively.

### 5. Define Your Niche
Now tell the AI what kind of channel you are running:
- Go to the **Ideas** tab.
- In the "Niche description" box, type exactly what your channel is about. Example:
  > *"Cold war espionage, unexplained disappearances from the 1900s, and declassified military secrets."*
- Click **Harvest Ideas**. The system will scrape the internet, and the LLM will grade the ideas against your specific niche to ensure it only produces relevant content.

---

## Phase 5: Run on Autopilot (Background Automation)

You are completely set up. Now it's time to let the machine take over.

1. **Turn on the Scheduler:**
   - Go to the **Dashboard** tab.
   - You will see the **Autopilot Scheduler** section. 
   - Ensure the scheduler is running. 

2. **What the Scheduler Does:**
   As long as the terminal window running `python start.py` remains open, the software operates in an infinite loop:
   - **Tick 1:** It looks at your `Ideas` list. It picks the highest-rated idea.
   - **Tick 2:** It researches the idea, writes a script, generates voiceover, downloads B-roll, and renders the video.
   - **Tick 3:** It generates an AI thumbnail and SEO metadata.
   - **Tick 4:** It uploads the final product to your YouTube channel.
   - **Tick 5:** It cleans up temporary storage files to prevent your hard drive from filling up.
   - **Tick 6:** A few days later, it checks the YouTube Analytics of that video and adjusts its own scoring algorithm to make better videos in the future.

3. **Leave It Running:**
   Simply minimize the terminal window. You can close the browser tab. The software will continue to run silently in the background, harvesting ideas and publishing videos to your channel indefinitely. 

**Congratulations!** You now own a fully automated YouTube documentary channel.