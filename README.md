# Smug2Immich

Migrate your entire SmugMug photo library to [Immich](https://immich.app), preserving album structure.

## Features

- Downloads all photos and videos from SmugMug via their API
- Uploads directly to Immich via API, organized into albums matching your SmugMug folder structure
- **Resumable** — interrupt anytime with Ctrl+C and re-run to continue where you left off
- **Parallel processing** — album loading (10 threads) and download/upload (20 threads) run concurrently
- **In-memory streaming** — by default, files are streamed from SmugMug to Immich without writing to disk
- **Connection pooling** with automatic retries and exponential backoff
- **Docker support** — run it on the same server as Immich for maximum speed
- Persistent config — Immich URL and API key are saved after first use
- Handles SmugMug pagination, password-protected accounts, and Immich deduplication (409s)

## Quick Start

### Python

```bash
pip install -r requirements.txt

python Smug2Immich.py \
  -u YOUR_SMUGMUG_USERNAME \
  -s YOUR_SMSESS_COOKIE \
  --immich-server http://your-immich-server:8080 \
  --immich-api-key YOUR_IMMICH_API_KEY
```

### Docker

```bash
docker compose build

docker compose run smug2immich \
  -u YOUR_SMUGMUG_USERNAME \
  -s YOUR_SMSESS_COOKIE \
  --immich-server http://localhost:8080 \
  --immich-api-key YOUR_IMMICH_API_KEY
```

Run in the background with `-d`:

```bash
docker compose run -d smug2immich \
  -u YOUR_SMUGMUG_USERNAME \
  -s YOUR_SMSESS_COOKIE \
  --immich-server http://localhost:8080 \
  --immich-api-key YOUR_IMMICH_API_KEY
```

Check progress:

```bash
docker logs -f <container_name>
```

## Getting Your SmugMug Session Cookie

1. Log in to SmugMug in your web browser
2. Open DevTools (F12) → **Application** → **Cookies** → `https://www.smugmug.com`
3. Copy the value of the `SMSESS` cookie

This is only required if your SmugMug account is password protected.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-u`, `--user` | *(required)* | SmugMug username (from `USERNAME.smugmug.com`) |
| `-s`, `--session` | | SmugMug `SMSESS` cookie for password-protected accounts |
| `--immich-server` | *(prompted)* | Immich server URL (saved after first use) |
| `--immich-api-key` | *(prompted)* | Immich API key (saved after first use) |
| `-o`, `--output` | `output/` | Temporary output directory (only used with `--keep-files`) |
| `--albums` | all | Specific albums to download, separated by `$` |
| `--workers` | `20` | Number of parallel download/upload threads |
| `--timeout` | `120` | Timeout in seconds for metadata and download requests |
| `--upload-timeout` | `600` | Timeout in seconds for Immich uploads (large videos) |
| `--keep-files` | off | Keep downloaded files on disk after uploading |
| `--verbose-errors` | off | Print detailed error messages for failures |
| `--reset` | | Clear saved progress and re-upload everything |
| `--reset-config` | | Clear saved Immich config and re-prompt |

## How It Works

1. Connects to Immich and verifies the API key
2. Loads any saved resume state (previously completed uploads)
3. Fetches the album list from SmugMug (parallelized, 10 at a time)
4. For each image, in parallel:
   - Resolves the best download URL (original video > original image > largest available)
   - Downloads into memory (or disk with `--keep-files`)
   - Uploads to Immich via API
   - Creates/finds the matching Immich album and adds the photo to it
   - Records the image as completed for resume
5. Progress is saved to disk every 50 uploads and on exit

## Resume

Progress is tracked in `.smug2immich_state.json` (or `/app/data/` in Docker). If the process is interrupted, re-run the same command — already uploaded images are skipped automatically.

Use `--reset` to start fresh and re-upload everything.

## Tips

- **Run on the same server as Immich** (via Docker) to avoid transferring files over the network twice
- **Use a dedicated Immich user** for the import to keep SmugMug photos separate from your existing library. Share albums to your main account as needed.
- Photos without EXIF dates will use SmugMug's `DateTimeOriginal` or `DateTimeUploaded` as the timestamp

## Requirements

- Python 3.10+
- Dependencies: `requests`, `beautifulsoup4`, `tqdm`, `colored`

## License

MIT
