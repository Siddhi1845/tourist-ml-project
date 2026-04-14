from flask import Blueprint, render_template, session, redirect, url_for, request, Response
import sqlite3

admin_bp = Blueprint('admin_bp', __name__)

# ---------------- ADMIN DASHBOARD ----------------
@admin_bp.route("/admin")
def admin():
    if "user" not in session or session["user"] != "admin":
        return "Unauthorized Access"

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM search_logs")
    total_searches_res = cursor.fetchone()
    total_searches = total_searches_res[0] if total_searches_res else 0

    cursor.execute("SELECT COUNT(*) FROM favorites")
    total_favorites_res = cursor.fetchone()
    total_favorites = total_favorites_res[0] if total_favorites_res else 0

    cursor.execute("SELECT COUNT(*) FROM saved_trips")
    total_trips_res = cursor.fetchone()
    total_trips = total_trips_res[0] if total_trips_res else 0

    cursor.execute("SELECT id, username, email, created_at FROM users")
    users = cursor.fetchall()

    cursor.execute("SELECT username, type, timestamp FROM search_logs ORDER BY timestamp DESC LIMIT 5")
    recent_activity = cursor.fetchall()

    cursor.execute("SELECT type, COUNT(*) as count FROM search_logs GROUP BY type ORDER BY count DESC LIMIT 5")
    popular_types = cursor.fetchall()

    chart_labels = [row[0] for row in popular_types]
    chart_values = [row[1] for row in popular_types]

    cursor.execute("SELECT date(timestamp) as d, COUNT(*) FROM search_logs GROUP BY d ORDER BY d ASC LIMIT 7")
    trends = cursor.fetchall()
    dates = [row[0] for row in trends]
    search_counts = [row[1] for row in trends]

    conn.close()

    return render_template(
        "admin.html",
        total_searches=total_searches,
        total_favorites=total_favorites,
        total_trips=total_trips,
        users=users,
        recent_activity=recent_activity,
        chart_labels=chart_labels,
        chart_values=chart_values,
        dates=dates,
        search_counts=search_counts,
    )

# ---------------- BULK DELETE USERS ----------------
@admin_bp.route("/bulk_delete")
def bulk_delete():
    if "user" not in session or session["user"] != "admin":
        return "Unauthorized Access"

    ids = request.args.get("ids")
    if not ids:
        return redirect(url_for("admin_bp.admin"))

    id_list = ids.split(",")
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    for uid in id_list:
        cursor.execute("DELETE FROM users WHERE id=?", (uid,))

    conn.commit()
    conn.close()
    return redirect(url_for("admin_bp.admin"))

# ---------------- EXPORT USERS (ADMIN) ----------------
@admin_bp.route("/export_users")
def export_users():
    if "user" not in session or session["user"] != "admin":
        return "Unauthorized Access"

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, created_at FROM users")
    users = cursor.fetchall()
    conn.close()

    def generate():
        yield "ID,Username,Email,Joined\n"
        for row in users:
            yield f"{row[0]},{row[1]},{row[2]},{row[3]}\n"

    return Response(generate(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=users.csv"})

# ---------------- DELETE USER ----------------
@admin_bp.route("/delete_user/<int:user_id>")
def delete_user(user_id):
    if "user" not in session or session["user"] != "admin":
        return "Unauthorized Access"

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("admin_bp.admin"))
