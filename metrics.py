import time
from functools import wraps
from models import execute_query


def get_relevant_places(username):
    """
    Fetch relevant places (favorites + highly rated feedbacks) for a user.
    Used as ground-truth for Precision/Recall metrics.
    FIX: query feedbacks by username only (was inconsistent with recommender schema).
    """
    # Use 'place' column — consistent with the rest of the codebase
    feedbacks = execute_query(
        "SELECT place FROM feedbacks WHERE username = ? AND rating >= 4",
        (username,), fetchall=True
    )
    favorites = execute_query(
        "SELECT place FROM favorites WHERE username = ?",
        (username,), fetchall=True
    )

    relevant = set()
    if feedbacks:
        relevant.update([f['place'] for f in feedbacks if f['place']])
    if favorites:
        relevant.update([f['place'] for f in favorites if f['place']])

    return relevant


def calculate_precision_k(recommended_places, relevant_places, k=10):
    """Precision@K: fraction of top-K recommendations that are relevant."""
    k_recs = recommended_places[:k]
    if not k_recs or not relevant_places:
        return 0.0
    rec_set = {p['place'] for p in k_recs if p.get('place')}
    hits = len(rec_set & relevant_places)
    return hits / len(k_recs)


def calculate_recall_k(recommended_places, relevant_places, k=10):
    """Recall@K: fraction of all relevant places captured in top-K."""
    k_recs = recommended_places[:k]
    # FIX: return 0 cleanly when no relevant places exist (avoids division by zero)
    if not k_recs or not relevant_places:
        return 0.0
    rec_set = {p['place'] for p in k_recs if p.get('place')}
    hits = len(rec_set & relevant_places)
    return hits / len(relevant_places)


def calculate_f1(precision, recall):
    """Harmonic mean of precision and recall."""
    if precision + recall == 0:
        return 0.0
    return 2 * (precision * recall) / (precision + recall)


def log_metrics(precision, recall, f1, avg_cos_sim, response_time):
    """Save calculated metrics to the database."""
    execute_query(
        """
        INSERT INTO metrics_log (precision_k, recall_k, f1, avg_cos_sim, response_time)
        VALUES (?, ?, ?, ?, ?)
        """,
        (precision, recall, f1, avg_cos_sim, response_time),
        commit=True
    )
    return True


def measure_response_time(func):
    """Decorator to automatically measure and log a function's response time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed_ms = (time.time() - start) * 1000
        execute_query(
            "INSERT INTO metrics_log (response_time) VALUES (?)",
            (elapsed_ms,), commit=True
        )
        return result
    return wrapper
