import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "voicebox_local.db"

def get_db_connection():
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # Profiles table
    c.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            prompt_path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # History table
    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            text TEXT NOT NULL,
            language TEXT NOT NULL,
            instruct TEXT,
            audio_path TEXT NOT NULL,
            duration REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (profile_id) REFERENCES profiles (id)
        )
    ''')
    # Base logic: Try creating fields if they don't exist
    try:
        c.execute("ALTER TABLE profiles ADD COLUMN owner TEXT DEFAULT 'amorwest'")
        c.execute("ALTER TABLE profiles ADD COLUMN is_default BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Columns already exist
        
    try:
        c.execute("ALTER TABLE history ADD COLUMN username TEXT DEFAULT 'amorwest'")
    except sqlite3.OperationalError:
        pass 
        
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'regular',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS hidden_profiles (
            username TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            hidden_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, profile_id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()
