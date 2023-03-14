# Importing necessary modules and packages
import os                  # For interacting with the operating system
import logging             # For logging errors and information
import asyncio             # For asynchronous programming
import aiohttp             # For making asynchronous HTTP requests
import spotipy             # For interacting with the Spotify API
import pytube              # For downloading audio from YouTube videos
import re                  # For regular expressions
import requests            # For making HTTP requests
import sqlite3             # For working with SQLite databases

# Importing necessary classes and functions from the aiogram package
from spotipy.oauth2 import SpotifyClientCredentials
from aiogram import Bot, Dispatcher, types
from aiogram.types.message import ContentType
from aiogram.utils import exceptions
from aiogram.types import InputFile


# Importing necessary credentials from the creds module
from creds import api as API_TOKEN                        # API_TOKEN of Telegram bot (@botfather)
from creds import client_id as SPOTIPY_CLIENT_ID          # Spotify Client ID for authentication
from creds import client_secret as SPOTIPY_CLIENT_SECRET  # Spotify Client Secret for authentication
from creds import botusername as BOT_USERNAME             # Unnecessary shit in console
from creds import bot_visible as BOT_NAME                 # (2) Unnecessary shit in console
from creds import yt_api                                  # YouTube API key for accessing the YouTube API

# Initializing a logging system
logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(levelname)s - %(message)s',
	datefmt='%d-%b-%y %H:%M:%S',
	handlers=[
		logging.FileHandler('logs.txt', mode='a', encoding='utf-8'),
		logging.StreamHandler()
	]
)

# Bot initialization
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Spotipy initialization
client_credentials_manager = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# Database initialization
conn = sqlite3.connect('users.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT)''')
conn.commit()

# Check if a directory named "downloads" exists in the current working directory
if not os.path.exists('downloads'):
    # If the directory does not exist, create a new directory named "downloads" 
    # using the os.makedirs() function
    os.makedirs('downloads')


# Define an asynchronous function named "download_track" that takes a track URL as a parameter
async def download_track(track_url):
    # Create a YouTube object using the pytube library and the track URL
    video = pytube.YouTube(track_url)
    
    # Filter the available video streams to get the highest quality audio-only stream
    audio = video.streams.filter(only_audio=True).order_by('abr').last()
    
    # Get the title of the video and remove any forbidden characters from the file name
    track_title = video.title
    title = re.sub(r'[\\/*?;"<>|]', ' ', track_title)
    
    # Define the file path for the downloaded MP3 file
    mp3_file_path = f'{title}.mp3'
    
    # Download the audio stream as an MP3 file to the "downloads" directory
    audio.download(filename=f"downloads/{mp3_file_path}")
    # Return the file path of the downloaded MP3 file
    return mp3_file_path


# Taking a track name as a string parameter and returning a string
async def search_track_on_youtube(track_name: str) -> str:
  # Build a search query for the track name
	query = f"{track_name}"
	# Create a new client session using the aiohttp library
	async with aiohttp.ClientSession() as session:
		# Send an HTTP GET request to the YouTube Data API with the search query and API key
		async with session.get(f'https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&key={yt_api}&maxResults=1') as response:
			# Parse the JSON response from the YouTube Data API
			response_dict = await response.json()
			# Extract the video ID of the first search result
			video_id = response_dict['items'][0]['id']['videoId']
			# Return the URL of the first search result video on YouTube
			return f"https://www.youtube.com/watch?v={video_id}"

# Removing any query parameters from the Spotify url
def clean_spotify_url(url):
	pattern = r'\?.*$'
	return re.sub(pattern, '', url)

# Handler for "/start" command
@dp.message_handler(commands=['start'])
async def welcome(message):
		# Connect to the users database
    with sqlite3.connect('users.db') as conn:
        cursor = conn.cursor()
        
        # Get user information
        user_id = message.from_user.id
        username = message.from_user.username
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name

				# Print user information to console
        print(f"User: {username} ({user_id}), {first_name} {last_name}")

				# Insert or replace user information into the users table
        cursor.execute('INSERT OR REPLACE INTO users(user_id, username, first_name, last_name) VALUES(?,?,?,?)', (user_id, username, first_name, last_name))
        conn.commit()
        
		# Send welcome message to user
    await bot.send_message(message.chat.id,
			f"Приветик, *{message.from_user.first_name}* ! \n Просто пришли сюда ссылку на трек в Spotify!", parse_mode='Markdown')

# Define a function to process a user message with a Spotify track link
@dp.message_handler(content_types=ContentType.TEXT)
async def process_track_link(message: types.Message):
  # If the user message contains a link to Spotify
	if re.match(r'http(s)?://open.spotify.com/', message.text):
		# Get the Spotify URL from the user message and clean it up
		spotify_track_url = clean_spotify_url(message.text)

		# Get information about the track from the Spotify API
		track_id = spotify_track_url.split('/')[-1]
		track_info = sp.track(track_id)
		track_name = track_info['name']
		artist_name = track_info['artists'][0]['name']
		image_url = track_info['album']['images'][0]['url']
		response = requests.get(image_url)
		# Save the album cover image to a file
		with open('downloads/cover.jpg', 'wb') as f:
			f.write(response.content)
		thumb = InputFile('downloads/cover.jpg')
  
		# Find the track on YouTube and download it
		youtube_track_url = await search_track_on_youtube(f"{track_name} {artist_name}")
		mp3_file_path = await download_track(youtube_track_url)
		# Send the file to the user as an audio message
		try:
			with open(f"downloads/{mp3_file_path}", 'rb') as audio_file:
				await message.answer_audio(audio=audio_file, title=track_name, performer=artist_name, thumb=thumb, disable_notification=True)
    
    # Handle exceptions that may occur
		except exceptions.CantParseEntities or exceptions.CantParseUrl:
			await message.answer('Не удалось обработать аудиофайл. Свяжитесь с @nevermorelove')
		except Exception as e:
			await message.answer(f"Произошла ошибка {e}. Свяжитесь с @nevermorelove")

  # If the user message does not contain a link to Spotify
	else:
		# Log the message for debugging purposes
		logging.info(f"{message.date} - {message.chat.id} - {message.chat.username} - {message.text}")
  
'''
Maybe i should use it for saving space but i wont
	# removing temp files
	os.remove(f"downloads/{mp3_file_path}")
	os.remove(downloads/cover.jpg)
'''

# Is it necessary to comment THIS code?
if __name__ == '__main__':
	logging.info(f"Starting bot {BOT_NAME} @{BOT_USERNAME}....")
	asyncio.run(dp.start_polling())
