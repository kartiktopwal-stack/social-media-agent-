"""
clip_publisher.py
─────────────────────────────────────────────────────────────────────────────
Phase 4 — YouTube Shorts Uploader

Functions:
    get_youtube_client        — Load OAuth creds from token.json, return API client
    build_shorts_title        — Build a YouTube Shorts title from hook + niche
    build_shorts_description  — Build a 2-3 line description with hashtags
    upload_clip               — Upload a single clip by clip_id, update SQLite
    publish_ready_clips       — Batch upload all enhanced clips
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("clip_publisher")

# token.json lives in project root (same dir as this file)
_TOKEN_PATH = Path(__file__).resolve().parent / "token.json"
print(json.dumps({"event": "youtube_token_path", "path": str(_TOKEN_PATH.resolve())}))


# ═══════════════════════════════════════════════════════════════════════════
# 1. YOUTUBE CLIENT
# ═══════════════════════════════════════════════════════════════════════════

def get_youtube_client():
    """Load OAuth credentials from token.json and return an authenticated
    YouTube Data API v3 service object.

    Refreshes the token automatically if expired.
    Raises FileNotFoundError if token.json is missing — never triggers OAuth.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not _TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"token.json not found at {_TOKEN_PATH}. "
            "Run 'python setup_youtube_auth.py' first to create it."
        )

    creds = Credentials.from_authorized_user_file(
        str(_TOKEN_PATH),
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired YouTube token ...")
            creds.refresh(Request())
            # Persist the refreshed token
            with open(_TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            logger.info("YouTube token refreshed and saved.")
        else:
            raise RuntimeError(
                "token.json credentials are invalid and cannot be refreshed. "
                "Delete token.json and re-run: python setup_youtube_auth.py"
            )

    return build("youtube", "v3", credentials=creds)


# ═══════════════════════════════════════════════════════════════════════════
# 2. TITLE + DESCRIPTION BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def build_shorts_title(hook_text: str, niche: str) -> str:
    """Build a YouTube Shorts title: '<hook_text> #Shorts'.

    Max 100 characters total — truncates hook_text if needed.
    """
    suffix = " #Shorts"
    normalized = hook_text.strip() or "Must watch this!"

    if "#shorts" in normalized.lower():
        max_title = 100
        return normalized[:max_title]

    max_hook = 100 - len(suffix)
    truncated = normalized[:max_hook] if len(normalized) > max_hook else normalized
    return f"{truncated}{suffix}"


def build_shorts_description(clip_row) -> str:
    """Build a 2-3 line YouTube Shorts description from the clip row.

    Includes hook text, niche context, and hashtags.
    Kept under 300 characters.
    """
    hook = clip_row["hook_text"] or "Check this out!"
    niche = clip_row["niche"] or "content"

    # Sanitise niche for hashtag (no spaces)
    niche_tag = niche.replace(" ", "").lower()

    footer = f"#{niche_tag} #viral\n#Shorts"
    max_hook_len = max(0, 300 - len(footer) - 2)
    trimmed_hook = hook[:max_hook_len]

    return f"{trimmed_hook}\n\n{footer}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. DB COLUMN MIGRATION
# ═══════════════════════════════════════════════════════════════════════════

def _ensure_youtube_id_column(conn) -> None:
    """Add youtube_id TEXT column if it doesn't exist yet."""
    try:
        conn.execute("ALTER TABLE clips ADD COLUMN youtube_id TEXT")
        conn.commit()
    except Exception:
        # Column already exists — that's fine
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 4. UPLOAD A SINGLE CLIP
# ═══════════════════════════════════════════════════════════════════════════

def upload_clip(clip_id: int) -> Optional[str]:
    """Upload a single enhanced clip to YouTube Shorts.

    Steps:
        1. Pull clip row from SQLite by clip_id
        2. Verify final_path exists on disk
        3. Build title + description
        4. Upload via YouTube Data API v3 (private, resumable)
        5. On success: store youtube_id, set status='published'
        6. On failure: set status='upload_failed', log, return None

    Returns the youtube_id string on success, None on failure.
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)

    from src.core.db import get_connection
    from googleapiclient.http import MediaFileUpload

    conn = get_connection()
    _ensure_youtube_id_column(conn)

    # ── 1. Pull clip row ──────────────────────────────────────────────
    row = conn.execute(
        "SELECT * FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise ValueError(f"No clip found with id={clip_id}")

    final_path = row["final_path"]
    if not final_path or not Path(final_path).exists():
        conn.close()
        raise FileNotFoundError(
            f"final_path does not exist on disk: {final_path}"
        )

    niche = row["niche"] or "content"
    hook_text = row["hook_text"] or "Must watch this!"

    # ── 2. Build metadata ─────────────────────────────────────────────
    title = build_shorts_title(hook_text, niche)
    description = build_shorts_description(row)

    logger.info(
        "Uploading clip #%d — title: %s", clip_id, title
    )
    print(f"  Uploading clip #{clip_id}: {title}")

    # ── 3. Upload to YouTube ──────────────────────────────────────────
    try:
        youtube = get_youtube_client()

        testing_mode = os.getenv("TESTING", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        # SAFETY: When TESTING=true is explicitly set, force private to prevent accidental public uploads.
        # Default to public in all other cases (production, development, missing env vars).
        privacy_status = "private" if testing_mode else "public"

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": ["shorts", niche, "viral"],
                "categoryId": "22",  # People & Blogs — safe default
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
                "madeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(Path(final_path).resolve()),
            mimetype="video/mp4",
            chunksize=1024 * 1024,
            resumable=True,
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = request.execute()
        youtube_id = response.get("id", "")

    except Exception as exc:
        # ── API error: mark as failed, do NOT raise ───────────────────
        logger.error(
            "YouTube upload failed for clip #%d: %s", clip_id, exc
        )
        print(f"  ❌ Upload failed for clip #{clip_id}: {exc}")
        try:
            conn.execute(
                "UPDATE clips SET status = 'upload_failed' WHERE id = ?",
                (clip_id,),
            )
            conn.commit()
        except Exception:
            pass
        conn.close()
        return None

    # ── 4. Store youtube_id IMMEDIATELY ────────────────────────────────
    if youtube_id:
        conn.execute(
            "UPDATE clips SET youtube_id = ?, status = 'published' WHERE id = ?",
            (youtube_id, clip_id),
        )
        conn.commit()
        logger.info(
            "Clip #%d published — youtube_id=%s", clip_id, youtube_id
        )
        print(f"  ✅ Clip #{clip_id} published — youtube_id: {youtube_id}")
    else:
        conn.execute(
            "UPDATE clips SET status = 'upload_failed' WHERE id = ?",
            (clip_id,),
        )
        conn.commit()
        logger.warning("YouTube returned no video ID for clip #%d", clip_id)
        print(f"  ⚠️  No youtube_id returned for clip #{clip_id}")

    conn.close()
    return youtube_id if youtube_id else None


# ═══════════════════════════════════════════════════════════════════════════
# 5. BATCH PUBLISH
# ═══════════════════════════════════════════════════════════════════════════

def publish_ready_clips(niche: Optional[str] = None) -> list[str]:
    """Upload all clips with status='enhanced' to YouTube.

    Args:
        niche: If provided, only upload clips for this niche.

    Returns:
        List of youtube_id strings for successfully uploaded clips.
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)

    from src.core.db import get_connection

    conn = get_connection()
    _ensure_youtube_id_column(conn)

    if niche:
        rows = conn.execute(
            "SELECT id FROM clips WHERE status = 'enhanced' AND niche = ?",
            (niche,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM clips WHERE status = 'enhanced'"
        ).fetchall()

    conn.close()

    total = len(rows)
    if total == 0:
        print("No clips with status='enhanced' found.")
        return []

    print(f"\n{'=' * 60}")
    print(f"  Publishing {total} enhanced clip(s) to YouTube Shorts")
    if niche:
        print(f"  Niche filter: {niche}")
    print(f"{'=' * 60}\n")

    uploaded: list[str] = []
    failed = 0

    for row in rows:
        clip_id = row["id"]
        yt_id = upload_clip(clip_id)
        if yt_id:
            uploaded.append(yt_id)
        else:
            failed += 1

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  PUBLISH SUMMARY")
    print(f"  Total:    {total}")
    print(f"  Uploaded: {len(uploaded)}")
    print(f"  Failed:   {failed}")
    if uploaded:
        print(f"\n  YouTube IDs:")
        for yt_id in uploaded:
            print(f"    • {yt_id}")
            print(f"      https://studio.youtube.com/video/{yt_id}/edit")
    print(f"{'=' * 60}")

    return uploaded
