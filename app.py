import hashlib
import logging
import os
from functools import wraps

import mysql.connector
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-strava-dashboard-secret")
logging.basicConfig(level=logging.INFO)


def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "strava"),
        connection_timeout=5,
    )


def fetch_all(query, parameters=()):
    connection = get_connection()
    try:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchall()
    finally:
        connection.close()


def fetch_one(query, parameters=()):
    rows = fetch_all(query, parameters)
    return rows[0] if rows else None


def execute(query, parameters=()):
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            connection.commit()
            return cursor.lastrowid
    finally:
        connection.close()


def hash_password(password: str) -> str:
    """Match demo_data.sql: SHA2(password, 256)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        return fetch_one(
            "SELECT user_id, username, email FROM users WHERE user_id = %s",
            (user_id,),
        )
    except mysql.connector.Error:
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if get_current_user() is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_current_user():
    return {"current_user": get_current_user()}


ACTIVITY_QUERY = """
    SELECT
        a.activity_id,
        a.title,
        a.description,
        a.distance,
        a.activity_date,
        a.duration,
        u.user_id,
        u.username,
        r.route_id,
        r.route_name,
        (SELECT COUNT(*) FROM kudos k
         WHERE k.activity_id = a.activity_id) AS kudos_count,
        (SELECT COUNT(*) FROM comments c
         WHERE c.activity_id = a.activity_id) AS comment_count
    FROM activities a
    JOIN users u ON u.user_id = a.user_id
    LEFT JOIN routes r ON r.route_id = a.route_id
"""


def database_error_page():
    app.logger.exception("Unable to load page data from MySQL")
    return (
        render_template(
            "error.html",
            page_title="Database unavailable",
            database_error=(
                "The app could not connect to MySQL. Check that the server is "
                "running and your .env settings are correct."
            ),
        ),
        503,
    )


@app.get("/")
def dashboard():
    try:
        stats = fetch_one(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS user_count,
                (SELECT COUNT(*) FROM activities) AS activity_count,
                (SELECT COUNT(*) FROM routes) AS route_count,
                (SELECT COALESCE(SUM(distance), 0) FROM activities) AS total_distance
            """
        )
        activities = fetch_all(
            ACTIVITY_QUERY + " ORDER BY a.activity_date DESC, a.activity_id DESC LIMIT 8"
        )
        return render_template(
            "index.html",
            stats=stats,
            activities=activities,
        )
    except mysql.connector.Error:
        return database_error_page()


@app.get("/activities")
def activities_page():
    try:
        activities = fetch_all(
            ACTIVITY_QUERY + " ORDER BY a.activity_date DESC, a.activity_id DESC"
        )
        return render_template("activities.html", activities=activities)
    except mysql.connector.Error:
        return database_error_page()


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user() is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        next_url = request.form.get("next") or request.args.get("next") or url_for("dashboard")

        if not username or not password:
            flash("Enter both username and password.", "error")
            return render_template("login.html", next=next_url)

        try:
            user = fetch_one(
                """
                SELECT user_id, username, password_hash
                FROM users
                WHERE username = %s
                """,
                (username,),
            )
        except mysql.connector.Error:
            return database_error_page()

        if user is None or user["password_hash"] != hash_password(password):
            flash("Invalid username or password.", "error")
            return render_template("login.html", next=next_url)

        session.clear()
        session["user_id"] = user["user_id"]
        session["username"] = user["username"]
        flash(f"Welcome back, {user['username']}.", "success")

        # Only allow relative redirects
        if not next_url.startswith("/"):
            next_url = url_for("dashboard")
        return redirect(next_url)

    next_url = request.args.get("next") or url_for("dashboard")
    return render_template("login.html", next=next_url)


@app.post("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("dashboard"))


@app.get("/routes")
def routes_page():
    try:
        routes = fetch_all(
            """
            SELECT
                r.route_id,
                r.route_name,
                r.distance,
                r.elevation,
                r.description,
                r.created_at,
                u.user_id,
                u.username,
                COUNT(DISTINCT a.activity_id) AS activity_count
            FROM routes r
            JOIN users u ON u.user_id = r.user_id
            LEFT JOIN activities a ON a.route_id = r.route_id
            GROUP BY r.route_id, r.route_name, r.distance, r.elevation,
                     r.description, r.created_at, u.user_id, u.username
            ORDER BY r.created_at DESC, r.route_id DESC
            """
        )
        return render_template("routes.html", routes=routes)
    except mysql.connector.Error:
        return database_error_page()


@app.post("/routes/create")
@login_required
def create_route():
    try:
        user = get_current_user()
        route_name = (request.form.get("route_name") or "").strip()
        distance = request.form.get("distance", type=float)
        elevation = request.form.get("elevation", type=float)
        description = (request.form.get("description") or "").strip() or None

        if not route_name or distance is None or elevation is None:
            flash("Please fill in route name, distance, and elevation.", "error")
            return redirect(url_for("routes_page"))

        if distance < 0 or elevation < 0:
            flash("Distance and elevation must be zero or greater.", "error")
            return redirect(url_for("routes_page"))

        execute(
            """
            INSERT INTO routes (user_id, route_name, distance, elevation, description)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user["user_id"], route_name[:150], distance, elevation, description),
        )
        flash(f'Route "{route_name}" created successfully.', "success")
        return redirect(url_for("routes_page"))
    except mysql.connector.Error:
        app.logger.exception("Failed to create route")
        flash("Could not create the route. Check the database connection.", "error")
        return redirect(url_for("routes_page"))


@app.get("/users")
def users_page():
    try:
        users = fetch_all(
            """
            SELECT
                u.user_id,
                u.username,
                COUNT(DISTINCT a.activity_id) AS activity_count,
                COALESCE((
                    SELECT SUM(a2.distance)
                    FROM activities a2
                    WHERE a2.user_id = u.user_id
                ), 0) AS total_distance
            FROM users u
            LEFT JOIN activities a ON a.user_id = u.user_id
            GROUP BY u.user_id, u.username
            ORDER BY u.username
            """
        )
        return render_template("users.html", users=users)
    except mysql.connector.Error:
        return database_error_page()


@app.get("/users/<int:user_id>")
def user_profile(user_id):
    try:
        user = fetch_one(
            """
            SELECT
                u.user_id,
                u.username,
                (SELECT COUNT(*) FROM activities a
                 WHERE a.user_id = u.user_id) AS activity_count,
                (SELECT COUNT(*) FROM routes r
                 WHERE r.user_id = u.user_id) AS route_count,
                COALESCE((SELECT SUM(a.distance) FROM activities a
                          WHERE a.user_id = u.user_id), 0) AS total_distance,
                (SELECT COUNT(*) FROM user_follows f
                 WHERE f.followed_id = u.user_id) AS follower_count,
                (SELECT COUNT(*) FROM user_follows f
                 WHERE f.follower_id = u.user_id) AS following_count
            FROM users u
            WHERE u.user_id = %s
            """,
            (user_id,),
        )
        if user is None:
            abort(404)

        activities = fetch_all(
            ACTIVITY_QUERY
            + " WHERE a.user_id = %s ORDER BY a.activity_date DESC, a.activity_id DESC",
            (user_id,),
        )
        routes = fetch_all(
            """
            SELECT route_id, route_name, distance, elevation, description
            FROM routes
            WHERE user_id = %s
            ORDER BY created_at DESC, route_id DESC
            """,
            (user_id,),
        )
        return render_template(
            "user_profile.html",
            user=user,
            activities=activities,
            routes=routes,
        )
    except mysql.connector.Error:
        return database_error_page()


@app.get("/healthz")
def health_check():
    try:
        connection = get_connection()
        connection.close()
        return jsonify(status="ok", database="connected")
    except mysql.connector.Error:
        app.logger.exception("MySQL health check failed")
        return jsonify(status="error", database="unavailable"), 503


if __name__ == "__main__":
    app.run(
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
