import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
import logging

class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str):
        """
        Initialize the SpotifyClient and configure a Spotipy client instance stored on self.sp.
        
        Parameters:
            client_id (str): Spotify API client ID used to authenticate requests.
            client_secret (str): Spotify API client secret used to authenticate requests.
        """
        self.sp = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=client_id, 
                client_secret=client_secret
            )
        )

    def get_track_info(self, track_id: str) -> dict:
        """
        Retrieve metadata for a Spotify track given its track ID.
        
        Parameters:
            track_id (str): Spotify track ID.
        
        Returns:
            dict: Dictionary with track metadata containing keys:
                - 'id': track's Spotify ID
                - 'name': track title
                - 'artist': first artist's name
                - 'album': album name
                - 'image_url': URL of the album artwork
        """
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
        except Exception:
            logging.exception("Error fetching Spotify track info for track_id=%s", track_id)
            raise

    @staticmethod
    def is_spotify_link(text: str) -> bool:
        """
        Determines whether a string contains a Spotify track URL or URI.
        
        Returns:
            true if the text contains a Spotify track ID, false otherwise.
        """
        return SpotifyClient.extract_track_id(text) is not None

    @staticmethod
    def extract_track_id(text: str) -> str | None:
        """
        Extract the Spotify track ID from a URL or URI.
        
        Parameters:
            text (str): A Spotify track URL or URI (e.g., "spotify:track:<id>" or "https://open.spotify.com/track/<id>" possibly with query parameters).
        
        Returns:
            track_id (str | None): The extracted track ID if present, otherwise `None`.
        """
        if not text:
            return None

        text = text.strip()

        if text.startswith('spotify:track:'):
            return text.split(':')[-1]

        # Remove query params
        cleaned = re.sub(r'\?.*$', '', text)
        match = re.search(
            r'open\.spotify\.com/(?:intl-[^/]+/)?track/([A-Za-z0-9]+)',
            cleaned,
        )
        if match:
            return match.group(1)
        return None