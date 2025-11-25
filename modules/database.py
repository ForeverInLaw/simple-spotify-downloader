import sqlite3
import logging
from pathlib import Path

DB_NAME = Path('data/users.db')

def init_db():
    """
    Create the application's SQLite database file and ensure required tables exist.
    
    Creates two tables when missing:
    - users: user_id (INTEGER PRIMARY KEY), username, first_name, last_name.
    - tracks: track_id (TEXT PRIMARY KEY), name (NOT NULL), artist (NOT NULL), album, image_url, created_at (defaults to CURRENT_TIMESTAMP).
    
    If a sqlite3.Error occurs, an error is logged and the function returns without raising.
    """
    try:
        DB_NAME.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, 
                    username TEXT, 
                    first_name TEXT, 
                    last_name TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tracks (
                    track_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    album TEXT,
                    image_url TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
    except sqlite3.Error:
        logging.exception("Database initialization error")
        raise

def add_user(user_id: int, username: str, first_name: str, last_name: str):
    """
    Upserts a user record into the database's users table.
    
    Parameters:
        user_id (int): The user's unique identifier.
        username (str): The user's username.
        first_name (str): The user's first name.
        last_name (str): The user's last name.
    
    Notes:
        Database errors are logged and not propagated.
    """
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO users(user_id, username, first_name, last_name) VALUES(?,?,?,?)', 
                (user_id, username, first_name, last_name)
            )
            conn.commit()
            logging.info(f"User updated: {username} ({user_id})")
    except sqlite3.Error:
        logging.exception("Error adding user %s", user_id)


def upsert_track(track_info: dict):
    """
    Cache track metadata for later retrieval.
    
    Parameters:
        track_info (dict): Track data with required keys `id`, `name`, and `artist`; optional keys `album` and `image_url`.
    """
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR REPLACE INTO tracks(track_id, name, artist, album, image_url)
                VALUES(?,?,?,?,?)
                ''',
                (
                    track_info['id'],
                    track_info['name'],
                    track_info['artist'],
                    track_info.get('album'),
                    track_info.get('image_url')
                )
            )
            conn.commit()
    except sqlite3.Error:
        logging.exception("Error caching track %s", track_info.get('id'))


def get_track(track_id: str):
    """
    Retrieve cached metadata for a track by its ID.
    
    Returns:
        dict: A mapping with keys `id`, `name`, `artist`, `album`, and `image_url` when the track is found.
        None: If the track is not present in the cache or a database error occurs.
    """
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT track_id, name, artist, album, image_url FROM tracks WHERE track_id=?',
                (track_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                'id': row[0],
                'name': row[1],
                'artist': row[2],
                'album': row[3],
                'image_url': row[4],
            }
    except sqlite3.Error:
        logging.exception("Error reading cached track %s", track_id)
        return None


def delete_track(track_id: str) -> None:
    """Removes cached metadata when audio file is deleted."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tracks WHERE track_id=?', (track_id,))
            conn.commit()
    except sqlite3.Error:
        logging.exception("Error deleting cached track %s", track_id)
