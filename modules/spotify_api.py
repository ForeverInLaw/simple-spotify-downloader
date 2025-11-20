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

    @staticmethod
    def _extract_artist_name(artists: list | None) -> str:
        if not artists:
            return 'Unknown Artist'

        first_artist = artists[0]
        if isinstance(first_artist, dict):
            return first_artist.get('name') or 'Unknown Artist'
        return first_artist or 'Unknown Artist'

    @staticmethod
    def _extract_image_url(images: list | None) -> str | None:
        if not images:
            return None

        first_image = images[0]
        if isinstance(first_image, dict):
            return first_image.get('url') or None
        return first_image or None

    @classmethod
    def _extract_album_metadata(cls, album_info: dict | None) -> tuple[str | None, str | None]:
        if not isinstance(album_info, dict):
            return None, None

        album_name = album_info.get('name')
        images = album_info.get('images')
        image_url = cls._extract_image_url(images if isinstance(images, list) else None)
        return album_name, image_url

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

            artist_name = self._extract_artist_name(track_info.get('artists'))
            album_name, image_url = self._extract_album_metadata(track_info.get('album'))

            return {
                'id': track_info['id'],
                'name': track_info['name'],
                'artist': artist_name,
                'album': album_name,
                'image_url': image_url
            }
        except Exception:
            logging.exception("Error fetching Spotify track info for track_id=%s", track_id)
            raise

    @staticmethod
    def is_spotify_link(text: str) -> bool:
        """
        Determines whether a string contains a Spotify track, playlist, or album URL/URI.
        
        Returns:
            true if the text contains a Spotify track, playlist, or album ID, false otherwise.
        """
        return (SpotifyClient.extract_track_id(text) is not None) or \
               (SpotifyClient.extract_playlist_id(text) is not None) or \
               (SpotifyClient.extract_album_id(text) is not None)

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

    @staticmethod
    def extract_playlist_id(text: str) -> str | None:
        """
        Extract the Spotify playlist ID from a URL or URI.
        
        Parameters:
            text (str): A Spotify playlist URL or URI.
        
        Returns:
            playlist_id (str | None): The extracted playlist ID if present, otherwise `None`.
        """
        if not text:
            return None

        text = text.strip()

        if text.startswith('spotify:playlist:'):
            return text.split(':')[-1]

        # Remove query params
        cleaned = re.sub(r'\?.*$', '', text)
        match = re.search(
            r'open\.spotify\.com/(?:intl-[^/]+/)?playlist/([A-Za-z0-9]+)',
            cleaned,
        )
        if match:
            return match.group(1)
        return None

    @staticmethod
    def extract_album_id(text: str) -> str | None:
        """
        Extract the Spotify album ID from a URL or URI.
        
        Parameters:
            text (str): A Spotify album URL or URI.
        
        Returns:
            album_id (str | None): The extracted album ID if present, otherwise `None`.
        """
        if not text:
            return None

        text = text.strip()

        if text.startswith('spotify:album:'):
            return text.split(':')[-1]

        # Remove query params
        cleaned = re.sub(r'\?.*$', '', text)
        match = re.search(
            r'open\.spotify\.com/(?:intl-[^/]+/)?album/([A-Za-z0-9]+)',
            cleaned,
        )
        if match:
            return match.group(1)
        return None

    def get_playlist_info(self, playlist_id: str) -> dict:
        """
        Retrieve basic metadata for a Spotify playlist.
        
        Parameters:
            playlist_id (str): Spotify playlist ID.
            
        Returns:
            dict: Dictionary with playlist metadata (id, name, owner, total_tracks).
        """
        try:
            playlist = self.sp.playlist(playlist_id, fields="id,name,owner.display_name,tracks.total")
            return {
                'id': playlist['id'],
                'name': playlist['name'],
                'owner': playlist['owner']['display_name'],
                'total_tracks': playlist['tracks']['total']
            }
        except Exception:
            logging.exception("Error fetching Spotify playlist info for playlist_id=%s", playlist_id)
            raise

    def get_playlist_tracks(self, playlist_id: str) -> list[dict]:
        """
        Retrieve all tracks from a Spotify playlist.
        
        Parameters:
            playlist_id (str): Spotify playlist ID.
            
        Returns:
            list[dict]: List of dictionaries, each containing track metadata (id, name, artist, album, image_url).
        """
        tracks_metadata = []
        try:
            results = self.sp.playlist_items(playlist_id)
            
            while results:
                for item in results['items']:
                    track = item.get('track')
                    # Skip items without a valid track or track ID (e.g., local tracks/podcasts)
                    if not track or not track.get('id'):
                        continue
                        
                    # Extract same metadata as get_track_info
                    artist_name = self._extract_artist_name(track.get('artists'))
                    album_name, image_url = self._extract_album_metadata(track.get('album'))
                    
                    tracks_metadata.append({
                        'id': track['id'],
                        'name': track.get('name', 'Unknown Title'),
                        'artist': artist_name,
                        'album': album_name,
                        'image_url': image_url
                    })
                
                if results['next']:
                    results = self.sp.next(results)
                else:
                    break
                    
            return tracks_metadata
        except Exception:
            logging.exception("Error fetching Spotify playlist tracks for playlist_id=%s", playlist_id)
            raise

    def get_album_info(self, album_id: str) -> dict:
        """
        Retrieve basic metadata for a Spotify album.
        
        Parameters:
            album_id (str): Spotify album ID.
            
        Returns:
            dict: Dictionary with album metadata (id, name, artist, image_url, total_tracks).
        """
        try:
            album = self.sp.album(album_id)
            
            artist_name = self._extract_artist_name(album.get('artists'))
            _, image_url = self._extract_album_metadata(album)

            return {
                'id': album['id'],
                'name': album['name'],
                'artist': artist_name,
                'image_url': image_url,
                'total_tracks': album['total_tracks']
            }
        except Exception:
            logging.exception("Error fetching Spotify album info for album_id=%s", album_id)
            raise

    def get_album_tracks(self, album_id: str, album_info: dict) -> list[dict]:
        """
        Retrieve all tracks from a Spotify album.
        
        Parameters:
            album_id (str): Spotify album ID.
            album_info (dict): Album metadata (must contain 'name' and 'image_url') to inject into track data.
            
        Returns:
            list[dict]: List of dictionaries, each containing track metadata.
        """
        tracks_metadata = []
        try:
            results = self.sp.album_tracks(album_id)
            
            while results:
                for track in results['items']:
                    if not track or not track.get('id'):
                        continue
                        
                    artist_name = self._extract_artist_name(track.get('artists'))

                    # Album tracks don't have album/image info, so we use the passed album_info
                    tracks_metadata.append({
                        'id': track['id'],
                        'name': track.get('name', 'Unknown Title'),
                        'artist': artist_name,
                        'album': album_info.get('name'),
                        'image_url': album_info.get('image_url')
                    })
                
                if results['next']:
                    results = self.sp.next(results)
                else:
                    break
                    
            return tracks_metadata
        except Exception:
            logging.exception("Error fetching Spotify album tracks for album_id=%s", album_id)
            raise