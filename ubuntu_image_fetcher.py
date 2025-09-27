# ubuntu_image_fetcher.py
# Ubuntu-inspired Image Fetcher
# - Multiple URLs supported (comma/space separated)
# - Creates Fetched_Images/
# - Validates HTTP response & headers
# - Streams to disk (binary mode)
# - Deduplicates by SHA-256 content hash
# - Friendly, respectful error handling

import os
import re
import time
import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

OUT_DIR = Path("Fetched_Images")
TIMEOUT = 15
MAX_SIZE_MB = 20  # soft limit to avoid huge downloads
HEADERS = {
    "User-Agent": "UbuntuImageFetcher/1.0 (+community; respectful use)"
}

def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "_").replace("/", "_").replace("\0", "")
    return name.strip() or f"image_{int(time.time()*1000)}.jpg"

def guess_ext(content_type: str) -> str:
    if not content_type:
        return ".jpg"
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
    return ext or ".jpg"

def derive_filename(url: str, response: requests.Response) -> str:
    # Try Content-Disposition first
    cd = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if match:
        return sanitize_filename(os.path.basename(unquote(match.group(1))))

    # Fall back to URL path
    path_name = sanitize_filename(os.path.basename(unquote(urlparse(url).path)))
    if path_name:
        return path_name

    # Last resort: synthesize name from content-type
    ext = guess_ext(response.headers.get("Content-Type", ""))
    return f"image_{int(time.time()*1000)}{ext}"

def ensure_unique(out_dir: Path, name: str) -> str:
    base, ext = os.path.splitext(name)
    candidate = name
    i = 1
    while (out_dir / candidate).exists():
        candidate = f"{base}_{i}{ext}"
        i += 1
    return candidate

def load_manifest(out_dir: Path):
    mpath = out_dir / "manifest_sha256.txt"
    if mpath.exists():
        hashes = {line.strip() for line in mpath.read_text(encoding="utf-8").splitlines() if line.strip()}
    else:
        hashes = set()
    return hashes, mpath

def append_manifest(mpath: Path, digest: str):
    with mpath.open("a", encoding="utf-8") as f:
        f.write(digest + "\n")

def download_one(url: str, out_dir: Path, known_hashes: set, mpath: Path):
    try:
        with requests.get(url, stream=True, headers=HEADERS, timeout=TIMEOUT) as r:
            r.raise_for_status()

            ctype = r.headers.get("Content-Type", "")
            if not ctype.startswith("image/"):
                print(f"✗ Skipping (not an image): {url} [{ctype or 'unknown type'}]")
                return

            size = r.headers.get("Content-Length")
            if size and int(size) > MAX_SIZE_MB * 1024 * 1024:
                mb = int(size) / (1024 * 1024)
                print(f"✗ Skipping (too large: {mb:.1f} MB): {url}")
                return

            name = ensure_unique(out_dir, derive_filename(url, r))
            tmp = out_dir / (name + ".part")

            # Stream to disk and compute hash to dedupe
            sha = hashlib.sha256()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    sha.update(chunk)
                    f.write(chunk)

            digest = sha.hexdigest()
            if digest in known_hashes:
                tmp.unlink(missing_ok=True)
                print(f"• Duplicate content skipped ({name})")
                return

            tmp.rename(out_dir / name)
            append_manifest(mpath, digest)
            known_hashes.add(digest)

            print(f"✓ Successfully fetched: {name}")
            print(f"✓ Image saved to {out_dir / name}")

    except requests.exceptions.RequestException as e:
        print(f"✗ Connection error: {e}")
    except OSError as e:
        print(f"✗ File error: {e}")

def main():
    print("Welcome to the Ubuntu Image Fetcher")
    print("A tool for mindfully collecting images from the web\n")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    known_hashes, mpath = load_manifest(OUT_DIR)

    raw = input("Enter one or more image URLs (comma or space separated):\n> ").strip()
    urls = [u for u in re.split(r"[,\s]+", raw) if u]

    if not urls:
        print("No URL provided. Exiting gracefully.")
        return

    for url in urls:
        download_one(url, OUT_DIR, known_hashes, mpath)

    print("\nConnection strengthened. Community enriched.")

if __name__ == "__main__":
    main()

