import inspect
import sys
import types
from pathlib import Path

from celery_app import app

from clip_publisher import (
    build_shorts_description,
    build_shorts_title,
    upload_clip,
)
from config.settings import settings
from src.trend_engine.collector import YouTubeTrendCollector
from src.utils.models import NicheConfig
from src.core import db as db_module
from tasks.clip_tasks import _apply_viral_score_gate, _get_min_viral_score


def _use_temp_database(monkeypatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "shorts-pipeline.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(db_module, "_DB_PATH", None)
    db_module.init_database()
    return db_path


def _install_fake_media_upload(monkeypatch) -> None:
    googleapiclient_module = types.ModuleType("googleapiclient")
    googleapiclient_module.__path__ = []
    http_module = types.ModuleType("googleapiclient.http")
    http_module.__package__ = "googleapiclient"

    class FakeMediaFileUpload:
        def __init__(self, filename: str, mimetype: str, chunksize: int, resumable: bool):
            self.filename = filename
            self.mimetype = mimetype
            self.chunksize = chunksize
            self.resumable = resumable

    http_module.MediaFileUpload = FakeMediaFileUpload
    googleapiclient_module.http = http_module
    monkeypatch.setitem(sys.modules, "googleapiclient", googleapiclient_module)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", http_module)


def _insert_clip_row(final_path: Path) -> int:
    conn = db_module.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO clips (url, niche, final_path, hook_text, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "https://youtube.com/watch?v=source-video",
                "technology",
                str(final_path),
                "Launch day update",
                "enhanced",
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _upload_clip_and_get_privacy_status(
    tmp_path: Path,
    monkeypatch,
    testing_value: str | None,
    youtube_id: str = "yt-test",
) -> str:
    _use_temp_database(monkeypatch, tmp_path)
    _install_fake_media_upload(monkeypatch)
    final_path = tmp_path / "clip.mp4"
    final_path.write_bytes(b"test-video")
    clip_id = _insert_clip_row(final_path)
    captured: dict[str, object] = {}

    class FakeInsertRequest:
        def execute(self) -> dict:
            return {"id": youtube_id}

    class FakeVideosService:
        def insert(self, *, part: str, body: dict, media_body) -> FakeInsertRequest:
            captured["part"] = part
            captured["body"] = body
            captured["media_body"] = media_body
            return FakeInsertRequest()

    class FakeYouTubeService:
        def videos(self) -> FakeVideosService:
            return FakeVideosService()

    if testing_value is None:
        monkeypatch.delenv("TESTING", raising=False)
    else:
        monkeypatch.setenv("TESTING", testing_value)
    monkeypatch.setattr("clip_publisher.get_youtube_client", lambda: FakeYouTubeService())

    assert upload_clip(clip_id) == youtube_id
    return captured["body"]["status"]["privacyStatus"]


def _collect_youtube_trends_for_video_items(
    monkeypatch,
    video_items: list[dict],
) -> list:
    collector = YouTubeTrendCollector()
    niche = NicheConfig(
        name="technology",
        display_name="Tech & AI",
        description="Latest technology trends",
        keywords=[],
    )
    video_ids = [item["id"] for item in video_items]

    def fake_request_json(url: str, params: dict | None = None) -> dict:
        if url.endswith("/search"):
            return {
                "items": [
                    {"id": {"videoId": video_id}}
                    for video_id in video_ids
                ]
            }
        return {"items": video_items}

    monkeypatch.setattr(settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(collector, "_request_json", fake_request_json)

    try:
        return collector.collect(niche)
    finally:
        collector.close()


def _youtube_video_item(
    video_id: str,
    duration: str,
    language: str | None = None,
) -> dict:
    snippet = {
        "title": f"Video {video_id}",
        "description": f"Description for {video_id}",
    }
    if language is not None:
        snippet["defaultAudioLanguage"] = language
    return {
        "id": video_id,
        "snippet": snippet,
        "statistics": {"viewCount": "250000"},
        "contentDetails": {"duration": duration},
    }


def _insert_enhanced_clip_with_score(score: float) -> int:
    conn = db_module.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO clips
                (url, niche, clip_path, score, start_sec, end_sec, status, gemini_score, final_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://youtube.com/watch?v=source-video",
                "technology",
                "clip.mp4",
                score,
                0.0,
                30.0,
                "enhanced",
                score,
                "final.mp4",
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _clip_status(clip_id: int) -> str:
    conn = db_module.get_connection()
    try:
        row = conn.execute(
            "SELECT status FROM clips WHERE id = ?",
            (clip_id,),
        ).fetchone()
        return row["status"]
    finally:
        conn.close()


def test_celery_schedule_runs_three_times_daily() -> None:
    schedule_config = app.conf.beat_schedule["run-clip-pipeline-3x-daily"]
    schedule = schedule_config["schedule"]

    assert schedule_config["task"] == "tasks.clip_tasks.run_full_pipeline"
    assert schedule._orig_hour == "8,14,20"
    assert schedule._orig_minute == 0


def test_youtube_duration_parser_handles_long_form_threshold() -> None:
    assert YouTubeTrendCollector._parse_duration_seconds("PT2M59S") == 179
    assert YouTubeTrendCollector._parse_duration_seconds("PT3M") == 180
    assert YouTubeTrendCollector._parse_duration_seconds("PT1H2M3S") == 3723
    assert YouTubeTrendCollector._parse_duration_seconds("P1DT2M") == 86520
    assert YouTubeTrendCollector._parse_duration_seconds("") == 0


def test_youtube_collector_uses_search_then_video_details(tmp_path: Path, monkeypatch) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    collector = YouTubeTrendCollector()
    niche = NicheConfig(
        name="technology",
        display_name="Tech & AI",
        description="Latest technology trends",
        keywords=["AI", "machine learning", "startups"],
        youtube_category_id="28",
    )
    requests: list[tuple[str, dict | None]] = []

    def fake_request_json(url: str, params: dict | None = None) -> dict:
        requests.append((url, params))
        if url.endswith("/search"):
            return {
                "items": [
                    {"id": {"videoId": "video-1"}},
                    {"id": {"videoId": "video-2"}},
                    {"id": {"videoId": "video-1"}},
                ]
            }
        return {
            "items": [
                {
                    "id": "video-1",
                    "snippet": {
                        "title": "Long-form AI update",
                        "description": "A detailed look at the latest AI news.",
                    },
                    "statistics": {"viewCount": "250000"},
                    "contentDetails": {"duration": "PT5M"},
                },
                {
                    "id": "video-2",
                    "snippet": {
                        "title": "Short AI clip",
                        "description": "Too short to keep.",
                    },
                    "statistics": {"viewCount": "999999"},
                    "contentDetails": {"duration": "PT2M"},
                },
            ]
        }

    monkeypatch.setattr(settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(collector, "_request_json", fake_request_json)

    try:
        trends = collector.collect(niche)
    finally:
        collector.close()

    assert len(requests) == 2
    search_url, search_params = requests[0]
    video_url, video_params = requests[1]

    assert search_url == "https://www.googleapis.com/youtube/v3/search"
    assert search_params["part"] == "id"
    assert search_params["type"] == "video"
    assert search_params["order"] == "viewCount"
    assert search_params["videoCategoryId"] == "28"
    assert search_params["q"] == "AI"
    assert search_params["publishedAfter"].endswith("Z")

    assert video_url == "https://www.googleapis.com/youtube/v3/videos"
    assert video_params["part"] == "snippet,statistics,contentDetails"
    assert video_params["id"] == "video-1,video-2"

    assert len(trends) == 1
    assert trends[0].topic == "Long-form AI update"
    assert trends[0].url == "https://youtube.com/watch?v=video-1"
    assert trends[0].description == "A detailed look at the latest AI news."
    assert trends[0].popularity_score == 2.5


def test_youtube_collector_rejects_non_english_video(monkeypatch) -> None:
    trends = _collect_youtube_trends_for_video_items(
        monkeypatch,
        [_youtube_video_item("video-hi", "PT5M", "hi")],
    )

    assert trends == []


def test_youtube_collector_allows_english_video(monkeypatch) -> None:
    trends = _collect_youtube_trends_for_video_items(
        monkeypatch,
        [_youtube_video_item("video-en", "PT5M", "en")],
    )

    assert len(trends) == 1
    assert trends[0].url == "https://youtube.com/watch?v=video-en"


def test_youtube_collector_rejects_video_over_sixty_minutes(monkeypatch) -> None:
    trends = _collect_youtube_trends_for_video_items(
        monkeypatch,
        [_youtube_video_item("video-long", "PT1H1S", "en")],
    )

    assert trends == []


def test_youtube_collector_allows_video_under_sixty_minutes(monkeypatch) -> None:
    trends = _collect_youtube_trends_for_video_items(
        monkeypatch,
        [_youtube_video_item("video-under", "PT59M59S", "en")],
    )

    assert len(trends) == 1
    assert trends[0].url == "https://youtube.com/watch?v=video-under"


def test_shorts_title_uses_canonical_suffix_without_duplication() -> None:
    assert build_shorts_title("Watch this", "technology") == "Watch this #Shorts"
    assert build_shorts_title("Already tagged #shorts", "technology") == "Already tagged #shorts"


def test_shorts_description_keeps_shorts_marker_at_bottom() -> None:
    row = {
        "hook_text": "A" * 400,
        "niche": "AI News",
    }

    description = build_shorts_description(row)

    assert description.endswith("#Shorts")
    assert "#ainews #viral" in description
    assert len(description) <= 300


def test_keyword_rotation_advances_each_call(tmp_path: Path, monkeypatch) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    niche = NicheConfig(
        name="technology",
        display_name="Tech & AI",
        description="Latest technology trends",
        keywords=["AI", "machine learning", "startups"],
    )

    queries = [YouTubeTrendCollector._build_search_query(niche) for _ in range(4)]

    assert queries == ["AI", "machine learning", "startups", "AI"]
    assert db_module.get_keyword_index(niche.name) == 1


def test_keyword_rotation_single_keyword_no_crash(tmp_path: Path, monkeypatch) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    niche = NicheConfig(
        name="technology",
        display_name="Tech & AI",
        description="Latest technology trends",
        keywords=["AI"],
    )

    assert YouTubeTrendCollector._build_search_query(niche) == "AI"
    assert YouTubeTrendCollector._build_search_query(niche) == "AI"
    assert db_module.get_keyword_index(niche.name) == 0


def test_keyword_rotation_empty_keywords_returns_empty(tmp_path: Path, monkeypatch) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    niche = NicheConfig(
        name="technology",
        display_name="Tech & AI",
        description="Latest technology trends",
        keywords=[],
    )

    assert YouTubeTrendCollector._build_search_query(niche) == ""


def test_video_category_id_preserved_with_rotation(tmp_path: Path, monkeypatch) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    collector = YouTubeTrendCollector()
    niche = NicheConfig(
        name="technology",
        display_name="Tech & AI",
        description="Latest technology trends",
        keywords=["AI", "machine learning"],
        youtube_category_id="28",
    )
    requests: list[tuple[str, dict | None]] = []

    def fake_request_json(url: str, params: dict | None = None) -> dict:
        requests.append((url, params))
        if url.endswith("/search"):
            return {"items": []}
        return {"items": []}

    monkeypatch.setattr(settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(collector, "_request_json", fake_request_json)

    try:
        collector.collect(niche)
    finally:
        collector.close()

    assert requests[0][1]["videoCategoryId"] == "28"
    assert requests[0][1]["q"] == "AI"


def test_published_after_remains_iso_format_with_rotation(tmp_path: Path, monkeypatch) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    collector = YouTubeTrendCollector()
    niche = NicheConfig(
        name="technology",
        display_name="Tech & AI",
        description="Latest technology trends",
        keywords=["AI", "machine learning"],
    )
    requests: list[tuple[str, dict | None]] = []

    def fake_request_json(url: str, params: dict | None = None) -> dict:
        requests.append((url, params))
        return {"items": []}

    monkeypatch.setattr(settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(collector, "_request_json", fake_request_json)

    try:
        collector.collect(niche)
    finally:
        collector.close()

    published_after = requests[0][1]["publishedAfter"]
    assert published_after.endswith("Z")
    assert "T" in published_after
    assert "." not in published_after


def test_upload_privacy_public_when_testing_not_set(tmp_path: Path, monkeypatch) -> None:
    assert _upload_clip_and_get_privacy_status(tmp_path, monkeypatch, None) == "public"


def test_upload_privacy_private_with_testing_env_var(tmp_path: Path, monkeypatch) -> None:
    assert _upload_clip_and_get_privacy_status(tmp_path, monkeypatch, "true") == "private"


def test_upload_privacy_public_with_testing_false(tmp_path: Path, monkeypatch) -> None:
    assert _upload_clip_and_get_privacy_status(tmp_path, monkeypatch, "false") == "public"


def test_upload_privacy_private_with_uppercase_testing_true(
    tmp_path: Path, monkeypatch
) -> None:
    assert _upload_clip_and_get_privacy_status(tmp_path, monkeypatch, "TRUE") == "private"


def test_low_score_clip_is_skipped_at_default_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    monkeypatch.delenv("MIN_VIRAL_SCORE", raising=False)
    clip_id = _insert_enhanced_clip_with_score(3.9)

    assert _apply_viral_score_gate(clip_id, _get_min_viral_score()) is False
    assert _clip_status(clip_id) == "skipped_low_score"


def test_equal_score_clip_is_allowed_at_default_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    monkeypatch.delenv("MIN_VIRAL_SCORE", raising=False)
    clip_id = _insert_enhanced_clip_with_score(4.0)

    assert _apply_viral_score_gate(clip_id, _get_min_viral_score()) is True
    assert _clip_status(clip_id) == "enhanced"


def test_high_score_clip_is_allowed_at_default_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    _use_temp_database(monkeypatch, tmp_path)
    monkeypatch.delenv("MIN_VIRAL_SCORE", raising=False)
    clip_id = _insert_enhanced_clip_with_score(4.1)

    assert _apply_viral_score_gate(clip_id, _get_min_viral_score()) is True
    assert _clip_status(clip_id) == "enhanced"


def test_upload_function_signature_unchanged() -> None:
    sig = inspect.signature(upload_clip)
    assert list(sig.parameters.keys()) == ["clip_id"]
