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
        """
        Create a Downloader instance configured with an optional storage quota.
        
        Parameters:
            max_storage_mb (int | None): Maximum allowed storage for downloaded tracks in megabytes. If `None` or a value less than or equal to zero, storage quota enforcement is disabled.
        """
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
        Finds the first YouTube video URL matching the given search query.
        
        @returns
            str: URL of the top matching YouTube video, or `None` if no match is found.
        """
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'default_search': 'ytsearch1',
        }

        def _search():
            """
            Finds the webpage URL of the first video returned by a yt_dlp query.
            
            Returns:
                str: The first result's `webpage_url` if a match is found, `None` otherwise.
            """
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                entries = info.get('entries') or []
                return entries[0]['webpage_url'] if entries else None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, _search)

    async def download_track(self, url: str, track_id: str) -> str:
        """
        Download a YouTube audio track as an MP3 file named by track_id into the tracks directory.
        
        If a file for the given track_id already exists, the existing file path is returned (cache hit) and storage quota enforcement runs. After a successful download the storage quota is enforced and the saved file path is returned.
        
        Parameters:
            url (str): YouTube video URL to download audio from.
            track_id (str): Identifier used as the output filename (file stem, without extension).
        
        Returns:
            Path: The filesystem path of the saved MP3 file.
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
            """
            Perform the download for the configured URL using the surrounding `ydl_opts`.
            
            Executes yt_dlp with the options provided in the enclosing scope to download the specified `url` according to the configured output template and post-processing steps.
            """
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, _download)
        
        self._enforce_storage_quota()

        return output_path

    def _directory_size(self, root: Path) -> int:
        """
        Compute the total size of all files under the given directory tree.
        
        Parameters:
            root (Path): Root directory to traverse and measure.
        
        Returns:
            total_size (int): Sum in bytes of all files under `root`; files that raise OSError during stat are skipped.
        """
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
        """
        Remove oldest downloaded tracks (and their cover images) until the downloads directory size is within the configured storage limit.
        
        If no storage limit is configured or the current size is already within the limit, this is a no-op. When the limit is exceeded, the method deletes the oldest MP3 files from TRACKS_DIR in batches of CLEANUP_BATCH, removes their corresponding cover images named {stem}.jpg from COVERS_DIR if present, and calls database.delete_track for each removed track.
        """
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
