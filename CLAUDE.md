# CLAUDE.md — Smug2Immich

## Project Overview

Smug2Immich is a Python CLI tool that migrates photo and video libraries from SmugMug to Immich. It preserves album/folder structure, supports resumable uploads, parallel processing, and in-memory streaming.

## Architecture

**Single-file application:** `Smug2Immich.py` (~841 lines)

There are no subdirectories, packages, or modules — all logic lives in one script.

### Key Sections in Smug2Immich.py

| Lines | Responsibility |
|-------|---------------|
| 22–59 | Configuration management (load/save JSON config) |
| 61–73 | Resume state tracking (completed asset IDs) |
| 130–153 | HTTP session management with retry adapters |
| 156–215 | SmugMug OAuth 1.0a PIN-based flow |
| 229–280 | Thread-safe statistics and progress tracking |
| 282–322 | SmugMug API access (JSON + legacy HTML fallback) |
| 325–356 | Immich upload (multipart streaming) |
| 364–413 | Immich album creation and mapping |
| 439–539 | Download & upload pipeline (main worker) |
| 624–688 | Album loading with pagination and caching |
| 747–774 | Main processing loop (ThreadPoolExecutor) |
| 789–841 | Summary report |

### Concurrency Model

- `ThreadPoolExecutor` with configurable workers (default 20, album loading uses 10)
- Four `threading.Lock` instances protect shared state: `stats_lock`, `completed_ids_lock`, `failed_files_lock`, `immich_album_lock`
- Connection pooling via `requests.Session` (pool size 20)

### External APIs

- **SmugMug API** (`https://api.smugmug.com` / `https://www.smugmug.com/api/v2/`): OAuth 1.0a or session cookie auth, paginated album/image listing
- **Immich API**: Upload assets (`POST /api/assets`), manage albums (`GET|POST /api/albums`, `PUT /api/albums/{id}/assets`)

### Persistent Files (not committed)

- `.smug2immich.json` — Saved config (Immich URL, API key, OAuth tokens)
- `.smug2immich_state.json` — Resume state (completed asset IDs)
- `.smug2immich_albums.json` — Cached album image data

## Development Setup

### Requirements

- Python 3.10+
- Dependencies: `pip install -r requirements.txt`

### Running

```bash
python Smug2Immich.py -u USERNAME --api-key KEY --api-secret SECRET \
  --immich-server http://localhost:8080 --immich-api-key APIKEY
```

### Docker

```bash
docker compose run smug2immich -u USERNAME [OPTIONS]
```

Docker uses `host` network mode and mounts `./data` for persistent config/state.

## Dependencies

Listed in `requirements.txt`:

- `requests` — HTTP with connection pooling
- `requests_oauthlib` — OAuth 1.0a for SmugMug
- `beautifulsoup4` — HTML parsing (legacy cookie auth fallback)
- `tqdm` — Progress bars
- `colored` — Terminal color output

## Code Conventions

- **Style:** PEP 8-adjacent, snake_case functions, module-level UPPER_CASE constants
- **Output:** `print()` with `flush=True` for real-time console output; `tqdm` for progress bars
- **Error handling:** Automatic retries with exponential backoff (up to 5 retries on 429/5xx); failures collected in `failed_files` list and reported at end
- **Graceful shutdown:** SIGINT/SIGTERM handlers save state before exit
- **State saves:** Every 50 uploads to avoid data loss
- **No logging framework** — uses direct print statements

## Testing

There are no automated tests, linting configs, or CI/CD pipelines in this repository.

## Common Tasks

### Adding a new CLI argument

Add to the `argparse.ArgumentParser` block near the bottom of the file (around line 700+), then reference `args.<name>` in the main flow.

### Modifying upload behavior

The core download-and-upload logic is in `download_and_upload_image()` (line ~439). This function resolves the best download URL, streams the file, uploads to Immich, and adds it to the correct album.

### Changing retry/timeout behavior

Retry adapters are configured in `_mount_adapters()` (line ~130). Default timeouts are set as module-level constants and overridable via CLI flags `--timeout` and `--upload-timeout`.
