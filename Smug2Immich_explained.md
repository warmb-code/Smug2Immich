# Smug2Immich.py — Line-by-Line Explanation

## Imports (Lines 1–16)

**Line 1:** `import os` — Imports the `os` module for file/path operations (checking if files exist, making directories, joining paths, removing files).

**Line 2:** `import sys` — Imports `sys` for `sys.exit()` to terminate the script with an error message/code.

**Line 3:** `import io` — Imports `io` for `io.BytesIO`, an in-memory binary buffer used to hold downloaded image data without writing to disk.

**Line 4:** `import requests` — Imports the `requests` HTTP library, used for all network calls (SmugMug API, image downloads, Immich uploads).

**Line 5:** `from requests.adapters import HTTPAdapter` — Imports `HTTPAdapter`, which lets us configure connection pooling and retry behavior on a `requests.Session`.

**Line 6:** `from urllib3.util.retry import Retry` — Imports `Retry`, a urllib3 class that defines automatic retry policies (how many retries, which HTTP status codes to retry on, backoff timing).

**Line 7:** `import json` — Imports `json` for parsing JSON strings from SmugMug API responses and reading/writing the config and state files.

**Line 8:** `import re` — Imports `re` (regular expressions) for sanitizing filenames by replacing unsafe characters.

**Line 9:** `import argparse` — Imports `argparse` for parsing command-line arguments (`--user`, `--workers`, etc.).

**Line 10:** `import time` — Imports `time` for formatting timestamps (used when uploading to Immich to set file creation dates).

**Line 11:** `import signal` — Imports `signal` to register handlers for SIGINT (Ctrl+C) and SIGTERM, enabling graceful shutdown.

**Line 12:** `from concurrent.futures import ThreadPoolExecutor, as_completed` — Imports the thread pool for parallel image processing. `ThreadPoolExecutor` manages worker threads; `as_completed` yields futures as they finish.

**Line 13:** `from threading import Lock` — Imports `Lock` for thread-safe access to shared mutable state (stats counters, completed IDs list, failed files list).

**Line 14:** `from bs4 import BeautifulSoup` — Imports BeautifulSoup (HTML parser). SmugMug's API returns JSON embedded inside HTML `<pre>` tags, so we need to parse the HTML to extract it.

**Line 15:** `from tqdm import tqdm` — Imports `tqdm`, a library that renders a progress bar in the terminal.

**Line 16:** `from colored import attr` — Imports `attr` from the `colored` library, used to apply bold formatting to the progress bar label text.

## Constants (Lines 18–22)

**Line 18:** `CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".smug2immich.json")` — Sets the path for the persistent config file. `__file__` is this script's path; `os.path.abspath` makes it absolute; `os.path.dirname` gets the directory; then we join `.smug2immich.json` to put the config file next to the script.

**Line 19:** `STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".smug2immich_state.json")` — Same pattern for the resume state file, which tracks which images have already been uploaded.

**Line 21:** `ENDPOINT = "https://www.smugmug.com"` — Base URL for all SmugMug API calls. API paths get appended to this.

**Line 22:** `MAX_RETRIES = 5` — Maximum number of automatic retries for failed HTTP requests (used by the `Retry` configuration).

## Persistent Config Functions (Lines 27–53)

**Line 27:** `def load_config():` — Defines a function to load the saved config file.

**Line 28:** `if os.path.exists(CONFIG_FILE):` — Checks if the config file exists on disk.

**Line 29:** `with open(CONFIG_FILE, 'r') as f:` — Opens the config file for reading.

**Line 30:** `return json.load(f)` — Parses and returns the JSON contents as a Python dict.

**Line 31:** `return {}` — If the file doesn't exist, returns an empty dict (no saved config yet).

**Line 34:** `def save_config(cfg):` — Defines a function to write the config dict to disk.

**Line 35:** `with open(CONFIG_FILE, 'w') as f:` — Opens (or creates) the config file for writing.

**Line 36:** `json.dump(cfg, f, indent=2)` — Writes the dict as pretty-printed JSON.

**Line 39:** `def get_config_value(cfg, key, prompt_text, cli_value=None, secret=False):` — Function that resolves a config value from three sources in priority order: CLI argument, saved config, or interactive prompt.

**Line 41:** `if cli_value:` — If the user passed the value on the command line, use it.

**Line 42:** `cfg[key] = cli_value` — Save it into the config dict.

**Line 43:** `save_config(cfg)` — Persist it to disk so next run doesn't need the CLI arg.

**Line 44:** `return cli_value` — Return the value.

**Line 45:** `if key in cfg and cfg[key]:` — If no CLI arg but it's in the saved config, use that.

**Line 46:** `return cfg[key]` — Return the saved value.

**Line 47:** `while True:` — If neither CLI nor saved config, loop until user provides a non-empty value.

**Line 48:** `value = input(prompt_text).strip()` — Prompt the user interactively and strip whitespace.

**Line 49:** `if value:` — If they typed something non-empty...

**Line 50:** `cfg[key] = value` — Save it to the config dict.

**Line 51:** `save_config(cfg)` — Persist to disk.

**Line 52:** `return value` — Return it.

**Line 53:** `print("  Value cannot be empty, please try again.")` — If empty, tell them and loop again.

## Resume State Functions (Lines 58–67)

**Line 58:** `def load_state():` — Function to load the resume state file (tracks completed image IDs).

**Line 59:** `if os.path.exists(STATE_FILE):` — Check if state file exists.

**Line 60:** `with open(STATE_FILE, 'r') as f:` — Open it for reading.

**Line 61:** `return json.load(f)` — Parse and return the JSON.

**Line 62:** `return {}` — If no state file, return empty dict (fresh start).

**Line 65:** `def save_state(state):` — Function to write state to disk.

**Line 66:** `with open(STATE_FILE, 'w') as f:` — Open/create state file for writing.

**Line 67:** `json.dump(state, f)` — Write the state dict as JSON.

## Argument Parsing (Lines 72–118)

**Line 72:** `parser = argparse.ArgumentParser(description="SmugMug Downloader with Immich Upload")` — Creates the argument parser with a description shown in `--help`.

**Lines 73–75:** Defines `-s`/`--session` argument — the SmugMug session cookie for password-protected accounts.

**Lines 76–77:** Defines `-u`/`--user` argument (required) — the SmugMug username from the URL.

**Lines 78–79:** Defines `-o`/`--output` argument — temp directory for downloaded files, defaults to `output/`.

**Lines 80–82:** Defines `--albums` — optional filter to only process specific albums, separated by `$`.

**Lines 83–84:** Defines `--workers` — number of parallel threads, defaults to 20.

**Lines 85–86:** Defines `--timeout` — HTTP timeout in seconds for API calls and downloads, defaults to 60.

**Lines 87–88:** Defines `--upload-timeout` — separate, longer timeout for Immich uploads (large videos), defaults to 600 seconds (10 minutes).

**Lines 89–90:** Defines `--immich-server` — Immich URL, defaults to `None` (will be loaded from config or prompted).

**Lines 91–92:** Defines `--immich-api-key` — Immich API key, same behavior as above.

**Lines 93–94:** Defines `--keep-files` — boolean flag; if set, downloaded files are kept on disk instead of being streamed in-memory only.

**Lines 95–96:** Defines `--verbose-errors` — boolean flag; if set, prints detailed error messages for each failure.

**Lines 97–98:** Defines `--reset` — boolean flag; if set, clears the resume state file so all images are re-processed.

**Lines 99–100:** Defines `--reset-config` — boolean flag; if set, deletes the saved config file so Immich URL/key are re-prompted.

**Line 102:** `args = parser.parse_args()` — Parses the command-line arguments into the `args` namespace object.

**Line 105:** `if args.reset_config:` — If user passed `--reset-config`...

**Line 106:** `if os.path.exists(CONFIG_FILE):` — ...and the config file exists...

**Line 107:** `os.remove(CONFIG_FILE)` — ...delete it.

**Line 108:** `print("Config cleared.")` — Confirm to user.

**Line 110:** `if args.reset:` — If user passed `--reset`...

**Line 111:** `if os.path.exists(STATE_FILE):` — ...and state file exists...

**Line 112:** `os.remove(STATE_FILE)` — ...delete it.

**Line 113:** `print("Progress state cleared.")` — Confirm.

**Line 116:** `cfg = load_config()` — Load whatever config is saved (or empty dict if first run / just reset).

**Line 117:** `immich_server = get_config_value(cfg, "immich_server", "Immich server URL (e.g. https://immich.example.com): ", args.immich_server)` — Resolve the Immich server URL from CLI, saved config, or interactive prompt.

**Line 118:** `immich_api_key = get_config_value(cfg, "immich_api_key", "Immich API key: ", args.immich_api_key)` — Same for the API key.

## HTTP Session Setup (Lines 122–148)

**Line 122:** `def _make_session(cookies=None, extra_headers=None):` — Factory function to create a `requests.Session` with connection pooling and retry logic.

**Line 123:** `s = requests.Session()` — Creates a new session. Sessions reuse TCP connections across requests.

**Lines 124–128:** Creates a `Retry` object: retry up to `MAX_RETRIES` (5) times, with exponential backoff starting at 1 second (`backoff_factor=1`), automatically retry on HTTP 429/500/502/503/504, for both GET and POST methods.

**Line 130:** `adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)` — Creates an HTTP adapter with the retry policy and a pool of 20 connections (so up to 20 concurrent requests can reuse connections without creating new TCP handshakes).

**Line 131:** `s.mount("https://", adapter)` — Attach this adapter to all HTTPS URLs.

**Line 132:** `s.mount("http://", adapter)` — Same for HTTP URLs.

**Lines 133–134:** If cookies were passed, add them to the session so they're sent with every request.

**Lines 135–136:** If extra headers were passed, add them as default headers for every request.

**Line 137:** `return s` — Return the configured session.

**Line 140:** `cookies = {"SMSESS": args.session} if args.session else {}` — Build the SmugMug cookie dict. If no session ID was given, empty dict (public access).

**Line 141:** `smugmug_session = _make_session(cookies=cookies)` — Create the SmugMug session with the cookie.

**Lines 142–145:** Create the Immich session with the API key and Accept header pre-configured.

**Line 148:** `output_dir = os.path.join(args.output, "")` — Normalizes the output directory path to always end with a path separator. `os.path.join("output", "")` gives `"output/"`.

## Album Filtering & Global State (Lines 150–167)

**Line 150:** `specific_albums = []` — Initialize empty list for album name filters.

**Line 151:** `if args.albums:` — If user specified `--albums`...

**Line 152:** `specific_albums = [x.strip() for x in args.albums.split('$') if x.strip()]` — Split on `$`, strip whitespace from each name, filter out empty strings.

**Line 155:** `stats_lock = Lock()` — A threading lock to protect stats counters from race conditions when multiple threads update them simultaneously.

**Line 156:** `album_stats = {}` — Dict that will map album names to per-album stat counters.

**Line 157:** `global_stats = {'downloaded': 0, 'uploaded': 0, 'skipped': 0, 'failed_download': 0, 'failed_upload': 0, 'total': 0}` — Global counters across all albums.

**Line 159:** `failed_files = []` — List to collect details about every file that failed (for the summary at the end).

**Line 160:** `failed_files_lock = Lock()` — Lock protecting the `failed_files` list from concurrent thread access.

**Line 163:** `completed_ids = set()` — Set of `device_asset_id` strings for images that were successfully uploaded in this run. Used for resume.

**Line 164:** `completed_ids_lock = Lock()` — Lock protecting the `completed_ids` set.

**Line 167:** `shutdown_requested = False` — Global flag that gets set to `True` when user hits Ctrl+C.

## Signal Handling (Lines 170–181)

**Line 170:** `def handle_signal(signum, frame):` — Signal handler function. `signum` is the signal number, `frame` is the current stack frame (unused).

**Line 171:** `global shutdown_requested` — Declares that we're modifying the module-level variable, not creating a local one.

**Line 172:** `if shutdown_requested:` — If this is the *second* Ctrl+C (flag already set)...

**Line 173:** `print("\nForce quit.")` — Tell the user.

**Line 174:** `sys.exit(1)` — Hard exit immediately.

**Line 175:** `shutdown_requested = True` — First Ctrl+C: set the flag so worker threads check it and stop picking up new work.

**Lines 176–177:** Print instructions that the shutdown is graceful and progress is saved.

**Line 180:** `signal.signal(signal.SIGINT, handle_signal)` — Register the handler for SIGINT (Ctrl+C).

**Line 181:** `signal.signal(signal.SIGTERM, handle_signal)` — Register for SIGTERM (e.g. `kill` command).

## Helper Functions (Lines 184–204)

**Line 184:** `def update_stats(album_name, key, value=1):` — Thread-safe function to increment a stat counter.

**Line 185:** `with stats_lock:` — Acquire the lock so no other thread modifies stats at the same time.

**Line 186:** `global_stats[key] += value` — Increment the global counter.

**Lines 187–188:** If the album exists in `album_stats`, increment its counter too. The `if` guard prevents a KeyError if called with an unknown album name.

**Line 191:** `def mark_completed(device_asset_id):` — Records that an image was successfully uploaded.

**Line 192:** `with completed_ids_lock:` — Thread-safe access.

**Line 193:** `completed_ids.add(device_asset_id)` — Add the ID to the in-memory set.

**Line 196:** `def save_progress():` — Flushes the in-memory completed IDs to the state file on disk.

**Lines 198–199:** Acquires the lock and copies the set to a list (so we release the lock quickly).

**Line 200:** `state = load_state()` — Load the existing state file (may have IDs from a previous run).

**Line 201:** `existing = set(state.get("completed", []))` — Get the previously saved IDs as a set.

**Line 202:** `existing.update(ids)` — Merge in the new IDs from this run.

**Line 203:** `state["completed"] = list(existing)` — Convert back to list for JSON serialization.

**Line 204:** `save_state(state)` — Write to disk.

## SmugMug API Function (Lines 207–222)

**Line 207:** `def get_json(url):` — Fetches a SmugMug API URL and extracts JSON from the HTML response.

**Line 209:** `try:` — Wrap in try/except for network and parse errors.

**Line 210:** `r = smugmug_session.get(ENDPOINT + url, timeout=args.timeout)` — Makes a GET request to `https://www.smugmug.com` + the API path. Uses the shared session (connection pooling + retries). Times out after `--timeout` seconds.

**Line 211:** `r.raise_for_status()` — Raises an exception if the HTTP status code is 4xx or 5xx.

**Line 212:** `soup = BeautifulSoup(r.text, "html.parser")` — Parses the HTML response body.

**Line 213:** `pres = soup.find_all("pre")` — Finds all `<pre>` tags in the HTML. SmugMug wraps JSON data in these tags.

**Lines 214–217:** If no `<pre>` tags found, optionally log an error and return `None`.

**Line 218:** `return json.loads(pres[-1].text)` — Takes the text content of the last `<pre>` tag and parses it as JSON. The last one is used because earlier `<pre>` tags may contain other content.

**Lines 219–222:** Catches JSON parse errors and request errors, optionally logs them, returns `None`.

## Immich Upload Function (Lines 225–252)

**Line 225:** `def upload_to_immich(file_data, filename, device_asset_id, created_at=None):` — Uploads file data (a file-like object) to the Immich API.

**Line 227:** `now = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())` — Formats the current UTC time as an ISO 8601 string.

**Line 228:** `timestamp = created_at or now` — Uses the image's original creation date if available, otherwise falls back to current time.

**Line 230:** `files = {'assetData': (filename, file_data, 'application/octet-stream')}` — Constructs the multipart file upload. `requests` will send this as a `multipart/form-data` request with the file attached under the field name `assetData`.

**Lines 231–237:** Builds the metadata fields Immich requires: a unique device asset ID (for deduplication), a device identifier, creation/modification timestamps, and `isFavorite` set to false.

**Lines 240–244:** POSTs to `{immich_server}/api/assets` with the file and metadata. Uses the Immich session (has API key header) and the upload-specific timeout.

**Lines 246–247:** HTTP 200 or 201 means successful upload; return success.

**Lines 248–249:** HTTP 409 means the asset already exists in Immich (duplicate); treat as success since the goal is just to get it there.

**Line 250:** Any other status code is a failure; return the code and first 200 chars of the response body for debugging.

**Lines 251–252:** Catches any exception (network error, timeout, etc.) and returns it as a failure message.

## Failure Recording & Asset ID Builder (Lines 255–266)

**Line 255:** `def _record_failure(album_name, filename, error_msg):` — Thread-safe helper to log a failed file.

**Line 256:** `with failed_files_lock:` — Acquire lock.

**Line 257:** `failed_files.append(...)` — Append a dict with album name, filename, and error message to the failures list.

**Line 260:** `def make_device_asset_id(image, album_name):` — Builds a stable, unique identifier for an image. Used both for Immich deduplication and for the resume feature (to know which images are already done).

**Line 262:** `raw_filename = image.get("FileName", "unknown")` — Get the original filename from the SmugMug image metadata, defaulting to "unknown".

**Line 263:** `image_key = image.get("ImageKey") or image.get("Key") or ""` — Get SmugMug's unique key for this image. Tries two possible field names.

**Lines 264–265:** If we have an image key, use `smug:{key}:{filename}` — globally unique.

**Line 266:** Otherwise fall back to `smug:{album_name}:{filename}` — less unique but best we can do.

## Main Worker Function (Lines 269–365)

**Line 269:** `def download_and_upload_image(image, album_path, album_name):` — The main worker function. Each thread pool worker runs this for one image. Downloads from SmugMug and uploads to Immich.

**Lines 271–272:** If a shutdown was requested (Ctrl+C), bail out immediately without doing any work.

**Line 274:** `raw_filename = image.get("FileName", "unknown")` — Get the original filename.

**Line 275:** `filename = re.sub(r'[^\w\-_\. ]', '_', raw_filename)` — Sanitize the filename for the local filesystem by replacing any character that isn't alphanumeric, hyphen, underscore, dot, or space with an underscore.

**Line 277:** `image_key = image.get("ImageKey") or image.get("Key") or ""` — Get the SmugMug image key again.

**Lines 278–280:** If we have an image key, append it to the filename (e.g. `IMG_0001_abc123.jpg`) to prevent collisions when two images in the same album have the same original filename.

**Line 282:** `device_asset_id = make_device_asset_id(image, album_name)` — Build the stable ID for this image.

**Line 285:** `created_at = None` — Initialize the timestamp variable.

**Line 286:** `dt_orig = image.get("DateTimeOriginal") or image.get("DateTimeUploaded")` — Try to get the original capture date from SmugMug metadata. Falls back to upload date.

**Lines 287–291:** If we got a date string, try to normalize it to ISO 8601 format. If it already has a "T" (like `2020-01-01T12:00:00`), use it as-is. Otherwise replace the space with "T" and append `.000Z`. The try/except silently ignores any formatting issues.

**Line 294:** `uris = image.get("Uris", {})` — Get the `Uris` dict from the image metadata, or empty dict if missing. This contains links to different versions of the image.

**Lines 295–299:** Determine which media type to download, in priority order: `LargestVideo` (for videos), `ImageDownload` (original-quality image download), `LargestImage` (fallback to the largest available image).

**Line 301:** `download_url = None` — Initialize.

**Line 302:** `if largest_media in uris:` — If the chosen media type has a URI...

**Line 303:** `image_req = get_json(uris[largest_media]["Uri"])` — Fetch the metadata for that URI to get the actual download URL. This is an extra API call because SmugMug doesn't include the direct download URL inline.

**Lines 304–308:** If that API call failed, record it as a download failure and return.

**Line 309:** `download_url = image_req["Response"][largest_media]["Url"]` — Extract the actual download URL from the API response.

**Lines 310–311:** If no URI was available for the chosen media type, fall back to the `ArchivedUri` field (a direct link to the archived original).

**Lines 313–316:** If we still have no download URL at all, record failure and return.

**Lines 318–319:** Check shutdown flag again before starting the actual download (which could be slow for large files).

**Lines 322–324:** Start the download. `stream=True` means the response body isn't downloaded all at once — instead we read it in chunks later. `raise_for_status()` throws an exception on HTTP errors.

**Lines 325–329:** If the download request itself fails (connection error, timeout, HTTP error), record failure and return.

**Line 331:** `if args.keep_files:` — If the user wants to keep files on disk...

**Line 332:** `os.makedirs(album_path, exist_ok=True)` — Create the album directory (and parents) if it doesn't exist.

**Line 333:** `image_path = os.path.join(album_path, filename)` — Full path for the file on disk.

**Lines 334–338:** Write the downloaded data to disk in 1MB chunks. The `if chunk` guard skips empty chunks (keep-alive signals).

**Lines 339–343:** If writing to disk fails (disk full, permissions, etc.), record failure and return.

**Line 345:** `update_stats(album_name, 'downloaded')` — Increment the download counter.

**Lines 347–348:** Re-open the file we just wrote and upload it to Immich. The file object is passed directly as the upload data.

**Line 349:** `else:` — If not keeping files (the default)...

**Line 350:** `buf = io.BytesIO()` — Create an in-memory binary buffer.

**Lines 351–353:** Stream the downloaded data into the buffer in 1MB chunks.

**Line 354:** `buf.seek(0)` — Rewind the buffer to the beginning so `upload_to_immich` reads from the start.

**Line 355:** `update_stats(album_name, 'downloaded')` — Increment download counter.

**Line 356:** `success, message = upload_to_immich(buf, filename, device_asset_id, created_at)` — Upload the in-memory buffer to Immich.

**Lines 358–361:** If upload succeeded, increment the upload counter, mark this image as completed (for resume), and return success.

**Lines 363–365:** If upload failed, increment the failure counter, record the failure details, and return.

## Main Execution — Immich Connection Test (Lines 371–382)

**Line 371:** `print("Testing Immich connection...", end="")` — Print without a newline (the result will be appended on the same line).

**Line 373:** `response = immich_session.get(f"{immich_server}/api/server/version", timeout=10)` — Hit the Immich version endpoint as a connectivity test.

**Lines 374–376:** If HTTP 200, parse the version info and print it.

**Lines 377–379:** Otherwise print the error and exit.

**Lines 380–382:** If the request itself threw an exception (DNS failure, connection refused, etc.), print and exit.

## Main Execution — Resume State Loading (Lines 385–389)

**Line 385:** `state = load_state()` — Load the resume state file.

**Line 386:** `previously_completed = set(state.get("completed", []))` — Get the set of image IDs that were already uploaded in previous runs.

**Lines 387–389:** If there are previously completed images, tell the user how many are being skipped and hint about `--reset`.

## Main Execution — Album List Retrieval (Lines 391–409)

**Line 391:** `print("Downloading album list...", end="")` — Status message.

**Line 392:** `albums = get_json(f"/api/v2/folder/user/{args.user}!albumlist")` — Fetch the list of all albums for the given SmugMug user.

**Lines 393–395:** If the API call failed, print error and exit.

**Line 396:** `print("done.")` — Finish the status line.

**Lines 398–401:** Try to access `albums["Response"]["AlbumList"]`. If the key doesn't exist, exit with a message that the user wasn't found or is password protected.

**Lines 403–406:** Filter the album list: if `--albums` was specified, keep only albums whose names match. Otherwise keep all.

**Lines 408–409:** If no albums match the filter, exit.

## Main Execution — Image Gathering & Resume Filtering (Lines 412–471)

**Line 412:** `all_work = []` — Master list of all (image, album_path, album_name) tuples to process.

**Line 413:** `skipped_count = 0` — Counter for images skipped due to resume.

**Line 415:** `for album in albums_to_process:` — Loop over each album to load its images.

**Line 416:** `album_path = os.path.join(output_dir, album["UrlPath"].lstrip("/"))` — Build the local directory path for this album. `lstrip("/")` removes the leading slash from the URL path so it doesn't become an absolute path.

**Line 417:** `album_name = album["Name"]` — Get the album's display name.

**Line 418:** `album_stats[album_name] = {...}` — Initialize per-album stat counters to zero.

**Line 420:** Print which album is being loaded.

**Line 421:** `images = get_json(album["Uri"] + "!images")` — Fetch the first page of images for this album. `!images` is a SmugMug API expansion that returns the images in the album.

**Lines 422–424:** If the API call failed, print error and skip to the next album.

**Lines 426–428:** If the response has no `AlbumImage` key, the album is empty; print that and skip.

**Line 430:** `album_images = images["Response"]["AlbumImage"]` — Get the list of image objects from the first page.

**Line 432:** `next_images = images` — Start pagination from the current response.

**Line 433:** `while "NextPage" in next_images["Response"]["Pages"]:` — SmugMug paginates results. Keep going while there's a next page.

**Line 434:** `next_images = get_json(next_images["Response"]["Pages"]["NextPage"])` — Fetch the next page.

**Lines 435–436:** If it failed, stop paginating (we'll process what we have).

**Line 437:** `album_images.extend(next_images["Response"]["AlbumImage"])` — Add the next page's images to our list.

**Line 440:** `pending = []` — Images that still need to be processed (not already completed).

**Line 441:** `for img in album_images:` — Loop over every image in this album.

**Line 442:** `aid = make_device_asset_id(img, album_name)` — Build its unique ID.

**Lines 443–444:** If this ID is in the previously completed set, increment the skip counter.

**Lines 445–446:** Otherwise, add it to the pending list.

**Line 448:** `total_in_album = len(album_images)` — Total images found in the album.

**Line 449:** `pending_in_album = len(pending)` — How many still need uploading.

**Line 450:** `skipped_in_album = total_in_album - pending_in_album` — How many were already done.

**Lines 452–455:** Update per-album and global stats with the totals and skip counts.

**Lines 457–460:** Print the image count, including skip info if any images were skipped.

**Lines 462–463:** Add each pending image to the master work list as a tuple.

**Lines 465–471:** If there's no work to do, print an appropriate message (either "all done" or "no images found") and exit cleanly.

## Main Execution — Thread Pool Processing (Lines 473–515)

**Line 473:** Print how many images will be processed with how many workers.

**Lines 474–475:** If some were skipped, mention it.

**Line 476:** Print whether files will be kept or streamed in-memory.

**Line 477:** Remind user about Ctrl+C and resume.

**Line 479:** `bar_format = '{l_bar}{bar:-2}| {n_fmt:>5}/{total_fmt:<5} [{elapsed}<{remaining}]'` — Custom format string for the tqdm progress bar. Shows the label, a bar, count/total, elapsed time, and estimated remaining time.

**Line 482:** `SAVE_INTERVAL = 50` — Save progress to disk every 50 completed images (not every single one, to reduce disk writes).

**Line 483:** `completions_since_save = 0` — Counter tracking how many images have completed since last save.

**Line 485:** `with ThreadPoolExecutor(max_workers=args.workers) as executor:` — Create a thread pool with the configured number of workers. The `with` block ensures threads are cleaned up when done.

**Lines 486–489:** Submit all work items to the thread pool. `executor.submit` schedules each `download_and_upload_image` call to run on a worker thread. The result is a dict mapping each `Future` object to `(image, album_name)` for later reference.

**Lines 491–493:** Create the tqdm progress bar with bold label, covering all work items.

**Line 494:** `for future in as_completed(future_to_info):` — Iterate over futures as they complete (not in submission order, but in completion order — whichever finishes first comes first).

**Line 495:** `result = future.result()` — Get the return value from the worker function. If it threw an exception, it would re-raise here.

**Line 496:** `pbar.update(1)` — Advance the progress bar by one.

**Line 497:** `completions_since_save += 1` — Track completions since last save.

**Lines 499–501:** If verbose errors are enabled and this image failed, print the failure details using `tqdm.write` (which cooperates with the progress bar so output doesn't get garbled).

**Lines 504–506:** If we've hit the save interval, flush completed IDs to disk and reset the counter.

**Lines 508–512:** If shutdown was requested (Ctrl+C), cancel all pending futures (ones that haven't started yet) and break out of the loop.

**Line 515:** `save_progress()` — Always save progress when exiting the main loop (catches the last batch of completions, and ensures we save on shutdown).

## Main Execution — Cleanup (Lines 518–525)

**Line 518:** `if not args.keep_files:` — If we're not keeping files...

**Lines 519–525:** Loop over all album directories and remove them if they're empty. `os.rmdir` only removes empty directories. `OSError` is caught silently (directory might not exist or might not be empty).

## Summary Output (Lines 528–579)

**Line 528:** `print("\n" + "=" * 60)` — Print a separator line (60 equals signs).

**Lines 529–532:** Print "INTERRUPTED" if shutdown was requested, or "COMPLETE" if it finished normally.

**Line 533:** Another separator line.

**Lines 534–540:** Print the global stats: total pending, skipped (resumed), downloaded, uploaded, failed downloads, failed uploads.

**Line 542:** `if len(albums_to_process) > 1:` — Only show per-album breakdown if there were multiple albums (not useful for a single album).

**Line 543:** Print header.

**Line 544:** `for aname, s in album_stats.items():` — Loop over each album's stats.

**Lines 545–546:** Skip albums with zero total and zero skipped (nothing happened).

**Line 547:** Sum up failed downloads + failed uploads.

**Lines 548–554:** Build a list of human-readable parts like "50 uploaded", "10 skipped", "2 failed".

**Line 555:** Print the album name and its stats.

**Line 557:** `if failed_files:` — If any files failed...

**Lines 558–560:** Print a "FAILED FILES" header with count.

**Lines 562–564:** Group failures by album name into a dict.

**Lines 566–571:** For each album with failures, print up to 5 failures with details, and a "... and N more" if there are more than 5.

**Line 573:** `if shutdown_requested:` — If we were interrupted...

**Lines 574–575:** Count total completed (from previous runs + this run).

**Lines 576–577:** Print the total and remind user to re-run to resume.

**Lines 578–579:** If not interrupted and not keeping files, print confirmation that no local files were written.
