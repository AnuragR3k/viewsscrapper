# ClipShare Multi-Platform View Verifier

A standalone backend verification microservice for ClipShare (Monad Hackathon). Verifies public view and impression metrics across **YouTube Shorts & Videos**, **X (formerly Twitter) Posts**, and **Instagram Reels/Posts** against campaign target thresholds.

---

## Supported Platforms

| Platform | Supported Formats | View Metric Source | Authentication Needed? |
|---|---|---|---|
| **YouTube** | `/shorts/ID`, `/watch?v=ID`, `youtu.be/ID` | `ytInitialPlayerResponse` / metadata | **No** (Public scraping) |
| **X (Twitter)** | `x.com/user/status/ID`, `twitter.com/status/ID` | Public syndication & impressions API | **No** (Public impressions) |
| **Instagram** | `/reel/SHORTCODE/`, `/p/SHORTCODE/` | Internal mobile media-info endpoint (`play_count`) | **Recommended** (`INSTAGRAM_SESSION_ID`) |

> **Note on Instagram:**  
> Meta strictly walls unauthenticated Reel view counts behind login redirects and anti-scraping blocks. The verifier therefore uses your local `INSTAGRAM_SESSION_ID` cookie to query Instagram's internal mobile media-info endpoint (`/api/v1/media/<media_id>/info`) — the same interface the official Instagram app uses — so real view counts can be read **without** a public developer token. Set `INSTAGRAM_SESSION_ID` in your local `.env` (open `instagram.com` in a browser → DevTools → Application → Cookies → `sessionid`). For production at scale, `INSTAGRAM_ACCESS_TOKEN` (Meta Graph API) is also supported.

---

## Quickstart (CLI)

Run directly in PowerShell inside `d:\monad\youtube-view-scraper`:

### 1. YouTube Verification
```powershell
.\.venv\Scripts\python.exe -m app.main "https://www.youtube.com/watch?v=sABBTdkLbhc"
```

### 2. X (Twitter) Verification
```powershell
.\.venv\Scripts\python.exe -m app.main "https://x.com/monad_xyz/status/1777687376136982767"
```

### 3. Instagram Verification
```powershell
.\.venv\Scripts\python.exe -m app.main "https://www.instagram.com/reel/DF2157_SflV/"
```

### 4. Interactive Mode
Omit the URL to enter it interactively:
```powershell
.\.venv\Scripts\python.exe -m app.main
```

### 5. Custom Campaign Target
Specify a custom view target (default: 10,000):
```powershell
.\.venv\Scripts\python.exe -m app.main "https://x.com/monad_xyz/status/1777687376136982767" --target 1000000
```

---

## Running the Web API (FastAPI)

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000
```

Interactive API documentation (Swagger UI):
- **Swagger Docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Running Unit Tests

Run the complete test suite (60 tests covering YouTube, X, and Instagram):
```powershell
.\.venv\Scripts\pytest.exe -v
```

---

## API Response Format

`POST /verify` returns a unified schema across all platforms:

```json
{
  "platform": "x",
  "video_id": "1777687376136982767",
  "views": 2098598,
  "target_views": 10000,
  "eligible": true,
  "status": "target_reached",
  "source": "x_syndication_api",
  "reason": null,
  "timestamp": "2026-10-10T09:39:40.123456+00:00",
  "note": "Prototype result, not a final payout approval."
}
```
