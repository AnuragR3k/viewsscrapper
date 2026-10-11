## ✨ Key Features

- **Multi-Platform Verification:** Retrieve publicly available view metrics from YouTube Shorts, YouTube videos, X posts, and Instagram Reels/posts.
- **Campaign Threshold Validation:** Compare retrieved views against configurable campaign targets to determine eligibility.
- **Unified REST API:** Return consistent JSON responses across supported platforms using FastAPI.
- **Multiple Extraction Strategies:** Parse platform metadata and use fallback strategies when available.
- **Error Handling:** Handle unavailable content, missing metrics, upstream failures, timeouts, and rate limits.
- **Configurable Authentication:** Support optional Instagram session credentials and Meta Graph API access tokens through environment variables.
- **Interactive API Documentation:** Explore and test endpoints using Swagger UI.
- **Automated Testing:** Test URL validation, view-count extraction, campaign eligibility, and failure scenarios using pytest.

## 🏗️ Architecture

```text
Client / Frontend
       |
       v
   FastAPI Server
       |
       v
  URL Validation
       |
       v
 Platform Detection
       |
       +-------- YouTube
       |
       +-------- X (Twitter)
       |
       +-------- Instagram
       |
       v
 Metric Extraction
       |
       v
 Campaign Threshold Check
       |
       v
 Unified JSON Response
```

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Core application logic |
| FastAPI | REST API development |
| Requests | HTTP requests to platform endpoints |
| BeautifulSoup | HTML metadata parsing |
| Pydantic | Request validation and response schemas |
| Pytest | Automated testing |
| Uvicorn | ASGI server |

## 🔒 Security & Reliability Notes

- Keep API credentials and session cookies in environment variables.
- Never commit your `.env` file or expose authentication cookies.
- Apply reasonable request limits and timeouts when deploying publicly.
- Treat retrieved metrics as verification signals, not definitive proof of engagement or payout eligibility.
- Respect platform terms, access restrictions, and applicable rate limits.

## 🚧 Current Limitations

- Platform responses and page structures can change without notice.
- Some view counts are unavailable for private, restricted, or inaccessible content.
- Instagram verification may require valid authentication.
- Public metrics may be delayed, hidden, or unavailable.
- A successful verification response does not independently establish eligibility for a final payment.

## 🗺️ Roadmap

- [ ] Add GitHub Actions CI for automated testing.
- [ ] Add structured application logging.
- [ ] Add API rate limiting and request validation hardening.
- [ ] Add response caching to reduce repeated upstream requests.
- [ ] Add integration with campaign management and payout workflows.
- [ ] Expand platform-specific regression tests.

## 🤝 Contributing

Contributions, bug reports, and feature suggestions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make your changes and add tests.
4. Run the test suite with `pytest -v`.
5. Open a pull request describing your changes.

---

**Disclaimer:** This project is an independent prototype for social media metric verification. It is not affiliated with or endorsed by YouTube, X, Instagram, or Meta. Metric availability depends on the relevant platform's access policies and technical limitations.
