"""
UploadEngine — YouTube Data API v3 OAuth + resumable upload.

Setup (one time per machine):
  1. https://console.cloud.google.com/ → create project
  2. Enable "YouTube Data API v3"
  3. APIs & Services → OAuth consent screen → External; add yourself as
     a test user (or publish if you don't mind verification)
  4. APIs & Services → Credentials → Create OAuth client ID → "Desktop app"
  5. Download the JSON; upload it via the UI. We store it as
     data/youtube/client_secrets.json
  6. Click "Authorize" in the UI; a browser tab opens; consent;
     token stored at data/youtube/token.json. Done.

Quotas: each upload costs 1600 units of the 10 000 daily quota,
so ~6 uploads/day per project. Plenty for one channel.

Heavy deps (google-auth, google-api-python-client) are lazy-imported
so the rest of the app runs without them.
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone


BASE_DIR    = Path(__file__).resolve().parent.parent
SECRETS_DIR = BASE_DIR / "data" / "youtube"
SECRETS_DIR.mkdir(parents=True, exist_ok=True)

CLIENT_SECRETS_PATH = SECRETS_DIR / "client_secrets.json"
TOKEN_PATH          = SECRETS_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


# ════════════════════════════════════════════════════════
#  Availability + status
# ════════════════════════════════════════════════════════

def is_installed() -> bool:
    try:
        import googleapiclient        # noqa: F401
        import google_auth_oauthlib   # noqa: F401
        return True
    except ImportError:
        return False


def has_secrets() -> bool:
    return CLIENT_SECRETS_PATH.exists()


def has_token() -> bool:
    return TOKEN_PATH.exists()


def channel_info() -> dict | None:
    """Return {id, title, subscribers} for the authorized channel, or None."""
    if not (is_installed() and has_token()):
        return None
    try:
        yt = _build_youtube()
        r = yt.channels().list(part="snippet,statistics", mine=True).execute()
        if not r.get("items"):
            return None
        item = r["items"][0]
        return {
            "id":          item["id"],
            "title":       item["snippet"].get("title"),
            "subscribers": int(item["statistics"].get("subscriberCount", 0)),
        }
    except Exception:
        return None


# ════════════════════════════════════════════════════════
#  OAuth
# ════════════════════════════════════════════════════════

def authorize(open_browser: bool = True) -> dict:
    """
    Run the InstalledAppFlow loopback flow. BLOCKS until the user
    authorizes in the browser, then writes token.json. Run in a thread.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not has_secrets():
        raise RuntimeError("client_secrets.json not uploaded yet")

    flow  = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_PATH), SCOPES
    )
    creds = flow.run_local_server(
        port=0, prompt="consent", open_browser=open_browser,
        authorization_prompt_message="Opening browser for YouTube authorization...",
        success_message="Authorized. You can close this tab.",
    )
    TOKEN_PATH.write_text(creds.to_json())
    return {"ok": True}


def _load_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_PATH.exists():
        raise RuntimeError("Not authorized — token.json missing")
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    return creds


def _build_youtube():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_load_creds(),
                 cache_discovery=False)


def revoke_token():
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


# ════════════════════════════════════════════════════════
#  Upload
# ════════════════════════════════════════════════════════

def upload_video(
    video_path: str | Path,
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    category_id: str = "27",                # 27 = Education
    privacy_status: str = "private",        # private | public | unlisted
    publish_at: str | None = None,          # ISO 8601, e.g. "2026-05-02T18:00:00Z"
    made_for_kids: bool = False,
    contains_synthetic_media: bool = True,  # YouTube AI-content disclosure
    on_progress=None,                       # cb(percent: int)
    on_log=None,                            # cb(msg: str)
) -> str:
    """Returns the new YouTube videoId."""
    from googleapiclient.http   import MediaFileUpload
    from googleapiclient.errors import HttpError

    log = on_log or (lambda m: None)
    yt  = _build_youtube()

    body: dict = {
        "snippet": {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        (tags or [])[:500],
            "categoryId":  category_id,
        },
        "status": {
            "privacyStatus":            privacy_status,
            "selfDeclaredMadeForKids":  made_for_kids,
            "containsSyntheticMedia":   contains_synthetic_media,
        },
    }
    if publish_at:
        # Scheduled: API requires privacyStatus=private, will flip at publishAt.
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"]     = publish_at

    media = MediaFileUpload(
        str(video_path), chunksize=4 * 1024 * 1024,
        resumable=True, mimetype="video/*",
    )
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    log("📤 starting resumable upload...")
    response = None
    while response is None:
        try:
            status, response = req.next_chunk()
        except HttpError as e:
            # 5xx + 429 → retry with backoff. 4xx → fatal.
            if e.resp.status in (500, 502, 503, 504, 429):
                log(f"   ⚠️  transient {e.resp.status}, retrying...")
                time.sleep(5)
                continue
            raise
        if status and on_progress:
            on_progress(int(status.progress() * 100))

    video_id = response["id"]
    log(f"✅ uploaded as videoId={video_id}")
    return video_id


def set_thumbnail(video_id: str, thumbnail_path: str | Path,
                  on_log=None) -> bool:
    from googleapiclient.http import MediaFileUpload
    log = on_log or (lambda m: None)
    yt  = _build_youtube()
    log(f"🖼️  setting thumbnail for {video_id}...")
    yt.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(thumbnail_path)),
    ).execute()
    log("   ✅ thumbnail set")
    return True


def upload_caption(video_id: str, srt_path: str | Path,
                   *, language: str = "en", name: str = "English",
                   on_log=None) -> bool:
    from googleapiclient.http import MediaFileUpload
    log = on_log or (lambda m: None)
    yt  = _build_youtube()
    log(f"💬 attaching caption track to {video_id}...")
    yt.captions().insert(
        part="snippet",
        body={"snippet": {"videoId": video_id, "language": language,
                          "name": name, "isDraft": False}},
        media_body=MediaFileUpload(str(srt_path), mimetype="application/x-subrip"),
    ).execute()
    log("   ✅ caption track attached")
    return True


# ════════════════════════════════════════════════════════
#  Top-level: full publish (video + thumb + caption)
# ════════════════════════════════════════════════════════

def publish(
    video_path: Path,
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    thumbnail_path: Path | None = None,
    caption_srt_path: Path | None = None,
    privacy_status: str = "private",
    publish_at: str | None = None,
    contains_synthetic_media: bool = True,
    idea_id: str | None = None,
    on_progress=None,
    on_log=None,
) -> dict:
    log = on_log or (lambda m: None)

    video_id = upload_video(
        video_path,
        title=title, description=description, tags=tags,
        privacy_status=privacy_status, publish_at=publish_at,
        contains_synthetic_media=contains_synthetic_media,
        on_progress=on_progress, on_log=log,
    )

    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            set_thumbnail(video_id, thumbnail_path, on_log=log)
        except Exception as e:
            log(f"   ⚠️  thumbnail set failed (non-fatal): {e}")

    if caption_srt_path and Path(caption_srt_path).exists():
        try:
            upload_caption(video_id, caption_srt_path, on_log=log)
        except Exception as e:
            log(f"   ⚠️  caption upload failed (non-fatal — needs verified account): {e}")

    # Record for analytics tracking (store local filename so storage engine
    # can skip deleting videos that haven't been uploaded yet)
    try:
        from engines import analytics
        analytics.record_upload(
            video_id, title, tags, idea_id=idea_id,
            local_filename=Path(video_path).name if video_path else None,
        )
    except Exception:
        pass

    return {
        "video_id": video_id,
        "url":      f"https://youtu.be/{video_id}",
        "studio":   f"https://studio.youtube.com/video/{video_id}/edit",
    }
