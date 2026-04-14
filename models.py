import sqlite3

DB_PATH = "users.db" # Database name used in your app

def get_db_connection():
    """Establishes and returns a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_query(query, args=(), fetchall=False, fetchone=False, commit=False):
    """Helper function to execute a database query."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(query, args)
    
    result = None
    if fetchall:
        result = cursor.fetchall()
    elif fetchone:
        result = cursor.fetchone()
        
    if commit:
        conn.commit()
        
    conn.close()
    return result

def init_db():
    """Initializes the database with the required tables."""
    queries = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            place TEXT NOT NULL,
            FOREIGN KEY(username) REFERENCES users(username)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS feedbacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            place TEXT NOT NULL,
            rating REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(username) REFERENCES users(username)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            place TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(username) REFERENCES users(username)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS recommendations_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            place TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(username) REFERENCES users(username)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS metrics_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            precision_k REAL,
            recall_k REAL,
            f1 REAL,
            avg_cos_sim REAL,
            response_time REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            place TEXT NOT NULL,
            rating INTEGER,
            comment TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(username) REFERENCES users(username)
        )
        """
    ]
    
    for query in queries:
        execute_query(query, commit=True)
        
    print("Database built successfully with the updated schema.")

def save_favorite(username, place):
    """Saves a place as a favorite and implicitly adds a 5-star rating."""
    # Check if favorite already exists
    existing = execute_query(
        "SELECT id FROM favorites WHERE username = ? AND place = ?", 
        (username, place), 
        fetchone=True
    )
    if not existing:
        execute_query(
            "INSERT INTO favorites (username, place) VALUES (?, ?)", 
            (username, place), 
            commit=True
        )
        # Implicitly save a 5-star rating when favorited
        save_rating(username, place, 5.0)
    return True

def save_rating(username, place, rating):
    """Saves or updates a user's rating for a specific place."""
    # Check if a rating already exists
    existing = execute_query(
        "SELECT id FROM feedbacks WHERE username = ? AND place = ?", 
        (username, place), 
        fetchone=True
    )
    if existing:
        execute_query(
            "UPDATE feedbacks SET rating = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?", 
            (rating, existing['id']), 
            commit=True
        )
    else:
        execute_query(
            "INSERT INTO feedbacks (username, place, rating) VALUES (?, ?, ?)", 
            (username, place, rating), 
            commit=True
        )
    return True

def log_click(username, place):
    """Logs when a user clicks on a particular place."""
    execute_query(
        "INSERT INTO clicks (username, place) VALUES (?, ?)", 
        (username, place), 
        commit=True
    )
    return True

def log_recommendation(username, place):
    """Logs when a place is recommended to a user."""
    execute_query(
        "INSERT INTO recommendations_log (username, place) VALUES (?, ?)", 
        (username, place), 
        commit=True
    )
    return True

if __name__ == "__main__":
    init_db()
