import hashlib
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
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


def activity_form_defaults():
    return {
        "title": "",
        "description": "",
        "distance": "",
        "activity_date": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "duration": "",
        "route_id": "",
    }


def activity_form_values(activity):
    activity_date = activity["activity_date"]
    date_format = "%Y-%m-%dT%H:%M:%S" if activity_date.second else "%Y-%m-%dT%H:%M"
    return {
        "title": activity["title"],
        "description": activity["description"] or "",
        "distance": str(activity["distance"]),
        "activity_date": activity_date.strftime(date_format),
        "duration": str(activity["duration"]),
        "route_id": str(activity["route_id"]) if activity["route_id"] else "",
    }


def render_activity_form(values, errors=None, mode="create", status_code=200):
    routes = fetch_all(
        """
        SELECT r.route_id, r.route_name, r.user_id, u.username
        FROM routes r
        JOIN users u ON u.user_id = r.user_id
        ORDER BY u.username, r.route_name
        """
    )
    return (
        render_template(
            "activity_form.html",
            page_title="Add activity" if mode == "create" else "Edit activity",
            active_page="activities",
            mode=mode,
            values=values,
            routes=routes,
            errors=errors or {},
        ),
        status_code,
    )


def validate_activity_form():
    values = {
        field: request.form.get(field, "")
        for field in (
            "title",
            "description",
            "distance",
            "activity_date",
            "duration",
            "route_id",
        )
    }
    values["title"] = values["title"].strip()
    values["description"] = values["description"].strip()
    errors = {}
    data = {}

    if not values["title"]:
        errors["title"] = "Enter an activity title."
    elif len(values["title"]) > 150:
        errors["title"] = "Use 150 characters or fewer."

    if len(values["description"].encode("utf-8")) > 65535:
        errors["description"] = "The description is too long."

    try:
        distance = Decimal(values["distance"])
        if not distance.is_finite() or distance <= 0:
            raise InvalidOperation
        if distance > Decimal("99999999.99"):
            errors["distance"] = "Distance exceeds the supported range."
        elif distance.quantize(Decimal("0.01")) != distance:
            errors["distance"] = "Use no more than two decimal places."
        else:
            data["distance"] = distance.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        errors.setdefault("distance", "Enter a valid distance greater than zero.")

    date_value = values["activity_date"]
    for date_format in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            data["activity_date"] = datetime.strptime(date_value, date_format)
            break
        except ValueError:
            continue
    if "activity_date" not in data:
        errors["activity_date"] = "Enter a valid date and time."

    try:
        duration = int(values["duration"])
        if duration < 1 or duration > 4294967295:
            raise ValueError
        data["duration"] = duration
    except ValueError:
        errors["duration"] = "Enter a whole number of seconds greater than zero."

    route_value = values["route_id"]
    if route_value:
        try:
            route_id = int(route_value)
            if route_id < 1:
                raise ValueError
            data["route_id"] = route_id
        except ValueError:
            errors["route_id"] = "Choose a valid route or leave the field blank."
    else:
        data["route_id"] = None

    if not errors:
        data["title"] = values["title"]
        data["description"] = values["description"] or None

        if data["route_id"] is not None and fetch_one(
            "SELECT route_id FROM routes WHERE route_id = %s",
            (data["route_id"],),
        ) is None:
            errors["route_id"] = "Choose an existing route."

    return values, data, errors


def require_activity_owner(activity):
    """Ensure the logged-in user owns the activity; abort 403 otherwise."""
    user = get_current_user()
    if user is None or activity["user_id"] != user["user_id"]:
        abort(403)
    return user


def execute_write(query, parameters):
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            lastrowid = cursor.lastrowid
        connection.commit()
        return lastrowid
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_activity(activity_id):
    return fetch_one(
        """
        SELECT activity_id, user_id, route_id, title, description, distance,
               activity_date, duration
        FROM activities
        WHERE activity_id = %s
        """,
        (activity_id,),
    )


@app.route("/activities/new", methods=["GET", "POST"])
@login_required
def create_activity():
    try:
        user = get_current_user()
        if request.method == "GET":
            return render_activity_form(activity_form_defaults())

        values, data, errors = validate_activity_form()
        if errors:
            return render_activity_form(values, errors, status_code=400)

        execute_write(
            """
            INSERT INTO activities
                (user_id, route_id, title, description, distance, activity_date, duration)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user["user_id"],
                data["route_id"],
                data["title"],
                data["description"],
                data["distance"],
                data["activity_date"],
                data["duration"],
            ),
        )
        return redirect(url_for("activities_page", notice="created"))
    except mysql.connector.Error:
        return database_error_page()


@app.route("/activities/<int:activity_id>/edit", methods=["GET", "POST"])
@login_required
def edit_activity(activity_id):
    try:
        activity = get_activity(activity_id)
        if activity is None:
            abort(404)
        require_activity_owner(activity)

        if request.method == "GET":
            return render_activity_form(activity_form_values(activity), mode="edit")

        values, data, errors = validate_activity_form()
        if errors:
            return render_activity_form(values, errors, mode="edit", status_code=400)

        execute_write(
            """
            UPDATE activities
            SET route_id = %s, title = %s, description = %s,
                distance = %s, activity_date = %s, duration = %s
            WHERE activity_id = %s AND user_id = %s
            """,
            (
                data["route_id"],
                data["title"],
                data["description"],
                data["distance"],
                data["activity_date"],
                data["duration"],
                activity_id,
                activity["user_id"],
            ),
        )
        return redirect(url_for("activities_page", notice="updated"))
    except mysql.connector.Error:
        return database_error_page()


@app.get("/activities/<int:activity_id>/delete")
@login_required
def confirm_delete_activity(activity_id):
    try:
        activity = fetch_one(
            """
            SELECT a.activity_id, a.user_id, a.title, u.username,
                   (SELECT COUNT(*) FROM kudos k WHERE k.activity_id = a.activity_id)
                       AS kudos_count,
                   (SELECT COUNT(*) FROM comments c WHERE c.activity_id = a.activity_id)
                       AS comment_count
            FROM activities a
            JOIN users u ON u.user_id = a.user_id
            WHERE a.activity_id = %s
            """,
            (activity_id,),
        )
        if activity is None:
            abort(404)
        require_activity_owner(activity)
        return render_template("activity_delete.html", activity=activity)
    except mysql.connector.Error:
        return database_error_page()


@app.post("/activities/<int:activity_id>/delete")
@login_required
def delete_activity(activity_id):
    try:
        activity = get_activity(activity_id)
        if activity is None:
            abort(404)
        require_activity_owner(activity)
        execute_write(
            "DELETE FROM activities WHERE activity_id = %s AND user_id = %s",
            (activity_id, activity["user_id"]),
        )
        return redirect(url_for("activities_page", notice="deleted"))
    except mysql.connector.Error:
        return database_error_page()


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
        notices = {
            "created": "Activity added successfully.",
            "updated": "Activity updated successfully.",
            "deleted": "Activity and its related reactions and comments were deleted.",
        }
        return render_template(
            "activities.html",
            activities=activities,
            notice=notices.get(request.args.get("notice")),
        )
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


def is_following(follower_id, followed_id):
    if not follower_id or not followed_id or follower_id == followed_id:
        return False
    row = fetch_one(
        """
        SELECT 1 AS ok
        FROM user_follows
        WHERE follower_id = %s AND followed_id = %s
        """,
        (follower_id, followed_id),
    )
    return row is not None


@app.get("/users")
def users_page():
    try:
        me = get_current_user()
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
                ), 0) AS total_distance,
                (SELECT COUNT(*) FROM user_follows f
                 WHERE f.followed_id = u.user_id) AS follower_count
            FROM users u
            LEFT JOIN activities a ON a.user_id = u.user_id
            GROUP BY u.user_id, u.username
            ORDER BY u.username
            """
        )
        following_ids = set()
        if me is not None:
            rows = fetch_all(
                "SELECT followed_id FROM user_follows WHERE follower_id = %s",
                (me["user_id"],),
            )
            following_ids = {row["followed_id"] for row in rows}
        return render_template(
            "users.html",
            users=users,
            following_ids=following_ids,
        )
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

        me = get_current_user()
        viewer_is_self = me is not None and me["user_id"] == user_id
        viewer_follows = (
            is_following(me["user_id"], user_id) if me is not None else False
        )

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
        followers = fetch_all(
            """
            SELECT u.user_id, u.username
            FROM user_follows f
            JOIN users u ON u.user_id = f.follower_id
            WHERE f.followed_id = %s
            ORDER BY u.username
            """,
            (user_id,),
        )
        following = fetch_all(
            """
            SELECT u.user_id, u.username
            FROM user_follows f
            JOIN users u ON u.user_id = f.followed_id
            WHERE f.follower_id = %s
            ORDER BY u.username
            """,
            (user_id,),
        )
        return render_template(
            "user_profile.html",
            user=user,
            activities=activities,
            routes=routes,
            followers=followers,
            following=following,
            viewer_is_self=viewer_is_self,
            viewer_follows=viewer_follows,
        )
    except mysql.connector.Error:
        return database_error_page()


@app.post("/users/<int:user_id>/follow")
@login_required
def follow_user(user_id):
    me = get_current_user()
    if me["user_id"] == user_id:
        flash("You cannot follow yourself.", "error")
        return redirect(url_for("user_profile", user_id=user_id))

    try:
        target = fetch_one("SELECT user_id, username FROM users WHERE user_id = %s", (user_id,))
        if target is None:
            abort(404)

        if is_following(me["user_id"], user_id):
            flash(f"You already follow {target['username']}.", "success")
        else:
            execute_write(
                """
                INSERT INTO user_follows (follower_id, followed_id)
                VALUES (%s, %s)
                """,
                (me["user_id"], user_id),
            )
            flash(f"You are now following {target['username']}.", "success")
        return redirect(url_for("user_profile", user_id=user_id))
    except mysql.connector.Error:
        app.logger.exception("Failed to follow user")
        flash("Could not follow that athlete. Check the database connection.", "error")
        return redirect(url_for("user_profile", user_id=user_id))


@app.post("/users/<int:user_id>/unfollow")
@login_required
def unfollow_user(user_id):
    me = get_current_user()
    try:
        target = fetch_one("SELECT user_id, username FROM users WHERE user_id = %s", (user_id,))
        if target is None:
            abort(404)

        execute_write(
            """
            DELETE FROM user_follows
            WHERE follower_id = %s AND followed_id = %s
            """,
            (me["user_id"], user_id),
        )
        flash(f"You unfollowed {target['username']}.", "success")
        return redirect(url_for("user_profile", user_id=user_id))
    except mysql.connector.Error:
        app.logger.exception("Failed to unfollow user")
        flash("Could not unfollow that athlete. Check the database connection.", "error")
        return redirect(url_for("user_profile", user_id=user_id))


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
