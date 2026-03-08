import os
import sys
import io

# Force unbuffered stdout so progress is visible in real time (even when piped/backgrounded)
sys.stdout.reconfigure(line_buffering=True)
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import re
import argparse
import time
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from bs4 import BeautifulSoup
from tqdm import tqdm
from colored import attr

DATA_DIR = os.environ.get("SMUG2IMMICH_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(DATA_DIR, ".smug2immich.json")
STATE_FILE = os.path.join(DATA_DIR, ".smug2immich_state.json")

ENDPOINT = "https://www.smugmug.com"
MAX_RETRIES = 5


# --- Persistent config (Immich URL, API key) ---

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)


def get_config_value(cfg, key, prompt_text, cli_value=None, secret=False):
    """Return CLI value if given, else saved config, else prompt the user. Saves to config."""
    if cli_value:
        cfg[key] = cli_value
        save_config(cfg)
        return cli_value
    if key in cfg and cfg[key]:
        return cfg[key]
    while True:
        value = input(prompt_text).strip()
        if value:
            cfg[key] = value
            save_config(cfg)
            return value
        print("  Value cannot be empty, please try again.")


# --- Resume state ---

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)


# --- Arg parsing ---

parser = argparse.ArgumentParser(description="SmugMug Downloader with Immich Upload")
parser.add_argument(
    "-s", "--session",
    help="session ID (required if user is password protected); log in on a web browser and paste the SMSESS cookie")
parser.add_argument(
    "-u", "--user", help="username (from URL, USERNAME.smugmug.com)", required=True)
parser.add_argument("-o", "--output", default="output/",
                    help="temporary output directory (files deleted after upload)")
parser.add_argument(
    "--albums",
    help="specific album names to download, split by $. Wrap in single quotes. (e.g. --albums 'Title 1$Title 2$Title 3')")
parser.add_argument(
    "--workers", type=int, default=20, help="number of parallel download threads (default: 20)")
parser.add_argument(
    "--timeout", type=int, default=120, help="request timeout in seconds for metadata/download (default: 120)")
parser.add_argument(
    "--upload-timeout", type=int, default=600, help="request timeout for Immich uploads (default: 600)")
parser.add_argument(
    "--immich-server", default=None, help="Immich server URL (saved after first use)")
parser.add_argument(
    "--immich-api-key", default=None, help="Immich API key (saved after first use)")
parser.add_argument(
    "--keep-files", action="store_true", help="keep local files after uploading to Immich")
parser.add_argument(
    "--verbose-errors", action="store_true", help="show detailed error messages for failures")
parser.add_argument(
    "--reset", action="store_true", help="clear saved progress and start fresh")
parser.add_argument(
    "--reset-config", action="store_true", help="clear saved Immich config and re-prompt")

args = parser.parse_args()

# Handle config reset
if args.reset_config:
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
        print("Config cleared.")

if args.reset:
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        print("Progress state cleared.")

# Load / prompt for Immich config
cfg = load_config()
immich_server = get_config_value(cfg, "immich_server", "Immich server URL (e.g. https://immich.example.com): ", args.immich_server)
immich_api_key = get_config_value(cfg, "immich_api_key", "Immich API key: ", args.immich_api_key)

# --- Shared sessions with connection pooling and automatic retries ---

def _make_session(cookies=None, extra_headers=None):
    s = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    if cookies:
        s.cookies.update(cookies)
    if extra_headers:
        s.headers.update(extra_headers)
    return s


cookies = {"SMSESS": args.session} if args.session else {}
smugmug_session = _make_session(cookies=cookies)
immich_session = _make_session(extra_headers={
    "x-api-key": immich_api_key,
    "Accept": "application/json",
})

# Normalize output dir
output_dir = os.path.join(args.output, "")

specific_albums = []
if args.albums:
    specific_albums = [x.strip() for x in args.albums.split('$') if x.strip()]

# Per-album statistics
stats_lock = Lock()
album_stats = {}
global_stats = {'downloaded': 0, 'uploaded': 0, 'skipped': 0, 'failed_download': 0, 'failed_upload': 0, 'total': 0}

failed_files = []
failed_files_lock = Lock()

# Track completed asset IDs for resume — written to state file periodically
completed_ids = set()
completed_ids_lock = Lock()

# Graceful shutdown
shutdown_requested = False


def handle_signal(signum, frame):
    global shutdown_requested
    if shutdown_requested:
        print("\nForce quit.")
        sys.exit(1)
    shutdown_requested = True
    print("\nShutting down gracefully... (press Ctrl+C again to force quit)")
    print("Progress is saved — re-run the same command to resume.")


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def update_stats(album_name, key, value=1):
    with stats_lock:
        global_stats[key] += value
        if album_name in album_stats:
            album_stats[album_name][key] += value


def mark_completed(device_asset_id):
    with completed_ids_lock:
        completed_ids.add(device_asset_id)


def save_progress():
    """Save completed asset IDs to state file."""
    with completed_ids_lock:
        ids = list(completed_ids)
    state = load_state()
    existing = set(state.get("completed", []))
    existing.update(ids)
    state["completed"] = list(existing)
    save_state(state)


def get_json(url, max_attempts=5):
    """Fetch SmugMug API endpoint, extract JSON from HTML <pre> tags.
    Respects rate limit headers and Retry-After on 429."""
    for attempt in range(max_attempts):
        try:
            r = smugmug_session.get(ENDPOINT + url, timeout=args.timeout)

            # Respect rate limiting
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 10))
                if args.verbose_errors:
                    print(f"\n  RATE LIMITED: waiting {retry_after}s before retry ({url})", flush=True)
                time.sleep(retry_after)
                continue

            # Proactively slow down when running low on quota
            remaining = r.headers.get("X-RateLimit-Remaining")
            if remaining is not None and int(remaining) < 10:
                time.sleep(1)

            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            pres = soup.find_all("pre")
            if not pres:
                if args.verbose_errors:
                    print(f"\n  ERROR: No JSON found in response from {url}")
                return None
            return json.loads(pres[-1].text)
        except (json.JSONDecodeError, requests.exceptions.RequestException) as e:
            if args.verbose_errors:
                print(f"\n  ERROR: {type(e).__name__} for {url}: {e}")
            if attempt + 1 < max_attempts:
                time.sleep(2 ** attempt)

    return None


def upload_to_immich(file_data, filename, device_asset_id, created_at=None):
    """Upload file data to Immich. Returns (success, message)."""
    now = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    timestamp = created_at or now

    files = {'assetData': (filename, file_data, 'application/octet-stream')}
    data = {
        'deviceAssetId': device_asset_id,
        'deviceId': 'SmugMug-Downloader',
        'fileCreatedAt': timestamp,
        'fileModifiedAt': timestamp,
        'isFavorite': 'false',
    }

    try:
        response = immich_session.post(
            f"{immich_server}/api/assets",
            files=files,
            data=data,
            timeout=args.upload_timeout,
        )
        if response.status_code in (200, 201):
            asset_id = response.json().get("id")
            return True, "Success", asset_id
        if response.status_code == 409:
            # Duplicate — try to get the existing asset ID
            body = response.json() if response.text else {}
            asset_id = body.get("id")
            return True, "Already exists", asset_id
        return False, f"HTTP {response.status_code}: {response.text[:200]}", None
    except Exception as ex:
        return False, str(ex), None


def _record_failure(album_name, filename, error_msg):
    with failed_files_lock:
        failed_files.append({'album': album_name, 'filename': filename, 'error': error_msg})


# --- Immich album management ---
# Maps SmugMug album name -> Immich album ID. Thread-safe via lock.
immich_album_cache = {}
immich_album_lock = Lock()


def get_or_create_immich_album(album_name, url_path):
    """Get or create an Immich album matching the SmugMug folder path.
    Uses url_path (e.g. 'Family/Vacation 2023') as the album name in Immich
    to preserve the folder hierarchy."""
    # Use the full path as album name so structure is preserved
    immich_album_name = url_path.strip("/").replace("/", " / ")
    if not immich_album_name:
        immich_album_name = album_name

    with immich_album_lock:
        if immich_album_name in immich_album_cache:
            return immich_album_cache[immich_album_name]

    # Search existing albums first
    try:
        resp = immich_session.get(
            f"{immich_server}/api/albums",
            timeout=args.timeout,
        )
        if resp.status_code == 200:
            for a in resp.json():
                if a.get("albumName") == immich_album_name:
                    with immich_album_lock:
                        immich_album_cache[immich_album_name] = a["id"]
                    return a["id"]
    except Exception:
        pass

    # Create the album
    try:
        resp = immich_session.post(
            f"{immich_server}/api/albums",
            json={"albumName": immich_album_name, "description": f"Imported from SmugMug: {album_name}"},
            timeout=args.timeout,
        )
        if resp.status_code in (200, 201):
            album_id = resp.json()["id"]
            with immich_album_lock:
                immich_album_cache[immich_album_name] = album_id
            return album_id
    except Exception:
        pass

    return None


def add_asset_to_immich_album(album_id, asset_id):
    """Add an uploaded asset to an Immich album."""
    if not album_id or not asset_id:
        return
    try:
        immich_session.put(
            f"{immich_server}/api/albums/{album_id}/assets",
            json={"ids": [asset_id]},
            timeout=args.timeout,
        )
    except Exception:
        pass


def make_device_asset_id(image, album_name):
    """Build a stable device_asset_id for an image (used for dedup and resume)."""
    raw_filename = image.get("FileName", "unknown")
    image_key = image.get("ImageKey") or image.get("Key") or ""
    if image_key:
        return f"smug:{image_key}:{raw_filename}"
    return f"smug:{album_name}:{raw_filename}"


def download_and_upload_image(image, album_path, album_name, url_path):
    """Download a single image from SmugMug and stream it to Immich."""
    if shutdown_requested:
        return {'status': 'skipped', 'filename': '?', 'error': 'shutdown'}

    raw_filename = image.get("FileName", "unknown")
    filename = re.sub(r'[^\w\-_\. ]', '_', raw_filename)

    image_key = image.get("ImageKey") or image.get("Key") or ""
    if image_key:
        name, ext = os.path.splitext(filename)
        filename = f"{name}_{image_key}{ext}"

    device_asset_id = make_device_asset_id(image, album_name)

    # Use SmugMug's DateTimeOriginal if available for accurate timestamps
    created_at = None
    dt_orig = image.get("DateTimeOriginal") or image.get("DateTimeUploaded")
    if dt_orig:
        try:
            created_at = dt_orig if "T" in dt_orig else dt_orig.replace(" ", "T") + ".000Z"
        except Exception:
            pass

    # Determine best download URL
    uris = image.get("Uris", {})
    largest_media = (
        "LargestVideo" if "LargestVideo" in uris else
        "ImageDownload" if "ImageDownload" in uris else
        "LargestImage"
    )

    download_url = None
    if largest_media in uris:
        image_req = get_json(uris[largest_media]["Uri"])
        if image_req is None:
            update_stats(album_name, 'failed_download')
            error_msg = f'Could not retrieve metadata URI: {uris[largest_media]["Uri"]}'
            _record_failure(album_name, filename, error_msg)
            return {'status': 'failed', 'filename': filename, 'error': error_msg}
        download_url = image_req["Response"][largest_media]["Url"]
    else:
        download_url = image.get("ArchivedUri")

    if not download_url:
        update_stats(album_name, 'failed_download')
        _record_failure(album_name, filename, 'No download URL available')
        return {'status': 'failed', 'filename': filename, 'error': 'No download URL available'}

    if shutdown_requested:
        return {'status': 'skipped', 'filename': filename, 'error': 'shutdown'}

    # Download
    try:
        r = smugmug_session.get(download_url, timeout=args.timeout, stream=True)
        r.raise_for_status()
    except requests.exceptions.RequestException as ex:
        update_stats(album_name, 'failed_download')
        error_msg = f'Download failed: {ex}'
        _record_failure(album_name, filename, error_msg)
        return {'status': 'failed', 'filename': filename, 'error': error_msg}

    if args.keep_files:
        os.makedirs(album_path, exist_ok=True)
        image_path = os.path.join(album_path, filename)
        try:
            with open(image_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        except Exception as ex:
            update_stats(album_name, 'failed_download')
            error_msg = f'Disk write failed: {ex}'
            _record_failure(album_name, filename, error_msg)
            return {'status': 'failed', 'filename': filename, 'error': error_msg}

        update_stats(album_name, 'downloaded')

        with open(image_path, 'rb') as f:
            success, message, asset_id = upload_to_immich(f, filename, device_asset_id, created_at)
    else:
        buf = io.BytesIO()
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                buf.write(chunk)
        buf.seek(0)
        update_stats(album_name, 'downloaded')
        success, message, asset_id = upload_to_immich(buf, filename, device_asset_id, created_at)

    if success:
        update_stats(album_name, 'uploaded')
        mark_completed(device_asset_id)
        # Add to Immich album matching SmugMug folder structure
        if asset_id:
            immich_album_id = get_or_create_immich_album(album_name, url_path)
            add_asset_to_immich_album(immich_album_id, asset_id)
        return {'status': 'success', 'filename': filename, 'result': message}

    update_stats(album_name, 'failed_upload')
    _record_failure(album_name, filename, f'Upload failed: {message}')
    return {'status': 'upload_failed', 'filename': filename, 'error': message}


# --- Main ---

# Test Immich connection
print("Testing Immich connection...", end="", flush=True)
try:
    response = immich_session.get(f"{immich_server}/api/server/version", timeout=10)
    if response.status_code == 200:
        v = response.json()
        print(f"✓ Connected to Immich v{v.get('major','?')}.{v.get('minor','?')}.{v.get('patch','?')}")
    else:
        print(f"\n✗ Failed to connect to Immich: HTTP {response.status_code}")
        sys.exit(1)
except Exception as e:
    print(f"\n✗ Failed to connect to Immich: {e}")
    sys.exit(1)

# Load resume state
state = load_state()
previously_completed = set(state.get("completed", []))
if previously_completed:
    print(f"Resuming: {len(previously_completed)} images already completed from previous run.")
    print(f"  (use --reset to start fresh)\n")

print("Downloading album list...", end="", flush=True)
albums = get_json(f"/api/v2/folder/user/{args.user}!albumlist")
if albums is None:
    print("ERROR: Could not retrieve album list.")
    sys.exit(1)
print("done.")

try:
    album_list = albums["Response"]["AlbumList"]
except KeyError:
    sys.exit(f"No albums found for user {args.user}. The user may not exist or may be password protected.")

albums_to_process = [
    a for a in album_list
    if (not args.albums) or (a["Name"].strip() in specific_albums)
]

if not albums_to_process:
    sys.exit("No matching albums found.")

# Gather all images, skipping already-completed ones
all_work = []
skipped_count = 0


def load_album_images(album):
    """Load all images for a single album (with pagination). Returns (album, images) or (album, None)."""
    if shutdown_requested:
        return album, None

    # Request larger pages and only the fields we need to reduce API load
    image_fields = "FileName,ImageKey,Key,DateTimeOriginal,DateTimeUploaded,ArchivedUri,Uris"
    images = get_json(album["Uri"] + f"!images?count=500&_filter={image_fields}")
    if images is None or shutdown_requested:
        return album, None

    if "AlbumImage" not in images["Response"]:
        return album, []

    album_images = images["Response"]["AlbumImage"]

    next_images = images
    while "NextPage" in next_images["Response"]["Pages"] and not shutdown_requested:
        next_images = get_json(next_images["Response"]["Pages"]["NextPage"])
        if next_images is None:
            break
        album_images.extend(next_images["Response"]["AlbumImage"])

    return album, album_images


album_loader_workers = min(args.workers, len(albums_to_process))
total_albums = len(albums_to_process)
print(f"Loading images from {total_albums} albums ({album_loader_workers} parallel)...", flush=True)

album_results = {}
albums_loaded = 0
load_start_time = time.time()

with ThreadPoolExecutor(max_workers=album_loader_workers) as loader:
    futures = {loader.submit(load_album_images, a): a for a in albums_to_process}
    for future in as_completed(futures):
        if shutdown_requested:
            for f in futures:
                f.cancel()
            break
        album, images = future.result()
        album_results[album["Name"]] = (album, images)
        albums_loaded += 1

        elapsed = time.time() - load_start_time
        avg_per_album = elapsed / albums_loaded
        remaining = (total_albums - albums_loaded) * avg_per_album
        mins_left = int(remaining // 60)
        secs_left = int(remaining % 60)

        status = "ERROR" if images is None else f"{len(images)} images" if images else "empty"
        print(f"  [{albums_loaded}/{total_albums}, ~{mins_left}m{secs_left:02d}s left] {album['Name']}: {status}", flush=True)

if shutdown_requested:
    save_progress()
    print("\nInterrupted during album loading. Re-run to resume.")
    sys.exit(0)

# Process results in original album order
for album in albums_to_process:
    album_name = album["Name"]
    album_path = os.path.join(output_dir, album["UrlPath"].lstrip("/"))
    url_path = album["UrlPath"]
    album_stats[album_name] = {'downloaded': 0, 'uploaded': 0, 'skipped': 0, 'failed_download': 0, 'failed_upload': 0, 'total': 0}

    _, album_images = album_results.get(album_name, (None, None))
    if not album_images:
        continue

    # Filter out already-completed images
    pending = []
    for img in album_images:
        aid = make_device_asset_id(img, album_name)
        if aid in previously_completed:
            skipped_count += 1
        else:
            pending.append(img)

    total_in_album = len(album_images)
    pending_in_album = len(pending)
    skipped_in_album = total_in_album - pending_in_album

    album_stats[album_name]['total'] = pending_in_album
    album_stats[album_name]['skipped'] = skipped_in_album
    global_stats['total'] += pending_in_album
    global_stats['skipped'] += skipped_in_album

    for img in pending:
        all_work.append((img, album_path, album_name, url_path))

if not all_work:
    if skipped_count > 0:
        print(f"\nAll {skipped_count} images already uploaded! Nothing to do.")
        print("Use --reset to re-upload everything.")
    else:
        print("No images found across selected albums.")
    sys.exit(0)

print(f"\nProcessing {len(all_work)} images across {len(albums_to_process)} album(s) with {args.workers} workers...")
if skipped_count > 0:
    print(f"Skipping {skipped_count} already-completed images.")
print(f"Files will be {'KEPT locally' if args.keep_files else 'streamed in-memory (no disk writes)'}")
print(f"Photos will be organized into Immich albums matching SmugMug folder structure.")
print(f"Progress is auto-saved — interrupt with Ctrl+C and re-run to resume.\n")

bar_format = '{l_bar}{bar:-2}| {n_fmt:>5}/{total_fmt:<5} [{elapsed}<{remaining}]'

# Periodic save interval
SAVE_INTERVAL = 50  # save every N completions
completions_since_save = 0

with ThreadPoolExecutor(max_workers=args.workers) as executor:
    future_to_info = {
        executor.submit(download_and_upload_image, img, path, name, upath): (img, name)
        for img, path, name, upath in all_work
    }

    with tqdm(total=len(all_work),
              desc=f"{attr('bold')}Total progress{attr('reset')}",
              bar_format=bar_format, position=0, leave=True) as pbar:
        for future in as_completed(future_to_info):
            result = future.result()
            pbar.update(1)
            completions_since_save += 1

            if result['status'] in ('failed', 'upload_failed') and args.verbose_errors:
                _, aname = future_to_info[future]
                tqdm.write(f"  ✗ [{aname}] {result['status']}: {result['filename']} - {result.get('error', '?')}")

            # Periodically save progress
            if completions_since_save >= SAVE_INTERVAL:
                save_progress()
                completions_since_save = 0

            if shutdown_requested:
                # Cancel pending futures
                for f in future_to_info:
                    f.cancel()
                break

# Always save progress on exit
save_progress()

# Clean up empty dirs
if not args.keep_files:
    for album in albums_to_process:
        album_path = os.path.join(output_dir, album["UrlPath"].lstrip("/"))
        try:
            if os.path.isdir(album_path) and not os.listdir(album_path):
                os.rmdir(album_path)
        except OSError:
            pass

# --- Summary ---
print("\n" + "=" * 60)
if shutdown_requested:
    print("INTERRUPTED — progress saved, re-run to resume")
else:
    print("COMPLETE")
print("=" * 60)
print(f"  Total pending:       {global_stats['total']}")
print(f"  Skipped (resumed):   {global_stats['skipped']}")
print(f"  Downloaded:          {global_stats['downloaded']}")
print(f"  Uploaded to Immich:  {global_stats['uploaded']}")
print(f"  Failed Downloads:    {global_stats['failed_download']}")
print(f"  Failed Uploads:      {global_stats['failed_upload']}")
print("=" * 60)

if len(albums_to_process) > 1:
    print("\nPer-album breakdown:")
    for aname, s in album_stats.items():
        if s['total'] == 0 and s['skipped'] == 0:
            continue
        failed = s['failed_download'] + s['failed_upload']
        parts = []
        if s['uploaded']:
            parts.append(f"{s['uploaded']} uploaded")
        if s['skipped']:
            parts.append(f"{s['skipped']} skipped")
        if failed:
            parts.append(f"{failed} failed")
        print(f"  {aname}: {', '.join(parts)}")

if failed_files:
    print(f"\n{'=' * 60}")
    print(f"FAILED FILES ({len(failed_files)} total)")
    print(f"{'=' * 60}")

    albums_with_failures = {}
    for failure in failed_files:
        albums_with_failures.setdefault(failure['album'], []).append(failure)

    for alb, failures in albums_with_failures.items():
        print(f"\n  {alb}: {len(failures)} failed")
        for f in failures[:5]:
            print(f"    - {f['filename']}: {f['error']}")
        if len(failures) > 5:
            print(f"    ... and {len(failures) - 5} more")

if shutdown_requested:
    with completed_ids_lock:
        total_done = len(previously_completed) + len(completed_ids)
    print(f"\nProgress saved: {total_done} images total completed.")
    print("Re-run the same command to resume from where you left off.")
elif not args.keep_files:
    print("\n✓ No local files written (streamed in-memory)")
