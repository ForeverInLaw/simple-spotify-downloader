import os
import logging
import asyncio
from pathlib import Path
import yt_dlp
from concurrent.futures import ThreadPoolExecutor

from modules import database

# Create directories if they don't exist
DOWNLOADS_ROOT = Path('downloads')
TRACKS_DIR = DOWNLOADS_ROOT / 'tracks'
COVERS_DIR = DOWNLOADS_ROOT / 'covers'
DOWNLOADS_ROOT.mkdir(exist_ok=True)
TRACKS_DIR.mkdir(parents=True, exist_ok=True)
COVERS_DIR.mkdir(parents=True, exist_ok=True)

CLEANUP_BATCH = 2

class Downloader:
    def __init__(self, max_storage_mb: int | None = None):
        self.executor = ThreadPoolExecutor(max_workers=4)
        if max_storage_mb is None or max_storage_mb <= 0:
            self.max_storage_bytes = 0
        else:
            self.max_storage_bytes = max_storage_mb * 1024 * 1024

    def close(self) -> None:
        """Release executor resources."""
        self.executor.shutdown(wait=False)

    async def search_youtube(self, query: str) -> str | None:
        """
        Searches for a video on YouTube using yt-dlp and returns the URL.
        """
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'default_search': 'ytsearch1',
        }

        def _search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                entries = info.get('entries') or []
                return entries[0]['webpage_url'] if entries else None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, _search)

    async def download_track(self, url: str, track_id: str) -> str:
        """
        Downloads the track from YouTube URL.
        Returns the path to the downloaded file.
        """
        output_path = TRACKS_DIR / f'{track_id}.mp3'
        
        # Check if already exists
        if output_path.exists():
            logging.info(f"Track {track_id} found in cache.")
            self._enforce_storage_quota()
            return output_path

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(TRACKS_DIR / f'{track_id}.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
        }

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, _download)
        
        self._enforce_storage_quota()

        return output_path

    def _directory_size(self, root: Path) -> int:
        total = 0
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                file_path = Path(dirpath) / name
                try:
                    total += file_path.stat().st_size
                except OSError:
                    continue
        return total

    def _enforce_storage_quota(self) -> None:
        if not self.max_storage_bytes:
            return

        total_size = self._directory_size(DOWNLOADS_ROOT)
        if total_size <= self.max_storage_bytes:
            return

        logging.warning(
            "Downloads folder size %sMB exceeds limit %sMB. Cleaning up oldest tracks...",
            round(total_size / (1024 * 1024), 2),
            round(self.max_storage_bytes / (1024 * 1024), 2),
        )

        while total_size > self.max_storage_bytes:
            track_files = sorted(
                TRACKS_DIR.glob('*.mp3'),
                key=lambda path: path.stat().st_ctime,
            )

            if not track_files:
                break

            deleted_something = False
            for path in track_files[:CLEANUP_BATCH]:
                try:
                    path.unlink()
                    deleted_something = True
                    logging.info("Removed cached track %s due to storage limit", path.name)
                    database.delete_track(path.stem)

                    cover_path = COVERS_DIR / f"{path.stem}.jpg"
                    if cover_path.exists():
                        cover_path.unlink()
                        deleted_something = True
                        logging.info("Removed cached cover %s", cover_path.name)
                except OSError as exc:
                    logging.warning("Failed to remove %s: %s", path, exc)

            total_size = self._directory_size(DOWNLOADS_ROOT)

            if not deleted_something:
                logging.warning(
                    "Cleanup stalled; failed to delete any files despite exceeding storage limit"
                )
                break
