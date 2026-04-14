import warnings
from sklearn.exceptions import ConvergenceWarning

import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.neighbors import NearestNeighbors
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

# ------------------ CONTROLLERS ------------------
def clean_data(df):
    """Clean and strip dataframe columns and handle missing values."""
    df.columns = df.columns.str.strip()
    features = ['Type', 'Budget', 'Season', 'Interest']
    for col in features:
        if col in df.columns:
            df[col] = df[col].fillna('').astype(str).str.strip()
    return df

def get_user_profile(username, conn, places_df):
    """
    Extracts comprehensive user history from feedbacks, favorites, and history.
    Returns:
      past_places: set of place names the user interacted with positively.
      favorite_types: dictionary mapping a place 'Type' to its frequency/weight.
    """
    favorite_types = {}
    past_places = set()

    # 1. Past Ratings
    try:
        feedbacks = pd.read_sql(
            "SELECT place, rating FROM feedbacks WHERE username=?", conn, params=(username,)
        )
    except Exception:
        feedbacks = pd.DataFrame(columns=['place', 'rating'])

    if not feedbacks.empty:
        feedbacks['rating'] = pd.to_numeric(feedbacks['rating'], errors='coerce').fillna(0)
        good_feedbacks = feedbacks[feedbacks['rating'] >= 4.0]['place'].tolist()
        past_places.update(good_feedbacks)
        for place in good_feedbacks:
            p_type = places_df[places_df['Place'] == place]['Type'].values
            if len(p_type) > 0:
                favorite_types[p_type[0]] = favorite_types.get(p_type[0], 0) + 1

    # 2. User Favorites
    try:
        favorites = pd.read_sql(
            "SELECT place FROM favorites WHERE username=?", conn, params=(username,)
        )
    except Exception:
        favorites = pd.DataFrame(columns=['place'])

    if not favorites.empty:
        fav_list = favorites['place'].tolist()
        past_places.update(fav_list)
        for place in fav_list:
            p_type = places_df[places_df['Place'] == place]['Type'].values
            if len(p_type) > 0:
                favorite_types[p_type[0]] = favorite_types.get(p_type[0], 0) + 1.5

    # 3. User History
    try:
        history = pd.read_sql(
            "SELECT place, rating FROM history WHERE username=?", conn, params=(username,)
        )
        if not history.empty:
            history['rating'] = pd.to_numeric(history['rating'], errors='coerce').fillna(0)
            good_history = history[history['rating'] >= 4.0]['place'].tolist()
            past_places.update(good_history)
            for place in good_history:
                p_type = places_df[places_df['Place'] == place]['Type'].values
                if len(p_type) > 0:
                    favorite_types[p_type[0]] = favorite_types.get(p_type[0], 0) + 1
    except Exception:
        pass

    return past_places, favorite_types


# ------------------ CONTENT BASED WITH PERSONALIZATION ------------------
def content_based_recommendation(username, user_preferences, places_df, conn):
    """
    Generate content_score based on user preferences and historically favourite categories.
    """
    places_df = clean_data(places_df)

    def safe_repeat(val, n):
        v = str(val).strip()
        return (v + " ") * n if v else ""

    places_df['combined_features'] = places_df.apply(
        lambda r: (
            safe_repeat(r['Type'], 2) +
            safe_repeat(r['Budget'], 1) +
            safe_repeat(r['Season'], 1) +
            safe_repeat(r['Interest'], 2)
        ).strip(),
        axis=1
    )

    if places_df['combined_features'].str.strip().eq('').all():
        places_df['content_score'] = 0.0
        places_df['knn_score'] = 0.0
        places_df['cluster_score'] = 0.0
        places_df['cluster'] = 0
        return places_df, 0.0, {}

    cv = TfidfVectorizer()
    tfidf_matrix = cv.fit_transform(places_df['combined_features'])

    user_pref_str = (
        safe_repeat(user_preferences.get('type', ''), 5) +
        safe_repeat(user_preferences.get('budget', ''), 2) +
        safe_repeat(user_preferences.get('season', ''), 2) +
        safe_repeat(user_preferences.get('interest', ''), 3)
    ).strip()

    past_places, favorite_types = get_user_profile(username, conn, places_df)
    past_features = ""
    if past_places:
        past_rows = places_df[places_df['Place'].isin(past_places)]
        past_features = " ".join(past_rows['combined_features'].tolist())

    # Cap history multiplier to avoid drowning current search query
    history_count = len(past_places)
    dynamic_weight = min(max(1, history_count), 5)

    if user_pref_str:
        final_query_str = (user_pref_str + " ") * dynamic_weight + past_features
    else:
        final_query_str = past_features if past_features else "general"

    final_query_str = final_query_str.strip()

    try:
        user_vector = cv.transform([final_query_str])
    except Exception:
        user_vector = cv.transform(["general"])

    # KNN Step
    k_candidates = min(50, len(places_df))
    knn = NearestNeighbors(n_neighbors=k_candidates, metric='cosine')
    knn.fit(tfidf_matrix)
    distances, indices = knn.kneighbors(user_vector)

    candidate_indices = indices[0]
    places_df = places_df.iloc[candidate_indices].copy()
    places_df['knn_score'] = 1 - distances[0]

    candidate_tfidf = tfidf_matrix[candidate_indices]
    base_similarity = cosine_similarity(user_vector, candidate_tfidf)[0]

    min_sim, max_sim = base_similarity.min(), base_similarity.max()
    if max_sim > min_sim:
        base_similarity = (base_similarity - min_sim) / (max_sim - min_sim)
    elif max_sim > 0:
        base_similarity = base_similarity / max_sim
    else:
        base_similarity = np.zeros_like(base_similarity)

    places_df['content_score'] = base_similarity

    # CLUSTERING — convert sparse to dense before silhouette_score
    candidate_tfidf_dense = candidate_tfidf.toarray()
    best_labels = None
    best_score = -1
    best_kmeans = None

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ConvergenceWarning)
        if len(places_df) >= 4:
            for k in range(4, min(7, len(places_df))):
                kmeans = KMeans(n_clusters=k, random_state=42, n_init='auto')
                labels = kmeans.fit_predict(candidate_tfidf_dense)
                try:
                    score = silhouette_score(candidate_tfidf_dense, labels)
                    if score > best_score:
                        best_score = score
                        best_labels = labels
                        best_kmeans = kmeans
                except Exception:
                    pass

        user_vector_dense = user_vector.toarray()
        if best_labels is not None:
            places_df['cluster'] = best_labels
            user_cluster = best_kmeans.predict(user_vector_dense)[0]
            places_df['cluster_score'] = (places_df['cluster'] == user_cluster).astype(float)
        elif len(places_df) > 1:
            kmeans = KMeans(n_clusters=min(5, len(places_df)), random_state=42, n_init='auto')
            places_df['cluster'] = kmeans.fit_predict(candidate_tfidf_dense)
            user_cluster = kmeans.predict(user_vector_dense)[0]
            places_df['cluster_score'] = (places_df['cluster'] == user_cluster).astype(float)
        else:
            places_df['cluster'] = 0
            places_df['cluster_score'] = 1.0

    # PERSONALIZATION — vectorised (avoid slow iterrows mutation)
    if favorite_types:
        max_weight = max(favorite_types.values())
        boost_map = {t: (w / max_weight) * 0.25 for t, w in favorite_types.items()}
        places_df['_boost'] = places_df['Type'].map(boost_map).fillna(0)
        places_df['content_score'] = (
            places_df['content_score'] + places_df['content_score'] * places_df['_boost']
        ).clip(upper=1.0)
        places_df.drop(columns=['_boost'], inplace=True)
    else:
        places_df['content_score'] = places_df['content_score'].clip(upper=1.0)

    avg_sim = float(np.mean(base_similarity))
    return places_df, avg_sim, favorite_types


# ------------------ COLLABORATIVE ------------------
def collaborative_filtering(username, conn):
    """
    Generate collab_score based on similar users' feedbacks.
    """
    try:
        fav_df = pd.read_sql("SELECT username, place, rating FROM feedbacks", conn)
    except Exception:
        return {}

    if fav_df.empty:
        return {}

    # Use aggfunc='mean' to handle duplicate (user, place) pairs without crashing
    user_item = fav_df.pivot_table(
        index='username', columns='place', values='rating',
        aggfunc='mean', fill_value=0
    )

    if username not in user_item.index:
        return {}

    user_sim = cosine_similarity(user_item)
    user_sim_df = pd.DataFrame(user_sim, index=user_item.index, columns=user_item.index)

    similar_users = user_sim_df[username].drop(labels=[username], errors='ignore')
    similar_users = similar_users[similar_users > 0].nlargest(5).index

    recommended_places = {}
    user_rated = set(user_item.columns[user_item.loc[username] > 0])

    for sim_user in similar_users:
        weight = user_sim_df.at[username, sim_user]
        sim_user_ratings = user_item.loc[sim_user]
        for place, rating in sim_user_ratings.items():
            if rating > 0 and place not in user_rated:
                recommended_places[place] = recommended_places.get(place, 0) + (rating * weight)

    return recommended_places


# ------------------ HYBRID & DIVERSITY ------------------
def apply_diversity(sorted_df, top_n=10, max_per_type=2):
    """
    Ensures that out of top_n results, no single 'Type' exceeds max_per_type.
    """
    diverse_list = []
    type_counts = {}
    seen_places = set()

    for _, row in sorted_df.iterrows():
        p_type = row['Type']
        p_name = row['Place']
        if type_counts.get(p_type, 0) < max_per_type and p_name not in seen_places:
            diverse_list.append(row)
            type_counts[p_type] = type_counts.get(p_type, 0) + 1
            seen_places.add(p_name)
        if len(diverse_list) == top_n:
            break

    # Fallback backfill
    if len(diverse_list) < top_n:
        for _, row in sorted_df.iterrows():
            if len(diverse_list) == top_n:
                break
            p_name = row['Place']
            if p_name not in seen_places:
                p_type = row['Type']
                if type_counts.get(p_type, 0) < 5:
                    diverse_list.append(row)
                    type_counts[p_type] = type_counts.get(p_type, 0) + 1
                    seen_places.add(p_name)

    return pd.DataFrame(diverse_list)


def _safe_normalize(series):
    """Min-max normalise; returns zeros if no range."""
    mn, mx = series.min(), series.max()
    if mx > mn:
        return (series - mn) / (mx - mn)
    elif mx > 0:
        return series / mx
    return pd.Series(np.zeros(len(series)), index=series.index)


def hybrid_recommendation(username, user_preferences, places_df, conn):
    """
    Combine content-based, collaborative, rating, and popularity scores.
    """
    places_df['tmp_rating'] = pd.to_numeric(places_df['Rating'], errors='coerce').fillna(0)
    places_df = places_df[places_df['tmp_rating'] >= 3.5].copy()
    places_df.drop(columns=['tmp_rating'], inplace=True, errors='ignore')

    if places_df.empty:
        return pd.DataFrame(columns=['Place', 'place', 'Rating', 'rating', 'Approx_Cost',
                                     'cost', 'final_score', 'match_score', 'explanation']), 0.0

    # 1. Content & Personalization
    places_df, avg_sim, favorite_types = content_based_recommendation(
        username, user_preferences, places_df, conn
    )

    # 2. Collaborative Filtering
    collab_scores_map = collaborative_filtering(username, conn)
    places_df['collab_score'] = places_df['Place'].map(collab_scores_map).fillna(0)

    # 3. Rating and Popularity
    places_df['rating_score'] = pd.to_numeric(places_df['Rating'], errors='coerce').fillna(0) / 5.0

    try:
        fav_df = pd.read_sql(
            "SELECT place, COUNT(*) as count FROM favorites GROUP BY place", conn
        )
        pop_map = dict(zip(fav_df['place'], fav_df['count']))
        places_df['popularity_score'] = places_df['Place'].map(pop_map).fillna(0)
    except Exception:
        places_df['popularity_score'] = 0.0

    # Normalise all scores consistently
    places_df['collab_score']     = _safe_normalize(places_df['collab_score'])
    places_df['content_score']    = _safe_normalize(places_df['content_score'])
    places_df['rating_score']     = _safe_normalize(places_df['rating_score'])
    places_df['popularity_score'] = _safe_normalize(places_df['popularity_score'])
    places_df['knn_score']        = _safe_normalize(places_df['knn_score'])

    # 4. Weight selection
    has_collab = places_df['collab_score'].max() > 0
    if not has_collab:
        w_content, w_collab, w_knn, w_rating, w_pop = 0.60, 0.00, 0.20, 0.10, 0.10
    else:
        w_content, w_collab, w_knn, w_rating, w_pop = 0.35, 0.25, 0.20, 0.10, 0.10

    places_df['final_score'] = (
        w_content * places_df['content_score'] +
        w_collab  * places_df['collab_score'] +
        w_knn     * places_df['knn_score'] +
        w_rating  * places_df['rating_score'] +
        w_pop     * places_df['popularity_score']
    )

    # Exact match boost — vectorised for performance
    pref_type     = str(user_preferences.get('type', '')).strip().lower()
    pref_budget   = str(user_preferences.get('budget', '')).strip().lower()
    pref_season   = str(user_preferences.get('season', '')).strip().lower()
    pref_interest = str(user_preferences.get('interest', '')).strip().lower()

    places_df['final_score'] += (
        (places_df['Type'].str.strip().str.lower() == pref_type).astype(float)     * 0.60 +
        (places_df['Budget'].str.strip().str.lower() == pref_budget).astype(float) * 0.25 +
        (places_df['Season'].str.strip().str.lower().isin([pref_season, 'all'])).astype(float) * 0.20 +
        (places_df['Interest'].str.strip().str.lower() == pref_interest).astype(float) * 0.25
    )

    sorted_df = places_df.sort_values(by='final_score', ascending=False)

    # 5. Diversity limit
    top_recommendations = apply_diversity(sorted_df, top_n=10, max_per_type=2).copy()
    top_recommendations = top_recommendations.sort_values(by='final_score', ascending=False)

    top_recommendations['place']  = top_recommendations['Place']
    top_recommendations['rating'] = top_recommendations['Rating']
    top_recommendations['cost']   = top_recommendations['Approx_Cost']

    # Cap match_score at 100
    top_recommendations['match_score'] = (
        top_recommendations['final_score'] * 100
    ).clip(upper=100).round(1)

    # Explainability
    explanations = []
    for _, row in top_recommendations.iterrows():
        matches = []
        if str(row.get('Type', '')).strip().lower() == pref_type and pref_type:
            matches.append("destination type")
        if str(row.get('Budget', '')).strip().lower() == pref_budget and pref_budget:
            matches.append("budget")
        if str(row.get('Season', '')).strip().lower() in [pref_season, 'all'] and pref_season:
            matches.append("season")
        if str(row.get('Interest', '')).strip().lower() == pref_interest and pref_interest:
            matches.append("interest")

        if matches:
            if len(matches) > 1:
                matches_str = ", ".join(matches[:-1]) + ", and " + matches[-1]
            else:
                matches_str = matches[0]
            explanations.append("Recommended because it matches your " + matches_str + " preferences")
        elif str(row.get('Type', '')).strip() in favorite_types:
            explanations.append("Because you liked similar places")
        elif row.get('collab_score', 0) > 0.5:
            explanations.append("Highly recommended by similar travellers")
        elif row.get('cluster_score', 0) == 1.0:
            explanations.append("Fits your general travel profile")
        else:
            explanations.append("A popular choice you might like")

    top_recommendations['explanation'] = explanations

    return top_recommendations, avg_sim
