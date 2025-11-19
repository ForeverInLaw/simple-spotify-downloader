import logging
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest
from aiohttp import ClientError
from dotenv import load_dotenv

# Import modules
from modules import database
from modules.spotify_api import SpotifyClient
from modules.downloader import Downloader, TRACKS_DIR, COVERS_DIR

load_dotenv()


def get_required_env(var_name: str) -> str:
    """
    Retrieve a required environment variable by name.
    
    Parameters:
        var_name (str): Name of the environment variable to read.
    
    Returns:
        str: The environment variable value.
    
    Raises:
        RuntimeError: If the environment variable is not set or is empty.
    """
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"Environment variable '{var_name}' must be set.")
    return value


def get_optional_int_env(var_name: str) -> int | None:
    """
    Retrieve an optional integer from the environment by variable name.
    
    Parameters:
        var_name (str): Name of the environment variable to read.
    
    Returns:
        int | None: The integer value if the variable is present and parses as an integer; otherwise `None`.
    
    Raises:
        ValueError: If the environment variable is set but cannot be parsed as an integer.
    """
    value = os.getenv(var_name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable '{var_name}' must be an integer.") from exc


TELEGRAM_API_TOKEN = get_required_env("TELEGRAM_API_TOKEN")
SPOTIFY_CLIENT_ID = get_required_env("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = get_required_env("SPOTIFY_CLIENT_SECRET")
STORAGE_LIMIT_MB = get_optional_int_env("STORAGE_LIMIT_MB")

LOG_FILE = 'logs.txt'
LOG_MAX_AGE = timedelta(days=1)


def cleanup_logs(path: str, max_age: timedelta) -> None:
    """
    Truncates the log file at the given path when its last modification time is older than the specified maximum age.
    
    Parameters:
        path (str): Filesystem path to the log file to check.
        max_age (timedelta): Maximum allowed age; if the file's age (now - last modification time) is greater than this, the file will be emptied.
    
    Notes:
        If the file does not exist, the function does nothing.
    """
    if not os.path.exists(path):
        return

    file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
    if file_age > max_age:
        open(path, 'w', encoding='utf-8').close()


cleanup_logs(LOG_FILE, LOG_MAX_AGE)


def ensure_cover_constraints(path: Path | str) -> None:
    """
    Ensure a cover image meets Telegram audio thumbnail requirements.
    
    If the file exists, converts the image to RGB JPEG and resizes it to at most 320×320 pixels (preserving aspect ratio), overwriting the original file with an optimized JPEG at quality 85. If the file does not exist, the function does nothing.
    
    Parameters:
        path (Path | str): Path to the cover image file.
    """
    cover_path = Path(path)
    if not cover_path.exists():
        return

    with Image.open(cover_path) as img:
        img = img.convert('RGB')
        img.thumbnail((320, 320))
        img.save(cover_path, format='JPEG', optimize=True, quality=85)


async def download_cover_image(url: str, destination: Path) -> None:
    """
    Download an image from the given URL and write it to the specified destination path.
    
    Parameters:
        url (str): HTTP(S) URL of the image to download.
        destination (Path): Filesystem path where the image will be saved; parent directories are created if missing.
    
    Raises:
        asyncio.TimeoutError: If the request does not complete within 15 seconds.
        aiohttp.ClientResponseError: If the HTTP response status indicates an error.
        aiohttp.ClientError: For other network-related errors.
        OSError: If writing the file to disk fails.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with asyncio.timeout(15):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.read()
    destination.write_bytes(data)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%d-%b-%y %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Initialize components
bot = Bot(token=TELEGRAM_API_TOKEN)
dp = Dispatcher()
spotify_client = SpotifyClient(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
downloader = Downloader(max_storage_mb=STORAGE_LIMIT_MB)

# Initialize DB
database.init_db()

@dp.message(Command('start'))
async def welcome(message: types.Message):
    """
    Register the sender of a Telegram message in the user database and send a localized welcome prompt.
    
    Parameters:
        message (aiogram.types.Message): Incoming Telegram message whose sender (id, username, first_name, last_name) will be recorded and who will receive the greeting.
    """
    user = message.from_user
    database.add_user(user.id, user.username, user.first_name, user.last_name)
    await message.answer(
        f"Приветик, *{user.first_name}*! \nПросто пришли сюда ссылку на трек в Spotify!", 
        parse_mode='Markdown'
    )

@dp.message(F.text)
async def process_track_link(message: types.Message):
    """
    Process an incoming Telegram message that contains a Spotify track link and deliver the corresponding audio to the user.
    
    Parses the Spotify link from the provided message, resolves track metadata (using cache when available), ensures cover art meets thumbnail constraints, downloads the audio from YouTube if not cached, and sends the audio with title, performer, and thumbnail to the chat. Handles network and processing errors by notifying the user and always removes the temporary status message after completion.
    """
    if not spotify_client.is_spotify_link(message.text):
        logging.info(f"{message.date} - {message.chat.id} - {message.text}")
        return

    status_msg = await message.answer("🔍 Ищу трек...")

    status_deleted = False

    async def delete_status_message() -> None:
        """
        Safely deletes the current status message if it has not already been deleted.
        
        If deletion fails due to a TelegramBadRequest error, the error is suppressed. Always marks the status as deleted so subsequent calls are no-ops.
        """
        nonlocal status_deleted
        if status_deleted:
            return
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass
        finally:
            status_deleted = True

    try:
        # 1. Resolve track ID and get metadata (cache first)
        track_id = spotify_client.extract_track_id(message.text)
        if not track_id:
            await message.answer("❌ Не удалось получить ID трека.")
            return

        track_info = database.get_track(track_id)
        if not track_info:
            track_info = spotify_client.get_track_info(track_id)
            database.upsert_track(track_info)

        track_name = track_info['name']
        artist_name = track_info['artist']
        mp3_path = TRACKS_DIR / f"{track_id}.mp3"

        # 2. Handle Cover Art
        cover_path = COVERS_DIR / f"{track_id}.jpg"
        if not cover_path.exists():
            await download_cover_image(track_info['image_url'], cover_path)
        ensure_cover_constraints(cover_path)

        thumb = FSInputFile(cover_path)

        # 3. Use cache if exists, otherwise search/download
        if mp3_path.exists():
            await status_msg.edit_text("📤 Отправляю...")
        else:
            await status_msg.edit_text(f"📥 Скачиваю: {artist_name} - {track_name}")
            search_query = f"{artist_name} - {track_name} audio"
            youtube_url = await downloader.search_youtube(search_query)

            if not youtube_url:
                await message.answer("❌ Не удалось найти трек на YouTube.")
                return

            mp3_path = await downloader.download_track(youtube_url, track_id)

        # 4. Send Audio
        audio_file = FSInputFile(mp3_path)
        await message.answer_audio(
            audio=audio_file, 
            title=track_name, 
            performer=artist_name, 
            thumbnail=thumb
        )

    except (ClientError, asyncio.TimeoutError) as exc:
        logging.error(f"Error downloading cover art: {exc}")
        await message.answer("❌ Не удалось загрузить обложку. Попробуйте позже.")
    except Exception as e:
        logging.error(f"Error processing request: {e}")
        await message.answer("❌ Произошла ошибка при обработке. Попробуйте позже.")
    finally:
        await delete_status_message()

async def main():
    """
    Start the bot's polling loop and keep it running, retrying on transient Telegram network errors.
    
    This coroutine begins long-lived polling of incoming updates for the configured Dispatcher and Bot. If a Telegram network error occurs, polling is retried after a short delay. If the coroutine is cancelled, it logs shutdown intent and re-raises asyncio.CancelledError. The function returns when polling stops normally.
    """
    logging.info("Starting bot...")
    retry_delay = 3

    while True:
        try:
            await dp.start_polling(bot)
        except TelegramNetworkError as exc:
            logging.warning(
                "Polling stopped due to Telegram network error: %s. Retrying in %s seconds...",
                exc,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
        except asyncio.CancelledError:
            logging.info("Polling cancelled. Shutting down gracefully.")
            raise
        else:
            logging.info("Polling finished.")
            break


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user.")
    finally:
        downloader.close()
