from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file
import pandas as pd
import sqlite3
import math
import requests
import traceback
import time
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

from model.recommender import hybrid_recommendation
from models import execute_query, save_favorite as db_save_favorite, save_rating as db_save_rating, log_click, log_recommendation
from metrics import get_relevant_places, calculate_precision_k, calculate_recall_k, calculate_f1, log_metrics

recommend_bp = Blueprint('recommend_bp', __name__)

# ---------------- HELPERS ----------------
FALLBACK_COORDS = {
    "Mumbai": {"lat": 19.0760, "lon": 72.8777},
    "Pune": {"lat": 18.5204, "lon": 73.8567},
    "Mahabaleshwar": {"lat": 17.9307, "lon": 73.6477},
    "Lonavala": {"lat": 18.7481, "lon": 73.4072},
    "Nashik": {"lat": 20.0110, "lon": 73.7903},
    "Aurangabad": {"lat": 19.8762, "lon": 75.3433},
    "Alibaug": {"lat": 18.6414, "lon": 72.8722},
    "Shirdi": {"lat": 19.7648, "lon": 74.4762},
    "Ajanta Caves": {"lat": 20.5519, "lon": 75.7033},
    "Ellora Caves": {"lat": 20.0258, "lon": 75.1780},
    "Marine Drive": {"lat": 18.9440, "lon": 72.8225},
    "Juhu Beach": {"lat": 19.1009, "lon": 72.8260},
}

def get_weather(lat, lon):
    import os
    API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
    if not API_KEY:
        return None
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}&units=metric"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return {
                "temperature": data["main"]["temp"],
                "description": data["weather"][0]["description"].title(),
                "humidity": data["main"]["humidity"],
                "wind_speed": data["wind"]["speed"]
            }
    except:
        pass
    return None

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in KM
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def optimize_route(places):
    if not places: return places
    optimized = []; remaining = places.copy()
    current = remaining.pop(0)
    optimized.append(current)
    while remaining:
        nearest = min(remaining, key=lambda x: calculate_distance(
            float(current["Latitude"]), float(current["Longitude"]),
            float(x["Latitude"]), float(x["Longitude"])))
        optimized.append(nearest)
        remaining.remove(nearest)
        current = nearest
    return optimized

# ---------------- HOME / RECOMMEND ----------------
@recommend_bp.route("/home", methods=["GET", "POST"])
def home():
    if "user" not in session:
        return redirect(url_for("main_bp.login"))

    df = pd.read_csv("maharashtra_destinations.csv")
    df.columns = df.columns.str.strip()
    df['Image_URL'] = df['Image_URL'].astype(str).str.replace('\\', '/', regex=False).str.replace('/static/', '', regex=False)

    if 'Latitude' not in df.columns: df['Latitude'] = float('nan')
    if 'Longitude' not in df.columns: df['Longitude'] = float('nan')
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    
    for idx, row in df.iterrows():
        if pd.isna(row["Latitude"]) or pd.isna(row["Longitude"]):
            p_name = str(row.get("Place", "")).strip()
            for key, coords in FALLBACK_COORDS.items():
                if key.lower() in p_name.lower():
                    df.at[idx, "Latitude"] = coords["lat"]
                    df.at[idx, "Longitude"] = coords["lon"]
                    break

    recommendations = []
    
    if request.method == "POST":
        destination = request.form.get("type")
        budget = request.form.get("budget")
        season = request.form.get("season")
        interest = request.form.get("interest")
        sort_option = request.form.get("sort")

        if destination and budget and season and interest:
            start_time = time.time()
            user_preferences = {'type': destination, 'budget': budget, 'season': season, 'interest': interest}
            conn = sqlite3.connect("users.db")
            
            recommendations_df, avg_sim = hybrid_recommendation(session["user"], user_preferences, df, conn)
            recommendations = recommendations_df.to_dict("records")
            
            # --- METRICS & LOGGING ---
            for item in recommendations[:10]:
                log_recommendation(session["user"], item['place'])
                
            execute_query("""
                INSERT INTO search_logs (username, type, budget, season, interest)
                VALUES (?, ?, ?, ?, ?)
            """, (session["user"], destination, budget, season, interest), commit=True)
            
            relevant_places = get_relevant_places(session["user"])
            precision = calculate_precision_k(recommendations, relevant_places, k=10)
            recall = calculate_recall_k(recommendations, relevant_places, k=10)
            f1 = calculate_f1(precision, recall)
            response_time_ms = (time.time() - start_time) * 1000
            
            log_metrics(precision, recall, f1, avg_sim, response_time_ms)
            conn.close()

            if sort_option == "rating":
                recommendations = sorted(recommendations, key=lambda x: float(x["rating"]), reverse=True)
            elif sort_option == "price":
                recommendations = sorted(recommendations, key=lambda x: float(x["cost"]))

    # Trending Logic
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT place, COUNT(*) FROM favorites GROUP BY place")
    fav_counts = cursor.fetchall()
    fav_dict = {place: count for place, count in fav_counts}

    trending_scores = []
    for i in range(len(df)):
        place = df.iloc[i]["Place"]
        rating = float(df.iloc[i]["Rating"])
        saves = fav_dict.get(place, 0)
        trending_scores.append(rating + (saves * 0.2))

    df["Trending_Score"] = trending_scores
    trending_df = df.sort_values(by="Trending_Score", ascending=False).head(6)

    cursor.execute("SELECT COUNT(*) FROM search_logs WHERE username=?", (session["user"],))
    total_searches = cursor.fetchone()[0]
    conn.close()

    return render_template("index.html", trending=trending_df.to_dict(orient="records"), 
                           recommendations=recommendations, total_searches=total_searches)

# ---------------- TRIP PLANNER ----------------
@recommend_bp.route("/trip_planner", methods=["GET", "POST"])
def trip_planner():
    if "user" not in session: return redirect(url_for("main_bp.login"))
    df = pd.read_csv("maharashtra_destinations.csv")
    df.columns = df.columns.str.strip()
    districts = sorted(df["District"].dropna().unique())

    itinerary = {}; selected_district = None; selected_days = None; total_trip_budget = 0

    if request.method == "POST":
        selected_district = request.form.get("district")
        selected_days = int(request.form.get("days"))
        filtered_df = df[df["District"] == selected_district].copy()

        if not filtered_df.empty:
            filtered_df["Rating"] = pd.to_numeric(filtered_df["Rating"], errors="coerce")
            filtered_df["Approx_Cost"] = pd.to_numeric(filtered_df["Approx_Cost"], errors="coerce")
            filtered_df["Latitude"] = pd.to_numeric(filtered_df["Latitude"], errors="coerce")
            filtered_df["Longitude"] = pd.to_numeric(filtered_df["Longitude"], errors="coerce")
            filtered_df = filtered_df.sort_values(by="Rating", ascending=False)
            places = filtered_df.to_dict(orient="records")
            used_places = set()

            for day in range(1, selected_days + 1):
                day_key = f"Day {day}"; day_places = []; daily_budget = 0
                previous_lat = None; previous_lon = None

                for place in places:
                    if place["Place"] in used_places: continue
                    if not day_places:
                        place["travel_time"] = 0
                        day_places.append(place); used_places.add(place["Place"])
                        daily_budget += place["Approx_Cost"]
                        previous_lat = float(place["Latitude"]); previous_lon = float(place["Longitude"])
                    else:
                        dist = calculate_distance(previous_lat, previous_lon, float(place["Latitude"]), float(place["Longitude"]))
                        if dist <= 25:
                            place["travel_time"] = round(dist / 40, 2)
                            day_places.append(place); used_places.add(place["Place"])
                            daily_budget += place["Approx_Cost"]
                            previous_lat = float(place["Latitude"]); previous_lon = float(place["Longitude"])
                    if len(day_places) == 3: break

                day_places = optimize_route(day_places)
                total_distance = 0; total_time = 0
                for i in range(1, len(day_places)):
                    dist = calculate_distance(float(day_places[i-1]["Latitude"]), float(day_places[i-1]["Longitude"]),
                                              float(day_places[i]["Latitude"]), float(day_places[i]["Longitude"]))
                    total_distance += dist; total_time += dist / 40

                itinerary[day_key] = {"places": day_places, "budget": int(daily_budget),
                                      "total_distance": round(total_distance, 2), "total_time": round(total_time, 2)}
                total_trip_budget += daily_budget
            session["last_itinerary"] = itinerary

    return render_template("trip_planner.html", districts=districts, itinerary=itinerary,
                           selected_district=selected_district, selected_days=selected_days, total_trip_budget=total_trip_budget)

@recommend_bp.route("/save_trip", methods=["POST"])
def save_trip():
    import sqlite3
    username = session.get("user")
    execute_query("INSERT INTO saved_trips (username, district, days, total_budget, created_at) VALUES (?, ?, ?, ?, ?)",
                  (username, request.form.get("district"), request.form.get("days"), request.form.get("total_budget"), datetime.now()), commit=True)
    return redirect(url_for("main_bp.dashboard"))

@recommend_bp.route("/delete_trip", methods=["POST"])
def delete_trip():
    execute_query("DELETE FROM saved_trips WHERE username=? AND district=? AND created_at=?",
                  (session.get("user"), request.form.get("district"), request.form.get("created_at")), commit=True)
    return redirect(url_for("main_bp.dashboard"))

@recommend_bp.route("/download_trip")
def download_trip():
    file_path = "trip_plan.pdf"
    doc = SimpleDocTemplate(file_path)
    elements = []; styles = getSampleStyleSheet()
    elements.append(Paragraph("MahaTrip AI - Trip Plan", styles["Title"]))
    elements.append(Spacer(1, 0.5 * inch))
    for day, data in session.get("last_itinerary", {}).items():
        elements.append(Paragraph(day, styles["Heading2"]))
        elements.append(Spacer(1, 0.2 * inch))
        for place in data["places"]:
            elements.append(Paragraph(f"{place['Place']} - ₹{place['Approx_Cost']}", styles["Normal"]))
        elements.append(Spacer(1, 0.5 * inch))
    doc.build(elements)
    return send_file(file_path, as_attachment=True)

# ---------------- PLACE DETAIL ----------------
@recommend_bp.route("/place/<name>")
def place_detail(name):
    if "user" not in session: return redirect(url_for("main_bp.login"))
    df = pd.read_csv("maharashtra_destinations.csv")
    df.columns = df.columns.str.strip()
    df["Place"] = df["Place"].str.strip()
    place_data = df[df["Place"].str.lower() == name.strip().lower()]

    if place_data.empty: return "Place not found"
    place = place_data.iloc[0]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT interest, location FROM users WHERE username=?", (session["user"],))
    user_data = cursor.fetchone()
    
    session_user_interest = user_data[0] if user_data else None
    
    short_description = f"""{place['Place']} is a popular {place['Type']} destination located in {place['District']}, Maharashtra."""
    weather = get_weather(place["Latitude"], place["Longitude"])

    related_df = df[df["Place"] != place["Place"]].copy()
    related_df["Similarity"] = ((related_df["Type"] == place["Type"]).astype(int) * 3 +
                                (related_df["Budget"] == place["Budget"]).astype(int) * 2 +
                                (related_df["Interest"] == place["Interest"]).astype(int) * 2)
    related_places = related_df.sort_values(by=["Similarity", "Rating"], ascending=[False, False]).head(3).to_dict(orient="records")

    nearby_list = []
    for _, row in df.iterrows():
        if row["Place"] != place["Place"]:
            distance = calculate_distance(place["Latitude"], place["Longitude"], row["Latitude"], row["Longitude"])
            nearby_list.append({"Place": row["Place"], "Image_URL": row["Image_URL"], "Rating": row["Rating"],
                                "Approx_Cost": row["Approx_Cost"], "Distance": distance})
    nearby_places = sorted(nearby_list, key=lambda x: x["Distance"])[:3]

    cursor.execute("SELECT note, created_at FROM notes WHERE username=? AND place=? ORDER BY id DESC", (session["user"], name))
    notes = cursor.fetchall()
    
    try:
        _hist_rating = float(place["Rating"]) if place["Rating"] else 0.0
    except (ValueError, TypeError):
        _hist_rating = 0.0
    try:
        _hist_cost = float(place["Approx_Cost"]) if place["Approx_Cost"] else 0.0
    except (ValueError, TypeError):
        _hist_cost = 0.0
    cursor.execute("INSERT INTO history (username, place, rating, cost) VALUES (?, ?, ?, ?)",
                   (session["user"], place["Place"], _hist_rating, _hist_cost))
    conn.commit(); conn.close()

    return render_template("place_detail.html", place=place, short_description=short_description,
                           notes=notes, related_places=related_places, nearby_places=nearby_places, weather=weather)

@recommend_bp.route("/add_note/<name>", methods=["POST"])
def add_note(name):
    execute_query("INSERT INTO notes (username, place, note, created_at) VALUES (?, ?, ?, ?)",
                  (session.get("user"), name, request.form.get("note"), datetime.now()), commit=True)
    return redirect(url_for("recommend_bp.place_detail", name=name))

@recommend_bp.route("/chatbot", methods=["POST"])
def chatbot():
    try:
        user_message = request.get_json().get("message", "").strip()
        user_msg_clean = user_message.lower()
        
        # 1. Intent: Greetings
        greetings = ["hi", "hello", "hey", "good morning", "good evening", "who are you", "help"]
        if any(user_msg_clean == g or user_msg_clean.startswith(g + " ") for g in greetings) and len(user_msg_clean) < 20:
            return jsonify({"reply": "Hello! I am your Smart AI Travel Assistant. Ask me to suggest a destination (e.g., 'suggest a cheap beach') or ask me for details about a specific place in Maharashtra!"})

        df = pd.read_csv("maharashtra_destinations.csv")
        df.columns = df.columns.str.strip()

        # 2. Intent: Specific Place Lookup
        place_names = df["Place"].str.lower().dropna().tolist()
        mentioned_place = None
        for p in place_names:
            if p in user_msg_clean:
                if len(p) > 3:
                    mentioned_place = p
                    break
        
        if mentioned_place:
            # Find the specific place details
            place_data = df[df["Place"].str.lower() == mentioned_place].iloc[0]
            name = place_data.get("Place", "")
            dist = place_data.get("District", "")
            typ = place_data.get("Type", "")
            rating = place_data.get("Rating", "N/A")
            cost = place_data.get("Approx_Cost", "N/A")
            season = place_data.get("Season", "Any")
            
            reply = f"Ah, **{name}**!\n\n"
            reply += f"📍 **Location:** {dist}, Maharashtra\n"
            reply += f"🏔 **Type:** {typ} destination\n"
            reply += f"⭐ **Rating:** {rating}/5.0\n"
            reply += f"💰 **Approx Cost:** ₹{cost} per person\n"
            reply += f"☀ **Best Season:** {season}\n\n"
            reply += f"You can explore more on the dashboard or search for it!"
            return jsonify({"reply": reply})

        # 3. Intent: Calculate Distance Focus
        if "distance" in user_msg_clean and "from" in user_msg_clean and "to" in user_msg_clean:
            return jsonify({"reply": "I see you're asking about distances! Please check out the **🗺 Trip Planner** tool in the top navigation to plot routes and automatically get travel times between any places."})

        # 4. Intent: Recommendation Fallback
        destination = None; budget = None; season = None; interest = None

        type_keywords = {
            "Beach": ["beach", "sea", "ocean", "coast", "sand"],
            "Hill": ["hill", "mountain", "valley", "peak", "trek", "trekking"],
            "Spiritual": ["spiritual", "temple", "shrine", "ashram", "holy", "god", "religious"],
            "Historical": ["historical", "history", "museum", "cave", "ancient", "monument", "heritage"],
            "Nature": ["nature", "lake", "waterfall", "greenery", "forest", "scenic"],
            "Wildlife": ["wildlife", "animal", "tiger", "safari", "sanctuary", "national park"],
            "Fort": ["fort", "castle", "palace"]
        }
        
        budget_keywords = {
            "Low": ["low", "cheap", "affordable", "budget", "inexpensive", "pocket-friendly"],
            "Medium": ["medium", "moderate", "average", "standard", "reasonable"],
            "High": ["high", "luxury", "expensive", "premium", "lavish", "rich"]
        }
        
        season_keywords = {
            "Summer": ["summer", "hot", "sun", "warm"],
            "Winter": ["winter", "cold", "snow", "chill", "freezing"],
            "Monsoon": ["monsoon", "rain", "wet", "rainy"],
            "All": ["all", "any time", "year-round", "anytime"]
        }
        
        interest_keywords = {
            "Adventure": ["adventure", "thrill", "action", "exciting", "camping", "hiking", "trek"],
            "Relaxation": ["relaxation", "relax", "peace", "chill", "calm", "quiet"],
            "Spiritual": ["spiritual", "religious", "pray", "peaceful", "meditation"],
            "Cultural": ["cultural", "culture", "tradition", "local", "art", "festival"],
            "Wildlife": ["wildlife", "animal", "bird", "safari"]
        }

        for k, words in type_keywords.items():
            if any(w in user_msg_clean for w in words): destination = k
        for k, words in budget_keywords.items():
            if any(w in user_msg_clean for w in words): budget = k
        for k, words in season_keywords.items():
            if any(w in user_msg_clean for w in words): season = k
        for k, words in interest_keywords.items():
            if any(w in user_msg_clean for w in words): interest = k

        last_prefs = session.get("last_preferences", {})
        destination = destination or last_prefs.get("type", "")
        budget = budget or last_prefs.get("budget", "")
        season = season or last_prefs.get("season", "")
        interest = interest or last_prefs.get("interest", "")

        user_preferences = {"type": destination, "budget": budget, "season": season, "interest": interest}
        session["last_preferences"] = user_preferences
        session.modified = True

        username = session.get("user")
        if not username:
            return jsonify({"reply": "Please log in to get personalized recommendations."})

        conn = sqlite3.connect("users.db")
        try:
            recommendations_df, _ = hybrid_recommendation(username, user_preferences, df, conn)
        finally:
            conn.close()

        filtered_df = recommendations_df.head(5)
        if filtered_df.empty: 
            return jsonify({"reply": "Sorry 😔 I couldn't find any destinations matching those preferences right now."})
        
        # Build recommendation response
        prefs = []
        if destination: prefs.append(f"{destination.lower()} destinations")
        if budget: prefs.append(f"a {budget.lower()} budget")
        if season: prefs.append(f"the {season.lower()} season")
        if interest: prefs.append(f"{interest.lower()} activities")
        
        exact_match = True
        top_row = filtered_df.iloc[0]
        if destination and str(top_row.get("Type", "")).strip().lower() != destination.lower(): exact_match = False
        if budget and str(top_row.get("Budget", "")).strip().lower() != budget.lower(): exact_match = False
        if season and str(top_row.get("Season", "")).strip().lower() not in [season.lower(), "all"]: exact_match = False
        if interest and str(top_row.get("Interest", "")).strip().lower() != interest.lower(): exact_match = False

        if not prefs:
            reply = "I'm not exactly sure what you're looking for, but based on your recent activity, here are my top picks:\n\n"
        else:
            pref_str = " and ".join([", ".join(prefs[:-1]), prefs[-1]] if len(prefs) > 1 else prefs)
            if exact_match:
                reply = f"Based on your interest in {pref_str}, here are some top recommendations:\n\n"
            else:
                reply = f"I couldn't find an exact match for {pref_str}, but here are the closest alternatives:\n\n"
        
        for _, row in filtered_df.iterrows(): 
            explanation = row.get("explanation", "")
            exp_msg = f"\n  💡 {explanation}" if explanation else ""
            reply += f"• **{row['Place']}** (⭐ {row['Rating']}){exp_msg}\n\n"
            
        return jsonify({"reply": reply})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"reply": "Server error occurred while fetching your answer."})

@recommend_bp.route("/save_favorite", methods=["POST"])
def save_favorite():
    if "user" not in session: return redirect(url_for("main_bp.login"))
    place = request.form.get("place")
    if request.is_json: place = request.get_json().get("place")
    
    db_save_favorite(session["user"], place)
    if request.is_json: return jsonify({"success": True})
    flash(f"{place} added to favorites ❤️", "success")
    return redirect(url_for("recommend_bp.home"))

@recommend_bp.route("/rate_place", methods=["POST"])
def rate_place():
    if "user" not in session: return jsonify({"success": False, "error": "Unauthorized"}), 401
    data = request.get_json() or request.form
    db_save_rating(session["user"], data.get("place"), float(data.get("rating", 0)))
    return jsonify({"success": True, "message": f"Successfully rated {data.get('place')}"})

@recommend_bp.route("/track_click", methods=["POST"])
def track_click():
    data = request.get_json() or request.form
    user = session.get("user")
    if user:
        log_click(user, data.get("place"))
    return jsonify({"success": True})
