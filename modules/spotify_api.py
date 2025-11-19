import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
import logging

class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str):
        self.sp = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=client_id, 
                client_secret=client_secret
            )
        )

    def get_track_info(self, track_id: str) -> dict:
        """Fetches track information from Spotify by track ID."""
        try:
            track_info = self.sp.track(track_id)

            return {
                'id': track_info['id'],
                'name': track_info['name'],
                'artist': track_info['artists'][0]['name'],
                'album': track_info['album']['name'],
                'image_url': track_info['album']['images'][0]['url']
            }
        except Exception as e:
            logging.error(f"Error fetching Spotify track info: {e}")
            raise

    @staticmethod
    def is_spotify_link(text: str) -> bool:
        return SpotifyClient.extract_track_id(text) is not None

    @staticmethod
    def extract_track_id(text: str) -> str | None:
        """Extracts track ID from a Spotify URL or URI."""
        if not text:
            return None

        text = text.strip()

        if text.startswith('spotify:track:'):
            return text.split(':')[-1]

        # Remove query params
        cleaned = re.sub(r'\?.*$', '', text)
        match = re.search(r'open\.spotify\.com/track/([A-Za-z0-9]+)', cleaned)
        if match:
            return match.group(1)
        return None
