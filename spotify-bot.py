import logging
import asyncio
import os
import re
import zipfile
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
ZIP_THRESHOLD = get_optional_int_env("ZIP_THRESHOLD") or 10
MAX_ZIP_SIZE = 48 * 1024 * 1024  # 48 MB limit for Telegram bots

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
    log_path = Path(path)
    if not log_path.exists():
        return

    file_age = datetime.now() - datetime.fromtimestamp(log_path.stat().st_mtime)
    if file_age > max_age:
        log_path.write_text('', encoding='utf-8')


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
    Process an incoming Spotify link and route it to the proper handler.

    The function first checks whether the message references a playlist or album and delegates to the
    playlist/album handlers when needed. For single-track links it resolves track metadata (using cache when
    available), ensures cover art meets thumbnail constraints, downloads the audio from YouTube if not cached,
    and sends the audio with title, performer, and thumbnail to the chat. Handles network and processing errors
    by notifying the user and always removes the temporary status message after completion.
    """
    # Check if it's a playlist first
    playlist_id = spotify_client.extract_playlist_id(message.text)
    if playlist_id:
        await process_playlist_link(message, playlist_id)
        return

    # Check if it's an album
    album_id = spotify_client.extract_album_id(message.text)
    if album_id:
        await process_album_link(message, album_id)
        return

    if not spotify_client.is_spotify_link(message.text):
        logging.info(f"{message.date} - {message.chat.id} - {message.text}")
        return

    status_msg = await message.answer("🔍 Ищу трек...")

    try:
        track_id = spotify_client.extract_track_id(message.text)
        if not track_id:
            await message.answer("❌ Не удалось получить ID трека.")
            await status_msg.delete()
            return

        await download_and_send_track(message, track_id, status_msg)

    except Exception:
        logging.exception("Error processing request")
        await message.answer("❌ Произошла ошибка при обработке. Попробуйте позже.")
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass


async def send_tracks_one_by_one(
    message: types.Message,
    status_msg: types.Message,
    tracks: list,
    collection_name: str,
    collection_type: str,  # "Плейлист" or "Альбом"
    artist_name: str | None = None  # For albums
):
    """
    Downloads and sends tracks one by one, updating a status message.
    """
    total_tracks = len(tracks)
    # Concurrency limit
    semaphore = asyncio.Semaphore(10)
    completed_count = 0
    failed_count = 0

    async def bounded_download(track):
        nonlocal completed_count, failed_count
        async with semaphore:
            database.upsert_track(track)
            success = True
            try:
                await download_and_send_track(message, track['id'], None)
            except Exception:
                success = False
                logging.exception("Failed to download/send track %s", track.get('id'))
            finally:
                completed_count += 1
                if not success:
                    failed_count += 1
                if completed_count % 3 == 0 or completed_count == total_tracks:
                    try:
                        status_text = (
                            f"💿 Альбом: {collection_name}\n"
                            if collection_type == "Альбом"
                            else f"📄 Плейлист: {collection_name}\n"
                        )
                        status_text += (
                            f"📤 Загрузка: {completed_count}/{total_tracks}\n"
                            f"🎵 Обработано: {track['artist']} - {track['name']}"
                        )
                        await status_msg.edit_text(status_text)
                    except TelegramBadRequest:
                        pass

    tasks = [bounded_download(track) for track in tracks]
    await asyncio.gather(*tasks)

    if failed_count:
        await status_msg.edit_text(
            f"⚠️ {collection_type} {collection_name} загружен с ошибками.\n"
            f"Успешно: {total_tracks - failed_count}/{total_tracks}"
        )
    else:
        await status_msg.edit_text(f"✅ {collection_type} {collection_name} загружен!")


async def process_playlist_link(message: types.Message, playlist_id: str):
    """
    Process a Spotify playlist link: fetch tracks and send them concurrently.
    """
    status_msg = await message.answer("🔍 Получаю информацию о плейлисте...")
    try:
        playlist_info = spotify_client.get_playlist_info(playlist_id)
        playlist_name = playlist_info['name']
        total_tracks = playlist_info['total_tracks']

        if total_tracks > ZIP_THRESHOLD:
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="Скачать ZIP", callback_data=f"zip_playlist:{playlist_id}"),
                    types.InlineKeyboardButton(text="Отправлять по одному",
                                               callback_data=f"one_by_one_playlist:{playlist_id}")
                ]
            ])
            await status_msg.edit_text(
                f"📄 В плейлисте '{playlist_name}' {total_tracks} треков.\n"
                "Хотите скачать их одним ZIP-архивом?",
                reply_markup=keyboard
            )
            return

        await status_msg.edit_text(f"📄 Плейлист: {playlist_name}\n🔢 Треков: {total_tracks}\n🚀 Начинаю загрузку...")
        tracks = spotify_client.get_playlist_tracks(playlist_id)
        await send_tracks_one_by_one(message, status_msg, tracks, playlist_name, "Плейлист")

    except Exception:
        logging.exception("Error processing playlist")
        await message.answer("❌ Произошла ошибка при обработке плейлиста.")
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass


async def process_album_link(message: types.Message, album_id: str):
    """
    Process a Spotify album link: fetch tracks and send them concurrently.
    """
    status_msg = await message.answer("🔍 Получаю информацию об альбоме...")
    try:
        album_info = spotify_client.get_album_info(album_id)
        album_name = album_info['name']
        artist_name = album_info['artist']
        total_tracks = album_info['total_tracks']

        if total_tracks > ZIP_THRESHOLD:
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="Скачать ZIP", callback_data=f"zip_album:{album_id}"),
                    types.InlineKeyboardButton(text="Отправлять по одному",
                                               callback_data=f"one_by_one_album:{album_id}")
                ]
            ])
            await status_msg.edit_text(
                f"💿 В альбоме '{album_name}' {total_tracks} треков.\n"
                "Хотите скачать их одним ZIP-архивом?",
                reply_markup=keyboard
            )
            return

        await status_msg.edit_text(
            f"💿 Альбом: {album_name} - {artist_name}\n🔢 Треков: {total_tracks}\n🚀 Начинаю загрузку...")
        tracks = spotify_client.get_album_tracks(album_id, album_info)
        await send_tracks_one_by_one(message, status_msg, tracks, album_name, "Альбом", artist_name=artist_name)

    except Exception:
        logging.exception("Error processing album")
        await message.answer("❌ Произошла ошибка при обработке альбома.")
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data.startswith("one_by_one_playlist:"))
async def handle_one_by_one_playlist(callback_query: types.CallbackQuery):
    playlist_id = callback_query.data.split(":")[1]
    message = callback_query.message
    status_msg = await message.answer("🚀 Начинаю загрузку треков по одному...")

    try:
        playlist_info = spotify_client.get_playlist_info(playlist_id)
        tracks = spotify_client.get_playlist_tracks(playlist_id)
        await send_tracks_one_by_one(message, status_msg, tracks, playlist_info['name'], "Плейлист")
    except Exception:
        logging.exception("Error processing one_by_one_playlist callback")
        await message.answer("❌ Произошла ошибка.")
    finally:
        await callback_query.message.delete()


@dp.callback_query(F.data.startswith("zip_playlist:"))
async def handle_zip_playlist(callback_query: types.CallbackQuery):
    playlist_id = callback_query.data.split(":")[1]
    status_msg = callback_query.message

    try:
        playlist_info = spotify_client.get_playlist_info(playlist_id)
        tracks = spotify_client.get_playlist_tracks(playlist_id)
        await download_and_zip_tracks(status_msg, tracks, playlist_info['name'], "Плейлист")
    except Exception:
        logging.exception("Error processing zip_playlist callback")
        await status_msg.edit_text("❌ Произошла ошибка при обработке плейлиста для ZIP.")


@dp.callback_query(F.data.startswith("one_by_one_album:"))
async def handle_one_by_one_album(callback_query: types.CallbackQuery):
    album_id = callback_query.data.split(":")[1]
    message = callback_query.message
    status_msg = await message.answer("🚀 Начинаю загрузку треков по одному...")

    try:
        album_info = spotify_client.get_album_info(album_id)
        tracks = spotify_client.get_album_tracks(album_id, album_info)
        await send_tracks_one_by_one(message, status_msg, tracks, album_info['name'], "Альбом", artist_name=album_info['artist'])
    except Exception:
        logging.exception("Error processing one_by_one_album callback")
        await message.answer("❌ Произошла ошибка.")
    finally:
        await callback_query.message.delete()


@dp.callback_query(F.data.startswith("zip_album:"))
async def handle_zip_album(callback_query: types.CallbackQuery):
    album_id = callback_query.data.split(":")[1]
    status_msg = callback_query.message

    try:
        album_info = spotify_client.get_album_info(album_id)
        tracks = spotify_client.get_album_tracks(album_id, album_info)
        await download_and_zip_tracks(status_msg, tracks, album_info['name'], "Альбом")
    except Exception:
        logging.exception("Error processing zip_album callback")
        await status_msg.edit_text("❌ Произошла ошибка при обработке альбома для ZIP.")


async def download_track_for_zip(track: dict, semaphore: asyncio.Semaphore) -> Path | None:
    """
    Downloads a single track for ZIP packaging.
    """
    async with semaphore:
        database.upsert_track(track)
        track_id = track['id']
        mp3_path = TRACKS_DIR / f"{track_id}.mp3"

        if mp3_path.exists():
            return mp3_path

        search_query = f"{track['artist']} - {track['name']} audio"
        try:
            youtube_url = await downloader.search_youtube(search_query)
            if not youtube_url:
                logging.warning("No YouTube link found for %s", search_query)
                return None

            # Temporarily disable quota for ZIP downloads
            return await downloader.download_track(youtube_url, track_id, enforce_quota=False)
        except Exception:
            logging.exception("Failed to download track %s for zipping", track_id)
            return None


async def download_and_zip_tracks(
    status_msg: types.Message,
    tracks: list,
    collection_name: str,
    collection_type: str
):
    """
    Downloads all tracks, zips them, sends the archive, and cleans up.
    """
    total_tracks = len(tracks)
    sanitized_collection_name = re.sub(r'[\/:*?"<>|]', '_', collection_name)

    downloader.pause_quota_enforcement()

    try:
        await status_msg.edit_text(f"📥 Подготовка к скачиванию {collection_type} '{collection_name}'...")

        semaphore = asyncio.Semaphore(10)
        completed_count = 0

        async def download_and_update_status(track):
            nonlocal completed_count
            path = await download_track_for_zip(track, semaphore)
            completed_count += 1
            try:
                await status_msg.edit_text(
                    f"📥 Скачиваю {collection_type} '{collection_name}'...\n"
                    f"({completed_count}/{total_tracks}) {track['artist']} - {track['name']}"
                )
            except TelegramBadRequest:  # Message not modified
                pass
            return path

        tasks = [download_and_update_status(track) for track in tracks]
        results = await asyncio.gather(*tasks)

        downloaded_paths = [path for path in results if path]
        failed_count = total_tracks - len(downloaded_paths)

        if not downloaded_paths:
            await status_msg.edit_text(f"❌ Не удалось скачать ни одного трека из {collection_type} '{collection_name}'.")
            return

        await status_msg.edit_text(f"📦 Группирую треки для архивации...")

        # Split tracks into chunks to respect Telegram's file size limit
        zip_chunks = []
        current_chunk_size = 0
        current_chunk = []
        for path in downloaded_paths:
            size = path.stat().st_size
            if current_chunk_size + size > MAX_ZIP_SIZE and current_chunk:
                zip_chunks.append(current_chunk)
                current_chunk = []
                current_chunk_size = 0
            current_chunk.append(path)
            current_chunk_size += size
        if current_chunk:
            zip_chunks.append(current_chunk)

        for i, chunk in enumerate(zip_chunks):
            part_num = i + 1
            zip_filename = f"{sanitized_collection_name} (Часть {part_num}).zip"
            zip_path = TRACKS_DIR / zip_filename

            await status_msg.edit_text(f"📦 Создаю архив {part_num}/{len(zip_chunks)} для '{collection_name}'...")
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for track_path in chunk:
                    zipf.write(track_path, arcname=track_path.name)

            await status_msg.edit_text(f"📤 Отправляю архив {part_num}/{len(zip_chunks)} '{collection_name}'...")
            await status_msg.answer_document(FSInputFile(zip_path))

            if zip_path.exists():
                zip_path.unlink()

        if failed_count > 0:
            await status_msg.edit_text(
                f"✅ {collection_type} '{collection_name}' отправлен, но {failed_count} из {total_tracks} треков не удалось скачать."
            )
        else:
            await status_msg.edit_text(f"✅ {collection_type} '{collection_name}' успешно скачан и отправлен!")

    except Exception:
        logging.exception("Error during zipping process")
        await status_msg.edit_text(f"❌ Произошла ошибка при создании архива для '{collection_name}'.")
    finally:
        # Cleanup is now handled by the quota enforcer, so we just resume it.
        downloader.resume_quota_enforcement()


async def download_and_send_track(message: types.Message, track_id: str, status_msg: types.Message | None = None):
    """
    Download and send a single track to the user.
    
    Parameters:
        message: The original message to reply to.
        track_id: The Spotify track ID.
        status_msg: Optional status message to update. If None, no status updates are sent (assumed part of playlist).
    """
    status_deleted = False

    async def delete_status_message() -> None:
        nonlocal status_deleted
        if status_deleted or not status_msg:
            return
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass
        finally:
            status_deleted = True

    try:
        track_info = database.get_track(track_id)
        if not track_info:
            track_info = spotify_client.get_track_info(track_id)
            database.upsert_track(track_info)

        track_name = track_info['name']
        artist_name = track_info['artist']
        mp3_path = TRACKS_DIR / f"{track_id}.mp3"

        # Handle Cover Art
        thumb: FSInputFile | None = None
        image_url = track_info.get('image_url')
        if image_url:
            cover_path = COVERS_DIR / f"{track_id}.jpg"
            try:
                if not cover_path.exists():
                    await download_cover_image(image_url, cover_path)
                ensure_cover_constraints(cover_path)
                if cover_path.exists():
                    thumb = FSInputFile(cover_path)
            except (ClientError, asyncio.TimeoutError):
                logging.exception("Error downloading cover art")
                if status_msg:
                    await message.answer("⚠️ Не удалось загрузить обложку, отправляю трек без неё.")

        # Download if needed
        if mp3_path.exists():
            if status_msg:
                await status_msg.edit_text("📤 Отправляю...")
        else:
            if status_msg:
                await status_msg.edit_text(f"📥 Скачиваю: {artist_name} - {track_name}")
            search_query = f"{artist_name} - {track_name} audio"
            youtube_url = await downloader.search_youtube(search_query)

            if not youtube_url:
                if status_msg:
                    await message.answer("❌ Не удалось найти трек на YouTube.")
                return

            mp3_path = await downloader.download_track(youtube_url, track_id)

        # Send Audio
        audio_file = FSInputFile(mp3_path)
        audio_kwargs = {
            "audio": audio_file,
            "title": track_name,
            "performer": artist_name,
        }
        if thumb:
            audio_kwargs['thumbnail'] = thumb

        await message.answer_audio(**audio_kwargs)

    except Exception:
        logging.exception("Error processing request")
        # Let the caller decide how and when to notify the user.
        raise
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
