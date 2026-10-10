"""ClipShare Multi-Platform View Verification Scraper.

Standalone backend verification service for ClipShare. Validates public URLs
and retrieves view counts across YouTube, X (Twitter), and Instagram to determine
campaign target eligibility.
"""

from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import requests

# Load local environment variables from .env or .env.example
load_dotenv(".env")
load_dotenv(".env.example")

APP_VERSION = "1.2.0"

app = FastAPI(
    title="ClipShare Multi-Platform Verifier",
    description="Backend verification service to verify public YouTube, X (Twitter), and Instagram metrics for ClipShare campaigns.",
    version=APP_VERSION,
)

YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "youtu.be"}
X_HOSTS = {"x.com", "twitter.com"}
INSTAGRAM_HOSTS = {"instagram.com"}

YOUTUBE_ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{11}$")
X_ID_REGEX = re.compile(r"^\d{1,25}$")
IG_SHORTCODE_REGEX = re.compile(r"^[A-Za-z0-9_-]{5,35}$")

DEFAULT_TIMEOUT_SECONDS = 10.0
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


class VerifyRequest(BaseModel):
    url: str = Field(
        ...,
        max_length=500,
        description="Public YouTube, X, or Instagram video/post URL",
        examples=[
            "https://www.youtube.com/shorts/9f8bCHqeW-U",
            "https://x.com/monad_xyz/status/1777687376136982767",
            "https://www.instagram.com/reel/DF2157_SflV/",
        ],
    )
    target_views: int = Field(
        default=10000,
        ge=1,
        description="Configurable campaign target views (must be >= 1)",
        examples=[10000],
    )


class VerifyResponse(BaseModel):
    platform: str
    video_id: str
    views: Optional[int] = None
    target_views: int
    eligible: bool
    status: str
    source: Optional[str] = None
    reason: Optional[str] = None
    timestamp: str
    note: str = "Prototype result, not a final payout approval."


class HealthResponse(BaseModel):
    service: str
    status: str
    version: str
    platforms: List[str]


# =====================================================================
# Platform Detection & URL Validation
# =====================================================================

def detect_platform(url: str) -> str:
    """Detect whether URL belongs to YouTube, X (Twitter), or Instagram."""
    clean_url = url.strip()
    parsed = urlparse(clean_url)

    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Use a valid HTTPS URL.")

    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]

    if host in YOUTUBE_HOSTS or host.endswith(".youtube.com"):
        return "youtube"
    elif host in X_HOSTS or host.endswith(".twitter.com") or host.endswith(".x.com"):
        return "x"
    elif host in INSTAGRAM_HOSTS or host.endswith(".instagram.com"):
        return "instagram"
    else:
        raise ValueError(
            "Unsupported platform. Only YouTube, X (Twitter), and Instagram URLs are supported."
        )


def extract_youtube_id(url: str) -> str:
    """Validate YouTube URL and extract 11-character video ID."""
    clean_url = url.strip()
    parsed = urlparse(clean_url)

    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Use a valid HTTPS YouTube URL.")

    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]

    if host not in YOUTUBE_HOSTS and not host.endswith(".youtube.com"):
        raise ValueError("Only YouTube URLs are supported.")

    video_id = ""
    path = parsed.path.strip("/")

    if host == "youtu.be":
        parts = path.split("/")
        if parts and parts[0]:
            video_id = parts[0]
    elif path.startswith("shorts/"):
        parts = path.split("/")
        if len(parts) >= 2 and parts[1]:
            video_id = parts[1]
    elif path == "watch":
        query_params = parse_qs(parsed.query)
        v_list = query_params.get("v")
        if v_list and v_list[0]:
            video_id = v_list[0]
    else:
        raise ValueError("Provide a YouTube Shorts or video URL.")

    if not YOUTUBE_ID_REGEX.fullmatch(video_id):
        raise ValueError("Could not extract a valid 11-character YouTube video ID.")

    return video_id


# Alias for backward compatibility
extract_video_id = extract_youtube_id


def extract_x_id(url: str) -> str:
    """Validate X (Twitter) URL and extract tweet/post ID."""
    clean_url = url.strip()
    parsed = urlparse(clean_url)

    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Use a valid HTTPS X (Twitter) URL.")

    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]

    if host not in X_HOSTS and not host.endswith(".x.com") and not host.endswith(".twitter.com"):
        raise ValueError("Only X (Twitter) URLs are supported.")

    path = parsed.path.strip("/")
    parts = path.split("/")

    tweet_id = ""
    if len(parts) >= 2 and parts[-2] == "status":
        tweet_id = parts[-1]
    elif len(parts) >= 3 and parts[1] == "status":
        tweet_id = parts[2]

    if not X_ID_REGEX.fullmatch(tweet_id):
        raise ValueError("Could not extract a valid X (Twitter) status ID.")

    return tweet_id


def extract_instagram_id(url: str) -> str:
    """Validate Instagram URL and extract post or reel shortcode."""
    clean_url = url.strip()
    parsed = urlparse(clean_url)

    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Use a valid HTTPS Instagram URL.")

    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]

    if host not in INSTAGRAM_HOSTS and not host.endswith(".instagram.com"):
        raise ValueError("Only Instagram URLs are supported.")

    path = parsed.path.strip("/")
    parts = path.split("/")

    if len(parts) >= 2 and parts[0] in {"reel", "reels", "p"}:
        shortcode = parts[1]
    else:
        raise ValueError(
            "Provide an Instagram Reel or Post URL (e.g., https://www.instagram.com/reel/SHORTCODE/)."
        )

    if not IG_SHORTCODE_REGEX.fullmatch(shortcode):
        raise ValueError("Could not extract a valid Instagram shortcode.")

    return shortcode


# =====================================================================
# YouTube Scraper
# =====================================================================

def parse_player_response(text: str) -> Optional[Dict[str, Any]]:
    """Extract ytInitialPlayerResponse JSON payload from HTML script tags."""
    match = re.search(r"ytInitialPlayerResponse\s*=\s*(\{.+?\});", text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return None


def fetch_youtube_views(video_id: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Fetch public YouTube video metadata and parse view count."""
    page_url = f"https://www.youtube.com/watch?v={video_id}"
    headers = {
        "User-Agent": HTTP_USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = requests.get(
            page_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.Timeout:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Upstream request to YouTube timed out.",
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not retrieve the YouTube page.",
        )

    if response.status_code == 429:
        return {"views": None, "source": None, "reason": "YouTube rate limit encountered (HTTP 429)."}
    if response.status_code in (401, 403):
        return {"views": None, "source": None, "reason": f"YouTube access denied (HTTP {response.status_code})."}
    if response.status_code == 404:
        return {"views": None, "source": None, "reason": "Video not found on YouTube (HTTP 404)."}
    if response.status_code in (301, 302, 303, 307, 308):
        location = response.headers.get("Location", "")
        if "consent" in location:
            return {"views": None, "source": None, "reason": "YouTube redirected to consent verification."}
        return {"views": None, "source": None, "reason": f"Unexpected YouTube redirect to: {location}"}
    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YouTube service unavailable (HTTP {response.status_code}).",
        )
    if response.status_code != 200:
        return {"views": None, "source": None, "reason": f"Unexpected YouTube HTTP status {response.status_code}."}

    html = response.text

    if "consent.google.com" in html or "before you continue to YouTube" in html:
        return {"views": None, "source": None, "reason": "YouTube consent page encountered."}

    # Strategy 1: ytInitialPlayerResponse
    player_data = parse_player_response(html)
    if player_data:
        playability = player_data.get("playabilityStatus", {})
        play_status = playability.get("status")
        if play_status and play_status != "OK":
            reason = playability.get("reason") or "Video is unavailable or private."
            return {"views": None, "source": None, "reason": f"Video unavailable: {reason}"}

        details = player_data.get("videoDetails", {})
        view_count_raw = details.get("viewCount")
        if view_count_raw is not None and str(view_count_raw).isdigit():
            return {"views": int(view_count_raw), "source": "youtube_player_response", "reason": None}

        microformat = player_data.get("microformat", {}).get("playerMicroformatRenderer", {})
        micro_views = microformat.get("viewCount")
        if micro_views is not None and str(micro_views).isdigit():
            return {"views": int(micro_views), "source": "player_microformat_metadata", "reason": None}

    # Strategy 2: Direct regex
    view_matches = re.findall(r'"viewCount":\s*"(\d+)"', html)
    if view_matches:
        for match in view_matches:
            if match.isdigit():
                return {"views": int(match), "source": "youtube_page_metadata", "reason": None}

    # Strategy 3: HTML metadata fallback
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta"):
        key = meta.get("itemprop") or meta.get("property") or meta.get("name")
        content = meta.get("content", "")
        if key == "interactionCount" and content.isdigit():
            return {"views": int(content), "source": "page_metadata", "reason": None}

    if "Video unavailable" in html or "This video isn't available anymore" in html:
        return {"views": None, "source": None, "reason": "Video is unavailable or has been removed."}

    return {
        "views": None,
        "source": None,
        "reason": "YouTube did not expose a readable view count. Metadata may be missing or page format changed.",
    }


# Backward compatibility
fetch_view_count = fetch_youtube_views


# =====================================================================
# X (Twitter) Scraper
# =====================================================================

def fetch_x_views(tweet_id: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Fetch public X (Twitter) tweet view/impression count via public syndication service."""
    api_url = f"https://api.fxtwitter.com/status/{tweet_id}"
    headers = {"User-Agent": HTTP_USER_AGENT}

    try:
        response = requests.get(api_url, headers=headers, timeout=timeout)
    except requests.Timeout:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Upstream request to X timed out.",
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not retrieve the X post.",
        )

    if response.status_code == 404:
        return {"views": None, "source": None, "reason": "Post not found or deleted on X (HTTP 404)."}
    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"X service unavailable (HTTP {response.status_code}).",
        )
    if response.status_code != 200:
        return {"views": None, "source": None, "reason": f"Unexpected X status (HTTP {response.status_code})."}

    try:
        data = response.json()
    except Exception:
        return {"views": None, "source": None, "reason": "Could not parse X response JSON."}

    tweet = data.get("tweet") or {}
    views = tweet.get("views")

    if views is not None and isinstance(views, int):
        return {"views": views, "source": "x_syndication_api", "reason": None}

    # Older posts or posts with hidden view metrics
    return {
        "views": None,
        "source": None,
        "reason": "X post does not expose public impressions (metrics may be hidden or post predates view counts).",
    }


# =====================================================================
# Instagram Scraper & Verification
# =====================================================================

# Instagram does not expose a public, unauthenticated view-count API for
# reels/posts. When a local ``INSTAGRAM_SESSION_ID`` cookie is configured,
# public view counts can be read through Instagram's *internal* mobile
# media-info endpoint (``i.instagram.com/api/v1/media/<media_id>/info/``) --
# the same interface the official Instagram app uses. No developer access
# token is required for this.

INSTAGRAM_GRAPH_API_VERSION = "v19.0"

# A first-class Instagram (iPhone) build user-agent. The mobile media-info
# endpoint only returns its JSON payload to a recognised Instagram client UA.
MOBILE_IG_USER_AGENT = (
    "Instagram 278.0.0.19.115 (iPhone14,2; iOS 16_4; en_US; en-US; "
    "scale=3.00; 1170x2532; 459639534)"
)


def shortcode_to_media_id(shortcode: str) -> str:
    """Convert an Instagram shortcode (e.g. DeQyDVrIoXb) to its numeric media ID.

    Instagram media ids are a base-64 encoding (alphabet ``A-Za-z0-9-_``) of a
    numeric id. The internal mobile media-info endpoint takes this numeric id,
    not the human-readable shortcode.
    """
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    media_id = 0
    for char in shortcode:
        idx = alphabet.find(char)
        if idx == -1:
            raise ValueError(f"Invalid character in shortcode: {char}")
        media_id = (media_id * 64) + idx
    return str(media_id)


def _ig_session_headers(session_id: str, user_id: str) -> Dict[str, str]:
    """Build request headers authenticating as the session owner."""
    return {
        "User-Agent": MOBILE_IG_USER_AGENT,
        "Accept-Language": "en-US",
        "Accept": "*/*",
        "x-ig-app-id": "936619743392459",
        "Cookie": f"ds_user_id={user_id}; sessionid={session_id};",
    }


def _ig_view_count_from_item(item: Any) -> Optional[int]:
    """Extract the first available numeric view/play count from a media item."""
    if not isinstance(item, dict):
        return None
    for key in (
        "play_count",
        "ig_play_count",
        "video_play_count",
        "view_count",
        "video_view_count",
    ):
        value = item.get(key)
        if value is not None and str(value).isdigit():
            return int(value)
    return None


def _instagram_upstream_error(detail: str, status_code: int = status.HTTP_502_BAD_GATEWAY) -> HTTPException:
    """Build a consistent upstream-failure HTTPException for Instagram calls."""
    return HTTPException(status_code=status_code, detail=detail)


def fetch_instagram_views(shortcode: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Fetch an Instagram Reel/Post view count.

    Resolution order (returns the first definitive answer):
      1. Meta Graph API (``INSTAGRAM_ACCESS_TOKEN``) -- official, only used when
         a token is configured and only returns insights for owned content.
      2. Authenticated internal mobile media-info endpoint using the local
         ``INSTAGRAM_SESSION_ID`` cookie. This is the primary method for users
         without a developer access token and works for *public* reels/posts.
      3. Public embed fallback -- reads whatever view count is rendered in the
         embed HTML, and otherwise detects Meta's unauthenticated "login wall"
         so callers get a clear reason instead of a silent failure.
    """
    # --- 1. Official Meta Graph API (only with a configured access token) ---
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if access_token:
        result = _fetch_instagram_via_graph_api(shortcode, access_token, timeout)
        if result is not None:
            return result

    # --- 2. Session-cookie verification (primary local method) ---
    session_id = os.getenv("INSTAGRAM_SESSION_ID")
    if session_id:
        session_id = session_id.strip()
        user_id = session_id.split("%3A")[0].split(":")[0]
        result = _fetch_instagram_via_session_api(shortcode, session_id, user_id, timeout)
        if result is not None:
            return result

    # --- 3. Public, unauthenticated embed fallback ---
    return _fetch_instagram_via_embed(shortcode, timeout)


def _fetch_instagram_via_graph_api(shortcode: str, access_token: str, timeout: float) -> Optional[Dict[str, Any]]:
    """Return a view-count result dict via the official Meta Graph API, or None."""
    graph_url = (
        f"https://graph.facebook.com/{INSTAGRAM_GRAPH_API_VERSION}/{shortcode}/insights"
        f"?metric=plays,reach&access_token={access_token}"
    )
    try:
        resp = requests.get(graph_url, timeout=timeout)
    except requests.Timeout:
        raise _instagram_upstream_error("Upstream request to Instagram timed out.", status.HTTP_504_GATEWAY_TIMEOUT)
    except requests.RequestException:
        raise _instagram_upstream_error("Could not retrieve the Instagram resource.")

    if resp.status_code == 404:
        return {"views": None, "source": None, "reason": "Instagram post/reel not found (HTTP 404)."}
    if resp.status_code >= 500:
        raise _instagram_upstream_error(f"Instagram service unavailable (HTTP {resp.status_code}).")
    if resp.status_code != 200:
        return None  # fall through to session / embed strategies

    try:
        data = resp.json()
    except Exception:
        return None
    for metric in data.get("data", []):
        if metric.get("name") in {"plays", "reach"}:
            values = metric.get("values", [{}])
            val = values[0].get("value") if values else None
            if val is not None:
                return {"views": int(val), "source": "instagram_graph_api", "reason": None}
    return None


def _fetch_instagram_via_session_api(shortcode: str, session_id: str, user_id: str, timeout: float) -> Optional[Dict[str, Any]]:
    """Return a view-count result dict via the authenticated mobile media-info API.

    Returns a result dict for a definitive answer, or ``None`` to signal the
    caller should try the next strategy.
    """
    try:
        media_id = shortcode_to_media_id(shortcode)
    except ValueError:
        return {"views": None, "source": None, "reason": "Invalid Instagram shortcode."}

    api_url = f"https://i.instagram.com/api/v1/media/{media_id}/info/"
    try:
        resp = requests.get(api_url, headers=_ig_session_headers(session_id, user_id), timeout=timeout)
    except requests.Timeout:
        raise _instagram_upstream_error("Upstream request to Instagram timed out.", status.HTTP_504_GATEWAY_TIMEOUT)
    except requests.RequestException:
        raise _instagram_upstream_error("Could not retrieve the Instagram resource.")

    # 200: parse the media JSON returned by the mobile media-info endpoint.
    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            # 200 but not JSON (e.g. an HTML interstitial slipped through) --
            # fall through to the next strategy.
            return None
        items = data.get("items") or []
        if items and (count := _ig_view_count_from_item(items[0])) is not None:
            return {"views": count, "source": "instagram_session_api", "reason": None}
        # Exists but isn't a viewable video (e.g. a photo post) -- fall through.
        return None

    if resp.status_code == 429:
        return {"views": None, "source": None, "reason": "Instagram rate limit encountered (HTTP 429)."}
    if resp.status_code in (400, 404):
        # Instagram answers with HTTP 400 "Media not found or unavailable" for
        # bad/missing/removed media.
        return {"views": None, "source": None, "reason": f"Instagram post/reel not found (HTTP {resp.status_code})."}
    if resp.status_code in (401, 403):
        return {"views": None, "source": None, "reason": f"Instagram session ID is invalid or expired (HTTP {resp.status_code})."}
    if resp.status_code >= 500:
        raise _instagram_upstream_error(f"Instagram service unavailable (HTTP {resp.status_code}).")
    # Unrecognised status -- fall through to the public embed strategy.
    return None


def _fetch_instagram_via_embed(shortcode: str, timeout: float) -> Dict[str, Any]:
    """Public embed fallback: read an embed-rendered view count or detect the login wall."""
    embed_url = f"https://www.instagram.com/reel/{shortcode}/embed/captioned/"
    headers = {"User-Agent": HTTP_USER_AGENT}
    try:
        resp = requests.get(embed_url, headers=headers, timeout=timeout)
    except requests.Timeout:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Upstream request to Instagram timed out.")
    except requests.RequestException:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not connect to Instagram.")

    if resp.status_code == 200:
        html = resp.text or ""
        matches = re.findall(r"(\d[\d,.]*)\s*(?:views|plays)", html, re.IGNORECASE)
        if matches:
            clean_num = re.sub(r"[^\d]", "", matches[0])
            if clean_num.isdigit():
                return {"views": int(clean_num), "source": "instagram_embed_metadata", "reason": None}
        return _instagram_login_wall_reason()

    if resp.status_code == 404:
        return {"views": None, "source": None, "reason": "Instagram post/reel not found (HTTP 404)."}
    if resp.status_code >= 500:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Instagram service unavailable (HTTP {resp.status_code}).")
    return {"views": None, "source": None, "reason": f"Unexpected Instagram HTTP status {resp.status_code}."}


def _instagram_login_wall_reason() -> Dict[str, Any]:
    """Standard reason returned when Meta blocks an unauthenticated request."""
    return {
        "views": None,
        "source": None,
        "reason": (
            "Instagram login wall encountered. Meta restricts unauthenticated scraping of Reels. "
            "To verify Instagram reels, set INSTAGRAM_SESSION_ID in your local .env file "
            "(or configure INSTAGRAM_ACCESS_TOKEN for the Meta Graph API)."
        ),
    }


# =====================================================================
# FastAPI Endpoints
# =====================================================================

@app.get("/", response_model=HealthResponse)
def health():
    """Service health, version, and supported platforms check."""
    return {
        "service": "ClipShare Multi-Platform Verifier",
        "status": "running",
        "version": APP_VERSION,
        "platforms": ["youtube", "x", "instagram"],
    }


@app.post("/verify", response_model=VerifyResponse)
def verify_content(request: VerifyRequest):
    """Verify views/impressions for YouTube, X (Twitter), or Instagram content against campaign target."""
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        platform = detect_platform(request.url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    try:
        if platform == "youtube":
            item_id = extract_youtube_id(request.url)
            result = fetch_youtube_views(item_id)
        elif platform == "x":
            item_id = extract_x_id(request.url)
            result = fetch_x_views(item_id)
        elif platform == "instagram":
            item_id = extract_instagram_id(request.url)
            result = fetch_instagram_views(item_id)
        else:
            raise ValueError("Unsupported platform.")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    views = result.get("views")

    if views is None:
        return VerifyResponse(
            platform=platform,
            video_id=item_id,
            views=None,
            target_views=request.target_views,
            eligible=False,
            status="unable_to_verify",
            source=None,
            reason=result.get("reason"),
            timestamp=now_iso,
        )

    is_eligible = views >= request.target_views
    verif_status = "target_reached" if is_eligible else "below_target"

    return VerifyResponse(
        platform=platform,
        video_id=item_id,
        views=views,
        target_views=request.target_views,
        eligible=is_eligible,
        status=verif_status,
        source=result.get("source"),
        reason=None,
        timestamp=now_iso,
    )


# =====================================================================
# CLI Runner
# =====================================================================

def run_cli():
    """Run verification directly from command line."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Verify metrics for YouTube, X (Twitter), or Instagram content against campaign targets."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Content URL (YouTube Shorts/video, X status, or Instagram Reel)",
    )
    parser.add_argument(
        "--target",
        "-t",
        type=int,
        default=10000,
        help="Target view threshold (default: 10000)",
    )
    args = parser.parse_args()

    url = args.url
    target_views = args.target

    if not url:
        try:
            url = input("Enter YouTube, X, or Instagram URL: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)

    if not url:
        print("[ERROR] No URL provided.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(" ClipShare Multi-Platform View Verifier (CLI)")
    print("=" * 60)
    print(f"URL:          {url}")
    print(f"Target views: {target_views:,}")

    try:
        platform = detect_platform(url)
    except ValueError as e:
        print(f"\n[ERROR] Unsupported platform: {e}")
        sys.exit(1)

    print(f"Platform:     {platform.upper()}")

    try:
        if platform == "youtube":
            item_id = extract_youtube_id(url)
            print(f"Item ID:      {item_id}")
            print("Checking YouTube page...")
            result = fetch_youtube_views(item_id)
        elif platform == "x":
            item_id = extract_x_id(url)
            print(f"Item ID:      {item_id}")
            print("Checking X (Twitter) post...")
            result = fetch_x_views(item_id)
        elif platform == "instagram":
            item_id = extract_instagram_id(url)
            print(f"Item ID:      {item_id}")
            print("Checking Instagram Reel/Post...")
            result = fetch_instagram_views(item_id)
        else:
            print("[ERROR] Unknown platform.")
            sys.exit(1)
    except ValueError as e:
        print(f"\n[ERROR] Invalid URL: {e}")
        sys.exit(1)
    except HTTPException as e:
        print(f"\n[ERROR] Upstream failure ({e.status_code}): {e.detail}")
        sys.exit(1)

    views = result.get("views")
    if views is None:
        print("\n" + "-" * 60)
        print("[RESULT] Status: UNABLE TO VERIFY")
        print(f"Reason:  {result.get('reason')}")
        print("Eligible: NO")
        print("-" * 60 + "\n")
        return

    eligible = views >= target_views
    status_label = "TARGET REACHED" if eligible else "BELOW TARGET"

    print("\n" + "-" * 60)
    print(f"Current Views: {views:,}")
    print(f"Target Views:  {target_views:,}")
    print(f"Status:        {status_label}")
    print(f"Eligible:      {'YES (Reward requirement met)' if eligible else 'NO (Below target requirement)'}")
    print(f"Source:        {result.get('source')}")
    print("-" * 60 + "\n")


if __name__ == "__main__":
    run_cli()
