import os
import subprocess
import time
from typing import Tuple
from pathlib import Path
from urllib.parse import urlparse
from bot import config

valid_domains = config.domains["valid_domains"]

class DownloadError(Exception):
    pass

def get_platform(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    for valid_domain in valid_domains:
        if valid_domain in domain:
            return valid_domain
    raise DownloadError(f"Unsupported platform: {domain}")

def download_video(url: str, output_dir: str) -> Tuple[str, int]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = int(time.time())
    filename_prefix = f"video_{timestamp}"
    output_path_template = str(output_dir / f"{filename_prefix}.%(ext)s")

    try:
        platform = get_platform(url)
        
        cmd = [
            "yt-dlp",
            url,
            "-f", "best",
            "-o", output_path_template,
            "--no-warnings",
            "--no-playlist",
            "--merge-output-format", "mp4"  # Force MP4 output
        ]

        if platform in ['youtube', 'youtu']:
            cmd.extend(["--cookies", "cookies/cookie.txt"])

        print(f"Debug: Running command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if result.returncode != 0:
            raise DownloadError(f"Download failed: {result.stderr.strip()}")

        all_files = list(output_dir.glob(f"{filename_prefix}.*"))
        print("Debug: Files in output directory after download:", [f.name for f in all_files])

        if not all_files:
            raise DownloadError("Download completed but file not found.")

        downloaded_file = all_files[0]
        file_size = downloaded_file.stat().st_size

        print(f"Debug: Download completed successfully: {downloaded_file}, Size: {file_size} bytes")
        return str(downloaded_file), file_size

    except Exception as e:
        # Cleanup any partially downloaded files on error
        for f in output_dir.glob(f"{filename_prefix}.*"):
            try:
                f.unlink()
                print(f"Debug: Removed partially downloaded file: {f.name}")
            except OSError as cleanup_error:
                print(f"Debug: Error cleaning up file {f}: {cleanup_error}")
        raise DownloadError(f"Download failed: {str(e)}")

def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and \
               any(domain in result.netloc for domain in valid_domains)
    except Exception:
        return False