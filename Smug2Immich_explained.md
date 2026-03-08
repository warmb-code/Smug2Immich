# Smug2Immich.py — Line-by-Line Explanation

## Imports (Lines 1–19)

**Line 1:** `import os` — Imports the `os` module for file/path operations (checking if files exist, making directories, joining paths, removing files).

**Line 2:** `import sys` — Imports `sys` for `sys.exit()` to terminate the script with an error message/code, and `sys.stdout.reconfigure()` for output buffering control.

**Line 3:** `import io` — Imports `io` for `io.BytesIO`, an in-memory binary buffer used to hold downloaded image data without writing to disk.

**Line 6:** `sys.stdout.reconfigure(line_buffering=True)` — Forces stdout to flush after every newline, even when the process is not connected to a terminal (e.g. running in Docker background or piped). Without this, all output would be buffered and invisible until the process ends.

**Line 7:** `import requests` — Imports the `requests` HTTP library, used for all network calls (SmugMug API, image downloads, Immich uploads).

**Line 8:** `from requests.adapters import HTTPAdapter` — Imports `HTTPAdapter`, which lets us configure connection pooling and retry behavior on a `requests.Session`.

**Line 9:** `from urllib3.util.retry import Retry` — Imports `Retry`, a urllib3 class that defines automatic retry policies (how many retries, which HTTP status codes to retry on, backoff timing).

**Line 10:** `import json` — Imports `json` for parsing JSON strings from SmugMug API responses and reading/writing the config and state files.

**Line 11:** `import re` — Imports `re` (regular expressions) for sanitizing filenames by replacing unsafe characters.

**Line 12:** `import argparse` — Imports `argparse` for parsing command-line arguments (`--user`, `--workers`, etc.).

**Line 13:** `import time` — Imports `time` for formatting timestamps (used when uploading to Immich to set file creation dates).

**Line 14:** `import signal` — Imports `signal` to register handlers for SIGINT (Ctrl+C) and SIGTERM, enabling graceful shutdown.

**Line 15:** `from concurrent.futures import ThreadPoolExecutor, as_completed` — Imports the thread pool for parallel processing. `ThreadPoolExecutor` manages worker threads; `as_completed` yields futures as they finish. Used for both parallel album loading and parallel download/upload.

**Line 16:** `from threading import Lock` — Imports `Lock` for thread-safe access to shared mutable state (stats counters, completed IDs, failed files list, Immich album cache).

**Line 17:** `from bs4 import BeautifulSoup` — Imports BeautifulSoup (HTML parser). SmugMug's API returns JSON embedded inside HTML `<pre>` tags, so we need to parse the HTML to extract it.

**Line 18:** `from tqdm import tqdm` — Imports `tqdm`, a library that renders a progress bar in the terminal.

**Line 19:** `from colored import attr` — Imports `attr` from the `colored` library, used to apply bold formatting to the progress bar label text.

## Constants & Paths (Lines 21–26)

**Line 21:** `DATA_DIR = os.environ.get("SMUG2IMMICH_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))` — Determines where config and state files are stored. Checks the `SMUG2IMMICH_DATA_DIR` environment variable first (set by Docker to `/app/data`), falls back to the directory containing the script itself.

**Line 22:** `CONFIG_FILE = os.path.join(DATA_DIR, ".smug2immich.json")` — Path for the persistent config file (stores Immich server URL and API key).

**Line 23:** `STATE_FILE = os.path.join(DATA_DIR, ".smug2immich_state.json")` — Path for the resume state file (tracks which images have been uploaded).

**Line 25:** `ENDPOINT = "https://www.smugmug.com"` — Base URL for all SmugMug API calls. API paths get appended to this.

**Line 26:** `MAX_RETRIES = 5` — Maximum number of automatic retries for failed HTTP requests (used by the `Retry` configuration).

## Persistent Config Functions (Lines 31–57)

**Line 31:** `def load_config():` — Defines a function to load the saved config file.

**Line 32:** `if os.path.exists(CONFIG_FILE):` — Checks if the config file exists on disk.

**Line 33:** `with open(CONFIG_FILE, 'r') as f:` — Opens the config file for reading.

**Line 34:** `return json.load(f)` — Parses and returns the JSON contents as a Python dict.

**Line 35:** `return {}` — If the file doesn't exist, returns an empty dict (no saved config yet).

**Line 38:** `def save_config(cfg):` — Defines a function to write the config dict to disk.

**Line 39:** `with open(CONFIG_FILE, 'w') as f:` — Opens (or creates) the config file for writing.

**Line 40:** `json.dump(cfg, f, indent=2)` — Writes the dict as pretty-printed JSON.

**Line 43:** `def get_config_value(cfg, key, prompt_text, cli_value=None, secret=False):` — Function that resolves a config value from three sources in priority order: CLI argument, saved config, or interactive prompt.

**Line 45:** `if cli_value:` — If the user passed the value on the command line, use it.

**Line 46:** `cfg[key] = cli_value` — Save it into the config dict.

**Line 47:** `save_config(cfg)` — Persist it to disk so next run doesn't need the CLI arg.

**Line 48:** `return cli_value` — Return the value.

**Line 49:** `if key in cfg and cfg[key]:` — If no CLI arg but it's in the saved config, use that.

**Line 50:** `return cfg[key]` — Return the saved value.

**Line 51:** `while True:` — If neither CLI nor saved config, loop until user provides a non-empty value.

**Line 52:** `value = input(prompt_text).strip()` — Prompt the user interactively and strip whitespace.

**Line 53:** `if value:` — If they typed something non-empty...

**Line 54:** `cfg[key] = value` — Save it to the config dict.

**Line 55:** `save_config(cfg)` — Persist to disk.

**Line 56:** `return value` — Return it.

**Line 57:** `print("  Value cannot be empty, please try again.")` — If empty, tell them and loop again.

## Resume State Functions (Lines 62–71)

**Line 62:** `def load_state():` — Function to load the resume state file (tracks completed image IDs).

**Line 63:** `if os.path.exists(STATE_FILE):` — Check if state file exists.

**Line 64:** `with open(STATE_FILE, 'r') as f:` — Open it for reading.

**Line 65:** `return json.load(f)` — Parse and return the JSON.

**Line 66:** `return {}` — If no state file, return empty dict (fresh start).

**Line 69:** `def save_state(state):` — Function to write state to disk.

**Line 70:** `with open(STATE_FILE, 'w') as f:` — Open/create state file for writing.

**Line 71:** `json.dump(state, f)` — Write the state dict as JSON.

## Argument Parsing (Lines 76–122)

**Line 76:** `parser = argparse.ArgumentParser(description="SmugMug Downloader with Immich Upload")` — Creates the argument parser with a description shown in `--help`.

**Lines 77–79:** Defines `-s`/`--session` argument — the SmugMug session cookie for password-protected accounts.

**Lines 80–81:** Defines `-u`/`--user` argument (required) — the SmugMug username from the URL.

**Lines 82–83:** Defines `-o`/`--output` argument — temp directory for downloaded files, defaults to `output/`.

**Lines 84–86:** Defines `--albums` — optional filter to only process specific albums, separated by `$`.

**Lines 87–88:** Defines `--workers` — number of parallel threads, defaults to 20.

**Lines 89–90:** Defines `--timeout` — HTTP timeout in seconds for API calls and downloads, defaults to 120.

**Lines 91–92:** Defines `--upload-timeout` — separate, longer timeout for Immich uploads (large videos), defaults to 600 seconds (10 minutes).

**Lines 93–94:** Defines `--immich-server` — Immich URL, defaults to `None` (will be loaded from config or prompted).

**Lines 95–96:** Defines `--immich-api-key` — Immich API key, same behavior as above.

**Lines 97–98:** Defines `--keep-files` — boolean flag; if set, downloaded files are kept on disk instead of being streamed in-memory only.

**Lines 99–100:** Defines `--verbose-errors` — boolean flag; if set, prints detailed error messages for each failure.

**Lines 101–102:** Defines `--reset` — boolean flag; if set, clears the resume state file so all images are re-processed.

**Lines 103–104:** Defines `--reset-config` — boolean flag; if set, deletes the saved config file so Immich URL/key are re-prompted.

**Line 106:** `args = parser.parse_args()` — Parses the command-line arguments into the `args` namespace object.

**Lines 109–112:** If `--reset-config` was passed and the config file exists, delete it and confirm.

**Lines 114–117:** If `--reset` was passed and the state file exists, delete it and confirm.

**Line 120:** `cfg = load_config()` — Load whatever config is saved (or empty dict if first run / just reset).

**Line 121:** `immich_server = get_config_value(...)` — Resolve the Immich server URL from CLI, saved config, or interactive prompt.

**Line 122:** `immich_api_key = get_config_value(...)` — Same for the API key.

## HTTP Session Setup (Lines 126–152)

**Line 126:** `def _make_session(cookies=None, extra_headers=None):` — Factory function to create a `requests.Session` with connection pooling and retry logic.

**Line 127:** `s = requests.Session()` — Creates a new session. Sessions reuse TCP connections across requests.

**Lines 128–132:** Creates a `Retry` object: retry up to `MAX_RETRIES` (5) times, with exponential backoff starting at 1 second (`backoff_factor=1`), automatically retry on HTTP 429/500/502/503/504, for both GET and POST methods.

**Line 134:** `adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)` — Creates an HTTP adapter with the retry policy and a pool of 20 connections (so up to 20 concurrent requests can reuse connections without creating new TCP handshakes).

**Line 135:** `s.mount("https://", adapter)` — Attach this adapter to all HTTPS URLs.

**Line 136:** `s.mount("http://", adapter)` — Same for HTTP URLs.

**Lines 137–138:** If cookies were passed, add them to the session so they're sent with every request.

**Lines 139–140:** If extra headers were passed, add them as default headers for every request.

**Line 141:** `return s` — Return the configured session.

**Line 144:** `cookies = {"SMSESS": args.session} if args.session else {}` — Build the SmugMug cookie dict. If no session ID was given, empty dict (public access).

**Line 145:** `smugmug_session = _make_session(cookies=cookies)` — Create the SmugMug session with the cookie.

**Lines 146–149:** Create the Immich session with the API key and Accept header pre-configured.

**Line 152:** `output_dir = os.path.join(args.output, "")` — Normalizes the output directory path to always end with a path separator.

## Album Filtering & Global State (Lines 154–171)

**Line 154:** `specific_albums = []` — Initialize empty list for album name filters.

**Line 155:** `if args.albums:` — If user specified `--albums`...

**Line 156:** `specific_albums = [x.strip() for x in args.albums.split('$') if x.strip()]` — Split on `$`, strip whitespace from each name, filter out empty strings.

**Line 159:** `stats_lock = Lock()` — A threading lock to protect stats counters from race conditions when multiple threads update them simultaneously.

**Line 160:** `album_stats = {}` — Dict that will map album names to per-album stat counters.

**Line 161:** `global_stats = {'downloaded': 0, 'uploaded': 0, 'skipped': 0, 'failed_download': 0, 'failed_upload': 0, 'total': 0}` — Global counters across all albums.

**Line 163:** `failed_files = []` — List to collect details about every file that failed (for the summary at the end).

**Line 164:** `failed_files_lock = Lock()` — Lock protecting the `failed_files` list from concurrent thread access.

**Line 167:** `completed_ids = set()` — Set of `device_asset_id` strings for images that were successfully uploaded in this run. Used for resume.

**Line 168:** `completed_ids_lock = Lock()` — Lock protecting the `completed_ids` set.

**Line 171:** `shutdown_requested = False` — Global flag that gets set to `True` when user hits Ctrl+C.

## Signal Handling (Lines 174–185)

**Line 174:** `def handle_signal(signum, frame):` — Signal handler function. `signum` is the signal number, `frame` is the current stack frame (unused).

**Line 175:** `global shutdown_requested` — Declares that we're modifying the module-level variable, not creating a local one.

**Line 176:** `if shutdown_requested:` — If this is the *second* Ctrl+C (flag already set)...

**Line 177:** `print("\nForce quit.")` — Tell the user.

**Line 178:** `sys.exit(1)` — Hard exit immediately.

**Line 179:** `shutdown_requested = True` — First Ctrl+C: set the flag so worker threads check it and stop picking up new work.

**Lines 180–181:** Print instructions that the shutdown is graceful and progress is saved.

**Line 184:** `signal.signal(signal.SIGINT, handle_signal)` — Register the handler for SIGINT (Ctrl+C).

**Line 185:** `signal.signal(signal.SIGTERM, handle_signal)` — Register for SIGTERM (e.g. `kill` command or Docker stop).

## Helper Functions (Lines 188–208)

**Line 188:** `def update_stats(album_name, key, value=1):` — Thread-safe function to increment a stat counter.

**Line 189:** `with stats_lock:` — Acquire the lock so no other thread modifies stats at the same time.

**Line 190:** `global_stats[key] += value` — Increment the global counter.

**Lines 191–192:** If the album exists in `album_stats`, increment its counter too. The `if` guard prevents a KeyError if called with an unknown album name.

**Line 195:** `def mark_completed(device_asset_id):` — Records that an image was successfully uploaded.

**Line 196:** `with completed_ids_lock:` — Thread-safe access.

**Line 197:** `completed_ids.add(device_asset_id)` — Add the ID to the in-memory set.

**Line 200:** `def save_progress():` — Flushes the in-memory completed IDs to the state file on disk.

**Lines 202–203:** Acquires the lock and copies the set to a list (so we release the lock quickly).

**Line 204:** `state = load_state()` — Load the existing state file (may have IDs from a previous run).

**Line 205:** `existing = set(state.get("completed", []))` — Get the previously saved IDs as a set.

**Line 206:** `existing.update(ids)` — Merge in the new IDs from this run.

**Line 207:** `state["completed"] = list(existing)` — Convert back to list for JSON serialization.

**Line 208:** `save_state(state)` — Write to disk.

## SmugMug API Function (Lines 211–226)

**Line 211:** `def get_json(url):` — Fetches a SmugMug API URL and extracts JSON from the HTML response.

**Line 213:** `try:` — Wrap in try/except for network and parse errors.

**Line 214:** `r = smugmug_session.get(ENDPOINT + url, timeout=args.timeout)` — Makes a GET request to `https://www.smugmug.com` + the API path. Uses the shared session (connection pooling + retries). Times out after `--timeout` seconds.

**Line 215:** `r.raise_for_status()` — Raises an exception if the HTTP status code is 4xx or 5xx.

**Line 216:** `soup = BeautifulSoup(r.text, "html.parser")` — Parses the HTML response body.

**Line 217:** `pres = soup.find_all("pre")` — Finds all `<pre>` tags in the HTML. SmugMug wraps JSON data in these tags.

**Lines 218–221:** If no `<pre>` tags found, optionally log an error and return `None`.

**Line 222:** `return json.loads(pres[-1].text)` — Takes the text content of the last `<pre>` tag and parses it as JSON. The last one is used because earlier `<pre>` tags may contain other content.

**Lines 223–226:** Catches JSON parse errors and request errors, optionally logs them, returns `None`.

## Immich Upload Function (Lines 229–260)

**Line 229:** `def upload_to_immich(file_data, filename, device_asset_id, created_at=None):` — Uploads file data (a file-like object) to the Immich API. Returns a 3-tuple: `(success, message, asset_id)`.

**Line 231:** `now = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())` — Formats the current UTC time as an ISO 8601 string.

**Line 232:** `timestamp = created_at or now` — Uses the image's original creation date if available, otherwise falls back to current time.

**Line 234:** `files = {'assetData': (filename, file_data, 'application/octet-stream')}` — Constructs the multipart file upload. `requests` will send this as a `multipart/form-data` request with the file attached under the field name `assetData`.

**Lines 235–241:** Builds the metadata fields Immich requires: a unique device asset ID (for deduplication), a device identifier, creation/modification timestamps, and `isFavorite` set to false.

**Lines 244–248:** POSTs to `{immich_server}/api/assets` with the file and metadata. Uses the Immich session (has API key header) and the upload-specific timeout.

**Lines 250–252:** HTTP 200 or 201 means successful upload; extracts the `asset_id` from the response JSON and returns success with it.

**Lines 253–257:** HTTP 409 means the asset already exists in Immich (duplicate); treats as success and attempts to extract the existing asset ID from the response body.

**Line 258:** Any other status code is a failure; returns the code, first 200 chars of the response body, and `None` for asset_id.

**Lines 259–260:** Catches any exception (network error, timeout, etc.) and returns it as a failure message with `None` for asset_id.

## Failure Recording (Lines 263–265)

**Line 263:** `def _record_failure(album_name, filename, error_msg):` — Thread-safe helper to log a failed file.

**Line 264:** `with failed_files_lock:` — Acquire lock.

**Line 265:** `failed_files.append(...)` — Append a dict with album name, filename, and error message to the failures list.

## Immich Album Management (Lines 268–331)

**Line 270:** `immich_album_cache = {}` — In-memory cache mapping Immich album names to their IDs. Avoids repeated API lookups for albums we've already found/created.

**Line 271:** `immich_album_lock = Lock()` — Lock protecting the cache from concurrent thread access.

**Line 274:** `def get_or_create_immich_album(album_name, url_path):` — Gets or creates an Immich album matching the SmugMug folder structure. Uses the full URL path as the album name to preserve hierarchy.

**Line 279:** `immich_album_name = url_path.strip("/").replace("/", " / ")` — Converts the SmugMug URL path (e.g. `/Family/Vacation 2023/`) into a readable album name (`Family / Vacation 2023`).

**Lines 280–281:** Falls back to the raw album name if the URL path is empty.

**Lines 283–285:** Check the cache first — if we've already looked up or created this album, return its ID immediately.

**Lines 288–300:** Search Immich's existing albums via `GET /api/albums`. If an album with the matching name already exists, cache its ID and return it.

**Lines 303–315:** If no existing album was found, create a new one via `POST /api/albums` with the album name and a description noting it was imported from SmugMug. Cache and return the new album ID.

**Line 317:** `return None` — If both search and creation failed (e.g. network error), return None. The photo will still be uploaded, just not added to an album.

**Line 320:** `def add_asset_to_immich_album(album_id, asset_id):` — Adds an uploaded asset to an Immich album.

**Lines 322–323:** Early return if either ID is missing.

**Lines 325–328:** PUTs to `{immich_server}/api/albums/{album_id}/assets` with the asset ID. This is idempotent — adding an already-added asset is a no-op.

**Lines 330–331:** Silently catch any errors — album assignment is best-effort; the photo is already uploaded.

## Asset ID Builder (Lines 334–340)

**Line 334:** `def make_device_asset_id(image, album_name):` — Builds a stable, unique identifier for an image. Used for Immich deduplication, resume tracking, and determining which images to skip.

**Line 336:** `raw_filename = image.get("FileName", "unknown")` — Get the original filename from the SmugMug image metadata, defaulting to "unknown".

**Line 337:** `image_key = image.get("ImageKey") or image.get("Key") or ""` — Get SmugMug's unique key for this image. Tries two possible field names.

**Lines 338–339:** If we have an image key, use `smug:{key}:{filename}` — globally unique.

**Line 340:** Otherwise fall back to `smug:{album_name}:{filename}` — less unique but best we can do.

## Main Worker Function (Lines 343–443)

**Line 343:** `def download_and_upload_image(image, album_path, album_name, url_path):` — The main worker function. Each thread pool worker runs this for one image. Downloads from SmugMug and uploads to Immich, then assigns the photo to its Immich album.

**Lines 345–346:** If a shutdown was requested (Ctrl+C), bail out immediately without doing any work.

**Line 348:** `raw_filename = image.get("FileName", "unknown")` — Get the original filename.

**Line 349:** `filename = re.sub(r'[^\w\-_\. ]', '_', raw_filename)` — Sanitize the filename for the local filesystem by replacing any character that isn't alphanumeric, hyphen, underscore, dot, or space with an underscore.

**Line 351:** `image_key = image.get("ImageKey") or image.get("Key") or ""` — Get the SmugMug image key.

**Lines 352–354:** If we have an image key, append it to the filename (e.g. `IMG_0001_abc123.jpg`) to prevent collisions when two images in the same album have the same original filename.

**Line 356:** `device_asset_id = make_device_asset_id(image, album_name)` — Build the stable ID for this image.

**Line 359:** `created_at = None` — Initialize the timestamp variable.

**Line 360:** `dt_orig = image.get("DateTimeOriginal") or image.get("DateTimeUploaded")` — Try to get the original capture date from SmugMug metadata. Falls back to upload date.

**Lines 361–365:** If we got a date string, try to normalize it to ISO 8601 format. If it already has a "T" (like `2020-01-01T12:00:00`), use it as-is. Otherwise replace the space with "T" and append `.000Z`. The try/except silently ignores any formatting issues.

**Line 368:** `uris = image.get("Uris", {})` — Get the `Uris` dict from the image metadata, or empty dict if missing. This contains links to different versions of the image.

**Lines 369–373:** Determine which media type to download, in priority order: `LargestVideo` (for videos), `ImageDownload` (original-quality image download), `LargestImage` (fallback to the largest available image).

**Line 375:** `download_url = None` — Initialize.

**Line 376:** `if largest_media in uris:` — If the chosen media type has a URI...

**Line 377:** `image_req = get_json(uris[largest_media]["Uri"])` — Fetch the metadata for that URI to get the actual download URL. This is an extra API call because SmugMug doesn't include the direct download URL inline.

**Lines 378–382:** If that API call failed, record it as a download failure and return.

**Line 383:** `download_url = image_req["Response"][largest_media]["Url"]` — Extract the actual download URL from the API response.

**Lines 384–385:** If no URI was available for the chosen media type, fall back to the `ArchivedUri` field (a direct link to the archived original).

**Lines 387–390:** If we still have no download URL at all, record failure and return.

**Lines 392–393:** Check shutdown flag again before starting the actual download (which could be slow for large files).

**Lines 396–398:** Start the download. `stream=True` means the response body isn't downloaded all at once — instead we read it in chunks later. `raise_for_status()` throws an exception on HTTP errors.

**Lines 399–403:** If the download request itself fails (connection error, timeout, HTTP error), record failure and return.

**Line 405:** `if args.keep_files:` — If the user wants to keep files on disk...

**Line 406:** `os.makedirs(album_path, exist_ok=True)` — Create the album directory (and parents) if it doesn't exist.

**Line 407:** `image_path = os.path.join(album_path, filename)` — Full path for the file on disk.

**Lines 408–412:** Write the downloaded data to disk in 1MB chunks. The `if chunk` guard skips empty chunks (keep-alive signals).

**Lines 413–417:** If writing to disk fails (disk full, permissions, etc.), record failure and return.

**Line 419:** `update_stats(album_name, 'downloaded')` — Increment the download counter.

**Lines 421–422:** Re-open the file we just wrote and upload it to Immich. The file object is passed directly as the upload data. Returns a 3-tuple including the Immich asset ID.

**Line 423:** `else:` — If not keeping files (the default)...

**Line 424:** `buf = io.BytesIO()` — Create an in-memory binary buffer.

**Lines 425–427:** Stream the downloaded data into the buffer in 1MB chunks.

**Line 428:** `buf.seek(0)` — Rewind the buffer to the beginning so `upload_to_immich` reads from the start.

**Line 429:** `update_stats(album_name, 'downloaded')` — Increment download counter.

**Line 430:** `success, message, asset_id = upload_to_immich(...)` — Upload the in-memory buffer to Immich.

**Lines 432–434:** If upload succeeded, increment the upload counter and mark this image as completed (for resume).

**Lines 435–438:** If we got an asset ID back from Immich, find or create the matching Immich album (using the SmugMug folder path) and add this asset to it. This preserves the SmugMug folder structure as Immich albums.

**Line 439:** Return success.

**Lines 441–443:** If upload failed, increment the failure counter, record the failure details, and return.

## Main Execution — Immich Connection Test (Lines 449–460)

**Line 449:** `print("Testing Immich connection...", end="", flush=True)` — Print without a newline, flushed immediately so it appears right away.

**Line 451:** `response = immich_session.get(f"{immich_server}/api/server/version", timeout=10)` — Hit the Immich version endpoint as a connectivity test.

**Lines 452–454:** If HTTP 200, parse the version info and print it.

**Lines 455–457:** Otherwise print the error and exit.

**Lines 458–460:** If the request itself threw an exception (DNS failure, connection refused, etc.), print and exit.

## Main Execution — Resume State Loading (Lines 463–467)

**Line 463:** `state = load_state()` — Load the resume state file.

**Line 464:** `previously_completed = set(state.get("completed", []))` — Get the set of image IDs that were already uploaded in previous runs.

**Lines 465–467:** If there are previously completed images, tell the user how many are being skipped and hint about `--reset`.

## Main Execution — Album List Retrieval (Lines 469–487)

**Line 469:** `print("Downloading album list...", end="", flush=True)` — Status message, flushed immediately.

**Line 470:** `albums = get_json(f"/api/v2/folder/user/{args.user}!albumlist")` — Fetch the list of all albums for the given SmugMug user.

**Lines 471–473:** If the API call failed, print error and exit.

**Line 474:** `print("done.")` — Finish the status line.

**Lines 476–479:** Try to access `albums["Response"]["AlbumList"]`. If the key doesn't exist, exit with a message that the user wasn't found or is password protected.

**Lines 481–484:** Filter the album list: if `--albums` was specified, keep only albums whose names match. Otherwise keep all.

**Lines 486–487:** If no albums match the filter, exit.

## Main Execution — Parallel Album Image Loading (Lines 489–536)

**Line 490:** `all_work = []` — Master list of all (image, album_path, album_name, url_path) tuples to process.

**Line 491:** `skipped_count = 0` — Counter for images skipped due to resume.

**Line 494:** `def load_album_images(album):` — Function that loads all images for a single album, including pagination. Designed to run in a thread pool.

**Lines 496–497:** If shutdown was requested, bail out immediately.

**Line 499:** `images = get_json(album["Uri"] + "!images")` — Fetch the first page of images for this album.

**Line 500–501:** If the API call failed or shutdown was requested, return None.

**Lines 503–504:** If the response has no `AlbumImage` key, the album is empty; return empty list.

**Line 506:** `album_images = images["Response"]["AlbumImage"]` — Get the list of image objects from the first page.

**Line 509:** `while "NextPage" in next_images["Response"]["Pages"] and not shutdown_requested:` — Paginate while there are more pages and shutdown hasn't been requested.

**Lines 510–513:** Fetch next page and extend the image list.

**Line 515:** `return album, album_images` — Return the album and all its images.

**Line 518:** Print how many albums will be loaded with 10 parallel workers.

**Lines 520–521:** Create a thread pool with 10 workers and submit all album loading tasks.

**Lines 523–527:** As album loads complete, check for shutdown. If shutdown was requested, cancel all pending futures and break.

**Lines 528–531:** For each completed album, store the results and print the status.

**Lines 533–536:** If shutdown occurred during album loading, save progress and exit cleanly.

## Main Execution — Resume Filtering & Work Building (Lines 538–568)

**Lines 539–543:** Process album results in original order. For each album, set up paths and initialize per-album stats.

**Lines 545–547:** Get the loaded images for this album. Skip if no images.

**Lines 550–556:** Filter out already-completed images by checking each image's device_asset_id against the previously completed set.

**Lines 558–565:** Calculate totals, pending counts, and skip counts. Update per-album and global stats.

**Lines 567–568:** Add each pending image to the master work list as a 4-tuple including the URL path (needed for Immich album creation).

## Main Execution — Early Exit Check (Lines 570–576)

**Lines 570–576:** If there's no work to do, print an appropriate message (either "all done" or "no images found") and exit cleanly.

## Main Execution — Thread Pool Processing (Lines 578–621)

**Lines 578–583:** Print summary of what's about to happen: image count, skip count, streaming mode, album organization, and resume instructions.

**Line 585:** `bar_format = '{l_bar}{bar:-2}| {n_fmt:>5}/{total_fmt:<5} [{elapsed}<{remaining}]'` — Custom format string for the tqdm progress bar. Shows the label, a bar, count/total, elapsed time, and estimated remaining time.

**Line 588:** `SAVE_INTERVAL = 50` — Save progress to disk every 50 completed images (not every single one, to reduce disk writes).

**Line 589:** `completions_since_save = 0` — Counter tracking how many images have completed since last save.

**Line 591:** `with ThreadPoolExecutor(max_workers=args.workers) as executor:` — Create a thread pool with the configured number of workers. The `with` block ensures threads are cleaned up when done.

**Lines 592–595:** Submit all work items to the thread pool. `executor.submit` schedules each `download_and_upload_image` call to run on a worker thread with all 4 arguments including `url_path`. The result is a dict mapping each `Future` object to `(image, album_name)` for later reference.

**Lines 597–599:** Create the tqdm progress bar with bold label, covering all work items.

**Line 600:** `for future in as_completed(future_to_info):` — Iterate over futures as they complete (whichever finishes first comes first).

**Line 601:** `result = future.result()` — Get the return value from the worker function.

**Line 602:** `pbar.update(1)` — Advance the progress bar by one.

**Line 603:** `completions_since_save += 1` — Track completions since last save.

**Lines 605–607:** If verbose errors are enabled and this image failed, print the failure details using `tqdm.write` (which cooperates with the progress bar so output doesn't get garbled).

**Lines 610–612:** If we've hit the save interval, flush completed IDs to disk and reset the counter.

**Lines 614–618:** If shutdown was requested (Ctrl+C), cancel all pending futures and break out of the loop.

**Line 621:** `save_progress()` — Always save progress when exiting the main loop (catches the last batch of completions, and ensures we save on shutdown).

## Main Execution — Cleanup (Lines 624–631)

**Line 624:** `if not args.keep_files:` — If we're not keeping files...

**Lines 625–631:** Loop over all album directories and remove them if they're empty. `os.rmdir` only removes empty directories. `OSError` is caught silently (directory might not exist or might not be empty).

## Summary Output (Lines 634–685)

**Line 634:** `print("\n" + "=" * 60)` — Print a separator line (60 equals signs).

**Lines 635–638:** Print "INTERRUPTED" if shutdown was requested, or "COMPLETE" if it finished normally.

**Line 639:** Another separator line.

**Lines 640–646:** Print the global stats: total pending, skipped (resumed), downloaded, uploaded, failed downloads, failed uploads.

**Line 648:** `if len(albums_to_process) > 1:` — Only show per-album breakdown if there were multiple albums.

**Line 649:** Print header.

**Line 650:** `for aname, s in album_stats.items():` — Loop over each album's stats.

**Lines 651–652:** Skip albums with zero total and zero skipped (nothing happened).

**Line 653:** Sum up failed downloads + failed uploads.

**Lines 654–660:** Build a list of human-readable parts like "50 uploaded", "10 skipped", "2 failed".

**Line 661:** Print the album name and its stats.

**Line 663:** `if failed_files:` — If any files failed...

**Lines 664–666:** Print a "FAILED FILES" header with count.

**Lines 668–670:** Group failures by album name into a dict.

**Lines 672–677:** For each album with failures, print up to 5 failures with details, and a "... and N more" if there are more than 5.

**Line 679:** `if shutdown_requested:` — If we were interrupted...

**Lines 680–681:** Count total completed (from previous runs + this run).

**Lines 682–683:** Print the total and remind user to re-run to resume.

**Lines 684–685:** If not interrupted and not keeping files, print confirmation that no local files were written.
