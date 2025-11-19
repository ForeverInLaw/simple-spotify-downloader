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

            artists = track_info.get('artists', [])
            album_info = track_info.get('album', {})
            images = album_info.get('images', []) if isinstance(album_info, dict) else []

            first_artist = artists[0] if artists else {}
            artist_name = (
                first_artist.get('name')
                if isinstance(first_artist, dict)
                else first_artist
            )

            first_image = images[0] if images else {}
            image_url = (
                first_image.get('url')
                if isinstance(first_image, dict)
                else first_image
            ) or None

            return {
                'id': track_info['id'],
                'name': track_info['name'],
                'artist': artist_name or 'Unknown Artist',
                'album': album_info.get('name') if isinstance(album_info, dict) else None,
                'image_url': image_url
            }
        except Exception as e:
            logging.exception(f"Error fetching Spotify track info: {e}")
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
