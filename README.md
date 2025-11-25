# Simple Spotify Downloader

Telegram bot that converts Spotify track links into MP3 files by resolving track metadata through Spotify's API, looking up a matching YouTube audio source via yt-dlp, and sending the processed audio back to the requester. Built with **aiogram**, **spotipy**, and **yt-dlp**.

## Features

- Accepts direct Spotify track links or URIs
- Caches Spotify metadata and downloaded audio to minimize repeat lookups
- Downloads album artwork and attaches it as the Telegram audio thumbnail
- Uses yt-dlp with the configured JavaScript runtime for reliable YouTube extraction

## Requirements

- Python 3.11+
- Deno/Bun/Node/QuickJS (or another JS runtime supported by yt-dlp) — configured in `yt-dlp.conf`
- FFmpeg available on PATH for audio post-processing

> 💡 Install FFmpeg via your package manager (e.g., `winget install ffmpeg`, `brew install ffmpeg`, `apt install ffmpeg`) or download the binaries from [ffmpeg.org](https://ffmpeg.org/download.html). Ensure the `ffmpeg` executable is on `PATH`:
> ```bash
> ffmpeg -version
> ```
> Successful output indicates the bot will be able to run yt-dlp/FFmpeg post-processing.

## Setup

1. **Install FFmpeg & dependencies**
   ```bash
   ffmpeg -version   # confirm installed and on PATH
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure credentials**
   Copy `.env.example` to `.env` and fill in your values:
   ```ini
   TELEGRAM_API_TOKEN=<telegram_bot_token>
   SPOTIFY_CLIENT_ID=<spotify_client_id>
   SPOTIFY_CLIENT_SECRET=<spotify_client_secret>
   STORAGE_LIMIT_MB=500  # optional; omit or leave empty for unlimited cache
   ```
   Environment variables are loaded automatically via `python-dotenv` when `spotify-bot.py` starts.

3. **Enable yt-dlp JS runtime**
   Ensure `yt-dlp.conf` contains:
   ```conf
   --js-runtimes deno
   ```
   Adjust the runtime or path if you prefer Node/Bun/QuickJS.

4. **Run database migrations**
   The bot initializes SQLite tables automatically on first run. No manual steps required.

## Usage

```bash
python spotify-bot.py
```

Send a Spotify track URL (for example, `https://open.spotify.com/track/<id>`) to the Telegram bot. The bot responds with the MP3 file once the download or cache lookup finishes.

## Usage with Docker

To run the bot using Docker, follow these steps:

1. **Install Docker and Docker Compose.**
2. **Configure your credentials** in the `.env` file, including `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. You can obtain these from [my.telegram.org](https://my.telegram.org) under "API development tools".
3. **Run the bot** using Docker Compose:
   ```bash
   docker-compose up -d
   ```
   This will build the bot's Docker image and start both the bot and the local Telegram Bot API server. The server increases the file upload limit to 2GB.

## Project Structure

```text
modules/
  database.py      # SQLite helpers for users and track cache
  downloader.py    # yt-dlp search/download helpers
  spotify_api.py   # Spotify metadata client
spotify-bot.py     # aiogram entry point
yt-dlp.conf        # yt-dlp runtime configuration
```

## Roadmap

1. Playlist downloads
2. Text-based song search (without Spotify links)
3. Docker support

## License

MIT
