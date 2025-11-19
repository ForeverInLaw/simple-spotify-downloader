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
        match = re.search(r'open\.spotify\.com/track/([A-Za-z0-9]+)', cleaned)
        if match:
            return match.group(1)
        return None