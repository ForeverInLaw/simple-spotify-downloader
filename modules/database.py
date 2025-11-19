import sqlite3
import logging

DB_NAME = 'users.db'

def init_db():
    """Initializes the database and ensures users and tracks tables exist."""
    try:
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

def add_user(user_id: int, username: str, first_name: str, last_name: str):
    """Adds or updates a user in the database."""
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
    """Caches track metadata for reuse."""
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
    """Returns cached track metadata if available."""
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
