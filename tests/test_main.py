"""Unit tests for ClipShare Multi-Platform View Verification Scraper."""

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
import requests

from app.main import (
    app,
    extract_video_id,
    extract_youtube_id,
    extract_x_id,
    extract_instagram_id,
    detect_platform,
)

client = TestClient(app)


# --- 1. Health & Docs ---

def test_health_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "version" in data
    assert "platforms" in data
    assert set(data["platforms"]) == {"youtube", "x", "instagram"}


def test_docs_endpoint():
    response = client.get("/docs")
    assert response.status_code == 200


# --- 2. Platform Detection Tests ---

def test_detect_platform():
    assert detect_platform("https://www.youtube.com/watch?v=sABBTdkLbhc") == "youtube"
    assert detect_platform("https://youtu.be/sABBTdkLbhc") == "youtube"
    assert detect_platform("https://x.com/monad_xyz/status/1777687376136982767") == "x"
    assert detect_platform("https://twitter.com/monad_xyz/status/1777687376136982767") == "x"
    assert detect_platform("https://www.instagram.com/reel/DF2157_SflV/") == "instagram"
    with pytest.raises(ValueError):
        detect_platform("https://vimeo.com/12345678901")


# --- 3. YouTube URL Validation Tests ---

@pytest.mark.parametrize(
    "url,expected_id",
    [
        ("https://www.youtube.com/shorts/jeykyQosIWU", "jeykyQosIWU"),
        ("https://youtube.com/shorts/jeykyQosIWU", "jeykyQosIWU"),
        ("https://m.youtube.com/shorts/jeykyQosIWU", "jeykyQosIWU"),
        ("https://www.youtube.com/shorts/jeykyQosIWU?feature=share", "jeykyQosIWU"),
        ("https://www.youtube.com/shorts/jeykyQosIWU/", "jeykyQosIWU"),
        ("https://www.youtube.com/watch?v=jeykyQosIWU", "jeykyQosIWU"),
        ("https://youtube.com/watch?v=jeykyQosIWU", "jeykyQosIWU"),
        ("https://www.youtube.com/watch?v=jeykyQosIWU&t=10s", "jeykyQosIWU"),
        ("https://youtu.be/jeykyQosIWU", "jeykyQosIWU"),
        ("https://youtu.be/jeykyQosIWU?si=AbCdEfGhIjK", "jeykyQosIWU"),
    ],
)
def test_valid_youtube_urls(url, expected_id):
    assert extract_youtube_id(url) == expected_id
    assert extract_video_id(url) == expected_id


@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://www.youtube.com/shorts/jeykyQosIWU",  # Insecure scheme
        "ftp://www.youtube.com/shorts/jeykyQosIWU",   # Invalid scheme
        "https://vimeo.com/12345678901",              # Unsupported host
        "https://evil-youtube.com/shorts/jeykyQosIWU",# Phishing host
        "https://www.youtube.com/shorts/short",       # ID too short
        "https://www.youtube.com/shorts/waytoolongvideoid123", # ID too long
        "https://www.youtube.com/channel/UC12345678", # Channel URL
        "https://www.youtube.com/",                   # Root URL without video
        "not-a-url",                                  # Garbage string
        "",                                           # Empty string
    ],
)
def test_invalid_youtube_urls(invalid_url):
    with pytest.raises(ValueError):
        extract_youtube_id(invalid_url)


# --- 4. X (Twitter) URL Validation Tests ---

@pytest.mark.parametrize(
    "url,expected_id",
    [
        ("https://x.com/monad_xyz/status/1777687376136982767", "1777687376136982767"),
        ("https://twitter.com/monad_xyz/status/1777687376136982767", "1777687376136982767"),
        ("https://x.com/monad_xyz/status/1777687376136982767?s=20", "1777687376136982767"),
        ("https://x.com/status/1777687376136982767/", "1777687376136982767"),
    ],
)
def test_valid_x_urls(url, expected_id):
    assert extract_x_id(url) == expected_id


@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://x.com/monad_xyz/status/1777687376136982767",  # Insecure
        "https://x.com/monad_xyz",                            # Profile, no status
        "https://x.com/monad_xyz/status/notanid",             # Non-numeric ID
        "https://other.com/monad_xyz/status/1777687376136982767",
    ],
)
def test_invalid_x_urls(invalid_url):
    with pytest.raises(ValueError):
        extract_x_id(invalid_url)


# --- 5. Instagram URL Validation Tests ---

@pytest.mark.parametrize(
    "url,expected_id",
    [
        ("https://www.instagram.com/reel/DF2157_SflV/", "DF2157_SflV"),
        ("https://instagram.com/reel/DF2157_SflV", "DF2157_SflV"),
        ("https://www.instagram.com/p/DF2157_SflV/", "DF2157_SflV"),
        ("https://instagram.com/p/DF2157_SflV?igsh=123", "DF2157_SflV"),
    ],
)
def test_valid_instagram_urls(url, expected_id):
    assert extract_instagram_id(url) == expected_id


@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://www.instagram.com/reel/DF2157_SflV/",  # Insecure
        "https://www.instagram.com/username/",         # Profile URL
        "https://www.instagram.com/reel/ab",           # Too short
    ],
)
def test_invalid_instagram_urls(invalid_url):
    with pytest.raises(ValueError):
        extract_instagram_id(invalid_url)


def test_verify_rejects_unsupported_platform():
    response = client.post(
        "/verify",
        json={"url": "https://vimeo.com/12345678901", "target_views": 10000},
    )
    assert response.status_code == 422
    assert "Unsupported platform" in response.json()["detail"]


def test_verify_rejects_invalid_target_views():
    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 0},
    )
    assert response.status_code == 422


# --- 6. YouTube Verification Scenarios (Mocked) ---

def make_mock_youtube_html(view_count=None, is_ok=True, unavailable_reason=None):
    if not is_ok:
        payload = {
            "playabilityStatus": {
                "status": "ERROR",
                "reason": unavailable_reason or "This video is unavailable",
            }
        }
    else:
        payload = {
            "playabilityStatus": {"status": "OK"},
            "videoDetails": {
                "videoId": "jeykyQosIWU",
                "viewCount": str(view_count) if view_count is not None else None,
            },
        }
    import json
    return f"""
    <!DOCTYPE html>
    <html>
      <head><title>Test YouTube Video</title></head>
      <body>
        <script>
          var ytInitialPlayerResponse = {json.dumps(payload)};
        </script>
      </body>
    </html>
    """


@patch("app.main.requests.get")
def test_youtube_views_above_target(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = make_mock_youtube_html(view_count=15000, is_ok=True)
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "youtube"
    assert data["video_id"] == "jeykyQosIWU"
    assert data["views"] == 15000
    assert data["target_views"] == 10000
    assert data["eligible"] is True
    assert data["status"] == "target_reached"
    assert data["source"] == "youtube_player_response"
    assert "timestamp" in data


@patch("app.main.requests.get")
def test_youtube_views_equal_to_target(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = make_mock_youtube_html(view_count=10000, is_ok=True)
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] == 10000
    assert data["eligible"] is True
    assert data["status"] == "target_reached"


@patch("app.main.requests.get")
def test_youtube_views_below_target(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = make_mock_youtube_html(view_count=5000, is_ok=True)
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] == 5000
    assert data["eligible"] is False
    assert data["status"] == "below_target"


@patch("app.main.requests.get")
def test_youtube_missing_or_inaccessible_video(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = make_mock_youtube_html(is_ok=False, unavailable_reason="This video is private")
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] is None
    assert data["eligible"] is False
    assert data["status"] == "unable_to_verify"
    assert "Video unavailable: This video is private" in data["reason"]


@patch("app.main.requests.get")
def test_youtube_missing_view_count_metadata(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><div>Some YouTube Page without view count</div></body></html>"
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] is None
    assert data["eligible"] is False
    assert data["status"] == "unable_to_verify"
    assert "readable view count" in data["reason"]


@patch("app.main.requests.get")
def test_youtube_http_404_not_found(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] is None
    assert data["eligible"] is False
    assert data["status"] == "unable_to_verify"
    assert "HTTP 404" in data["reason"]


@patch("app.main.requests.get")
def test_youtube_rate_limit_http_429(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] is None
    assert data["eligible"] is False
    assert data["status"] == "unable_to_verify"
    assert "HTTP 429" in data["reason"]


@patch("app.main.requests.get")
def test_youtube_consent_screen_handling(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><h1>Before you continue to YouTube</h1><form action='https://consent.google.com'></form></body></html>"
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] is None
    assert data["eligible"] is False
    assert data["status"] == "unable_to_verify"
    assert "consent page" in data["reason"]


@patch("app.main.requests.get")
def test_youtube_upstream_timeout(mock_get):
    mock_get.side_effect = requests.Timeout("Connection timed out")

    response = client.post(
        "/verify",
        json={"url": "https://www.youtube.com/shorts/jeykyQosIWU", "target_views": 10000},
    )
    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]


# --- 7. X (Twitter) Verification Tests (Mocked) ---

@patch("app.main.requests.get")
def test_x_views_above_target(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 200,
        "message": "OK",
        "tweet": {"id": "1777687376136982767", "views": 25000},
    }
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://x.com/monad_xyz/status/1777687376136982767", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "x"
    assert data["video_id"] == "1777687376136982767"
    assert data["views"] == 25000
    assert data["eligible"] is True
    assert data["status"] == "target_reached"
    assert data["source"] == "x_syndication_api"


@patch("app.main.requests.get")
def test_x_views_below_target(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 200,
        "message": "OK",
        "tweet": {"id": "1777687376136982767", "views": 4000},
    }
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://x.com/monad_xyz/status/1777687376136982767", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] == 4000
    assert data["eligible"] is False
    assert data["status"] == "below_target"


@patch("app.main.requests.get")
def test_x_post_not_found(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://x.com/monad_xyz/status/00000000000", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "x"
    assert data["views"] is None
    assert data["eligible"] is False
    assert data["status"] == "unable_to_verify"
    assert "HTTP 404" in data["reason"]


# --- 8. Instagram Verification Tests ---

@patch("app.main.requests.get")
def test_instagram_login_wall(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body>Login to Instagram</body></html>"
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.instagram.com/reel/DF2157_SflV/", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "instagram"
    assert data["video_id"] == "DF2157_SflV"
    assert data["views"] is None
    assert data["eligible"] is False
    assert data["status"] == "unable_to_verify"
    assert "Instagram login wall" in data["reason"]


@patch("app.main.requests.get")
def test_instagram_views_above_target(mock_get):
    """Authenticated session successfully reads reel views above the target."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_resp.json.return_value = {"items": [{"play_count": 25000, "code": "DF2157_SflV"}]}
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.instagram.com/reel/DF2157_SflV/", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "instagram"
    assert data["video_id"] == "DF2157_SflV"
    assert data["views"] == 25000
    assert data["target_views"] == 10000
    assert data["eligible"] is True
    assert data["status"] == "target_reached"
    assert data["source"] == "instagram_session_api"
    assert data["reason"] is None


@patch("app.main.requests.get")
def test_instagram_views_below_target(mock_get):
    """Authenticated session reads reel views that are below the campaign target."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_resp.json.return_value = {"items": [{"play_count": 4000}]}
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.instagram.com/reel/DF2157_SflV/", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] == 4000
    assert data["eligible"] is False
    assert data["status"] == "below_target"
    assert data["source"] == "instagram_session_api"


@patch("app.main.requests.get")
def test_instagram_views_view_count_alias(mock_get):
    """Some media items expose view_count / video_view_count instead of play_count."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_resp.json.return_value = {"items": [{"view_count": 18400}]}
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.instagram.com/reel/DF2157_SflV/", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] == 18400
    assert data["eligible"] is True
    assert data["status"] == "target_reached"
    assert data["source"] == "instagram_session_api"


@patch("app.main.requests.get")
def test_instagram_post_not_found(mock_get):
    """A missing/invalid media id yields a clear 'not found' reason, not a crash."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = ""
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.instagram.com/reel/DF2157_SflV/", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "instagram"
    assert data["views"] is None
    assert data["eligible"] is False
    assert data["status"] == "unable_to_verify"
    assert "not found" in data["reason"].lower()


@patch("app.main.requests.get")
def test_instagram_session_expired(mock_get):
    """An invalid/expired session id is surfaced as a session-expiry reason."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = ""
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.instagram.com/reel/DF2157_SflV/", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] is None
    assert data["status"] == "unable_to_verify"
    assert "session" in data["reason"].lower()
    assert "expired" in data["reason"].lower()


@patch("app.main.requests.get")
def test_instagram_rate_limit(mock_get):
    """HTTP 429 from Instagram is reported as a rate-limit reason."""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = ""
    mock_get.return_value = mock_resp

    response = client.post(
        "/verify",
        json={"url": "https://www.instagram.com/reel/DF2157_SflV/", "target_views": 10000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["views"] is None
    assert data["status"] == "unable_to_verify"
    assert "429" in data["reason"]


@patch("app.main.requests.get")
def test_instagram_upstream_timeout(mock_get):
    """A connection timeout to Instagram surfaces as a 504 gateway timeout."""
    mock_get.side_effect = requests.Timeout("Connection timed out")

    response = client.post(
        "/verify",
        json={"url": "https://www.instagram.com/reel/DF2157_SflV/", "target_views": 10000},
    )
    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]
