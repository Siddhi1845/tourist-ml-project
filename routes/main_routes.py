from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import sqlite3
import pandas as pd
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

main_bp = Blueprint('main_bp', __name__)

# ---------------- LOGIN ----------------
@main_bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user[2], password):
            cursor.execute("""
                UPDATE users
                SET last_login=?, login_count=login_count+1
                WHERE username=?
            """, (datetime.now(), username))

            conn.commit()
            conn.close()

            session["user"] = username

            # 🔐 Admin Redirect
            if username == "admin":
                return redirect(url_for("admin_bp.admin"))

            return redirect(url_for("main_bp.experience"))
        else:
            conn.close()
            return render_template("login.html", error="Invalid Credentials")

    return render_template("login.html")

# ---------------- REGISTER ----------------
@main_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")
        email = request.form.get("email")
        location = request.form.get("location")
        interest = request.form.get("interest")

        if password != confirm:
            return render_template("register.html", error="Passwords do not match")

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        try:
            hashed_password = generate_password_hash(password)
            cursor.execute("""
                INSERT INTO users (username, password, email, location, interest, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (username, hashed_password, email, location, interest, datetime.now()))
            conn.commit()
        except:
            conn.close()
            return render_template("register.html", error="Username already exists")

        conn.close()
        return redirect(url_for("main_bp.login"))

    return render_template("register.html")

# ---------------- EXPERIENCE ----------------
@main_bp.route("/experience")
def experience():
    if "user" not in session:
        return redirect(url_for("main_bp.login"))
    username = session["user"]
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cursor.fetchone()

    # Get user history
    cursor.execute("SELECT place FROM history WHERE username=?", (username,))
    history = cursor.fetchall()
    personality = "Explorer"

    if history:
        df = pd.read_csv("maharashtra_destinations.csv")
        df.columns = df.columns.str.strip()
        place_types = []
        for (place,) in history:
            row = df[df["Place"] == place]
            if not row.empty:
                place_types.append(row.iloc[0]["Type"])

        if place_types:
            most_common = max(set(place_types), key=place_types.count)
            personality_map = {
                "Beach": "Coastal Dreamer",
                "Spiritual": "Spiritual Seeker",
                "Hill": "Mountain Explorer",
                "Wildlife": "Nature Enthusiast",
                "Historical": "Heritage Explorer",
                "Fort": "Adventure Strategist"
            }
            personality = personality_map.get(most_common, "Explorer")

    cursor.execute("SELECT place, COUNT(*) as count FROM history GROUP BY place ORDER BY count DESC LIMIT 3")
    trending = cursor.fetchall()
    conn.close()
    return render_template("experience.html", user=user, personality=personality, trending=trending)

# ---------------- DASHBOARD ----------------
@main_bp.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("main_bp.login"))

    username = session["user"]
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cursor.fetchone()

    cursor.execute("SELECT place, rating, cost FROM history WHERE username=? ORDER BY id DESC", (username,))
    history_raw = cursor.fetchall()

    history = []
    place_counter = {}
    place_types = []
    total_cost = 0

    df = pd.read_csv("maharashtra_destinations.csv")
    df.columns = df.columns.str.strip()

    for place, rating, cost in history_raw:
        try: cost = float(cost)
        except: cost = 0
        history.append((place, rating, cost))
        total_cost += cost
        place_counter[place] = place_counter.get(place, 0) + 1
        row = df[df["Place"] == place]
        if not row.empty:
            place_types.append(row.iloc[0]["Type"])

    cursor.execute("SELECT place, rating, cost FROM favorites WHERE username=?", (username,))
    favorites_raw = cursor.fetchall()
    favorites = []; seen = set()
    for place, rating, cost in favorites_raw:
        if place not in seen:
            try: cost = float(cost)
            except: cost = 0
            favorites.append((place, rating, cost))
            seen.add(place)

    cursor.execute("SELECT district, days, total_budget, created_at FROM saved_trips WHERE username=? ORDER BY id DESC", (username,))
    saved_trips = cursor.fetchall()

    cursor.execute("SELECT place, COUNT(*) as count FROM history GROUP BY place ORDER BY count DESC LIMIT 5")
    trending = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM search_logs WHERE username=?", (username,))
    total_searches_row = cursor.fetchone()
    total_searches = total_searches_row[0] if total_searches_row else 0
    conn.close()

    top_rated = df.sort_values(by="Rating", ascending=False).head(3)
    top_rated_places = top_rated.to_dict(orient="records")

    most_visited = max(place_counter, key=place_counter.get) if place_counter else None

    personality = "Explorer"
    if place_types:
        most_common = max(set(place_types), key=place_types.count)
        personality_map = {
            "Beach": "Coastal Dreamer",
            "Spiritual": "Spiritual Seeker",
            "Hill": "Mountain Explorer",
            "Wildlife": "Nature Enthusiast",
            "Historical": "Heritage Explorer",
            "Fort": "Adventure Strategist",
        }
        personality = personality_map.get(most_common, "Explorer")

    avg_budget = total_cost / len(history) if history else 0
    if avg_budget < 5000: budget_style = "Budget Traveler"
    elif avg_budget < 15000: budget_style = "Balanced Traveler"
    else: budget_style = "Luxury Explorer"

    activity_score = min((len(history) * 10 + len(saved_trips) * 15), 100)

    category_counts = df["Type"].value_counts().head(6)
    categories = [{"name": cat, "count": count} for cat, count in category_counts.items()]

    return render_template(
        "dashboard.html", user=user, history=history[:6], favorites=favorites,
        saved_trips=saved_trips, trending=trending, most_visited=most_visited,
        total_searches=total_searches, total_favorites=len(favorites), total_trips=len(saved_trips),
        personality=personality, budget_style=budget_style, activity_score=activity_score,
        category_labels=list(category_counts.keys()), category_values=[int(x) for x in category_counts.values],
        current_hour=datetime.now().hour, top_rated_places=top_rated_places, categories=categories
    )

# ---------------- EDIT PROFILE ----------------
@main_bp.route("/edit_profile", methods=["GET", "POST"])
def edit_profile():
    if "user" not in session:
        return redirect(url_for("main_bp.login"))
    username = session["user"]
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    if request.method == "POST":
        email = request.form.get("email")
        location = request.form.get("location")
        interest = request.form.get("interest")
        password = request.form.get("password")
        profile_photo = request.files.get("profile_photo")
        
        updates = ["email=?", "location=?", "interest=?"]
        params = [email, location, interest]
        
        if password:
            updates.append("password=?")
            params.append(generate_password_hash(password))
            
        if profile_photo and profile_photo.filename != '':
            import os
            from werkzeug.utils import secure_filename
            filename = secure_filename(f"{username}_{profile_photo.filename}")
            upload_dir = os.path.join("static", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            profile_photo.save(os.path.join(upload_dir, filename))
            updates.append("profile_photo=?")
            params.append(filename)
            
        params.append(username)
        query = f"UPDATE users SET {', '.join(updates)} WHERE username=?"
        cursor.execute(query, tuple(params))
        conn.commit()
        flash("Profile updated successfully!", "success")
    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cursor.fetchone()
    conn.close()
    return render_template("edit_profile.html", user=user)

# ---------------- LOGOUT ----------------
@main_bp.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("main_bp.login"))
