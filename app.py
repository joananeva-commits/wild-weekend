import sqlite3
import os
import secrets
from functools import wraps
from pathlib import Path
from hmac import compare_digest

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    abort
)

app = Flask(__name__)

@app.before_request
def generate_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)


def get_csrf_token():
    token = session.get("csrf_token")

    if token is None:
        token = secrets.token_hex(32)
        session["csrf_token"] = token

    return token


@app.context_processor
def inject_csrf_token():
    return {
        "csrf_token": get_csrf_token()
    }
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-only-change-me"
)

DB_PATH = Path(__file__).resolve().parent / "tourism.db"

print("DATABASE:", DB_PATH)


# =====================================================
# DATABASE CONNECTION
# =====================================================

def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
def validate_csrf():
    expected = session.get("csrf_token")
    received = request.form.get("csrf_token", "")

    if (
        not expected
        or not received
        or not compare_digest(expected, received)
    ):
        abort(400)

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped_view


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))

            if session.get("role") not in roles:
                abort(403)

            return view(*args, **kwargs)

        return wrapped_view

    return decorator

# =====================================================
# CAPACITY CHECK - LEGACY DEPARTURES
# =====================================================

def get_available_capacity(connection, departure_id):
    departure = connection.execute(
        """
        SELECT capacity
        FROM tour_departures
        WHERE id = ? AND is_active = 1
        """,
        (departure_id,)
    ).fetchone()

    if departure is None:
        return 0

    confirmed = connection.execute(
        """
        SELECT COALESCE(SUM(participants), 0)
        FROM bookings
        WHERE departure_id = ?
          AND status = 'CONFIRMED'
        """,
        (departure_id,)
    ).fetchone()[0]

    return departure["capacity"] - confirmed


# =====================================================
# CAPACITY CHECK - BOOKING REQUESTS
# =====================================================

def get_available_request_capacity(connection, tour_id, preferred_date):
    tour = connection.execute(
        """
        SELECT capacity
        FROM tours
        WHERE id = ?
        """,
        (tour_id,)
    ).fetchone()

    if tour is None:
        return 0

    confirmed = connection.execute(
        """
        SELECT COALESCE(SUM(participants), 0)
        FROM booking_requests
        WHERE tour_id = ?
          AND preferred_date = ?
          AND status = 'CONFIRMED'
        """,
        (tour_id, preferred_date)
    ).fetchone()[0]

    return tour["capacity"] - confirmed


# =====================================================
# DATABASE INITIALIZATION
# =====================================================

def init_db():

    with get_connection() as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS tours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0),
                capacity INTEGER NOT NULL CHECK(capacity > 0),
                latitude REAL,
                longitude REAL,
                map_query TEXT,
                image_url TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK(is_active IN (0, 1))
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS booking_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tour_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                participants INTEGER NOT NULL
                    CHECK(participants BETWEEN 1 AND 10),
                fitness_level TEXT,
                preferred_date TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING', 'CONFIRMED', 'CANCELLED')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tour_id) REFERENCES tours(id)
            )
        """)
            
        columns = [
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(booking_requests)"
            ).fetchall()
        ]

        if "user_id" not in columns:
            connection.execute("""
                ALTER TABLE booking_requests
                ADD COLUMN user_id INTEGER
                REFERENCES users(id)

        """)

        user_count = connection.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        if user_count == 0:
            connection.execute(
                """
                INSERT INTO users
                    (username, email, password_hash, role, status)
                VALUES (?, ?, ?, 'admin', 'ACTIVE')
                """,
                (
                    "admin",
                    "admin@example.com",
                    generate_password_hash("yoana2026")
                )
            )

        # Check for missing columns in an existing database.

        booking_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(booking_requests)"
            ).fetchall()
        }

        if "phone" not in booking_columns:
            connection.execute(
                "ALTER TABLE booking_requests ADD COLUMN phone TEXT"
            )

        if "fitness_level" not in booking_columns:
            connection.execute(
                "ALTER TABLE booking_requests ADD COLUMN fitness_level TEXT"
            )

        if "notes" not in booking_columns:
            connection.execute(
                "ALTER TABLE booking_requests ADD COLUMN notes TEXT"
            )

        if "status" not in booking_columns:
            connection.execute(
                """
                ALTER TABLE booking_requests
                ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'
                """
            )

        # Create tours if the database is empty.

        count = connection.execute(
            "SELECT COUNT(*) FROM tours"
        ).fetchone()[0]

        if count == 0:

            connection.executemany(
                """
                INSERT INTO tours (
                    code, name, location, description,
                    price, capacity, latitude, longitude,
                    map_query, image_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "planina",
                        "Диво приключение в планината",
                        "Родопите, Юндола, България",
                        "Уикенд сред природата, планински маршрути и близки срещи с дивия свят.",
                        220, 10, 42.0500, 23.8500,
                        "Юндола, Родопите, България",
                        "/static/images/deer.jpg"
                    ),
                    (
                        "more",
                        "Морско приключение",
                        "Остров Лефкада, Гърция",
                        "Ден край морето, кристални води и незабравимо преживяване с лодка.",
                        260, 10, 38.7066, 20.6406,
                        "Остров Лефкада, Гърция",
                        "/static/images/sea.jpg"
                    ),
                    (
                        "rafting",
                        "Рафтинг приключение",
                        "Река Струма, Кресненско дефиле, България",
                        "Адреналин, бързи води и емоции за любителите на активните преживявания.",
                        180, 10, 41.7500, 23.1500,
                        "Рафтинг река Струма, Кресненско дефиле, България",
                        "/static/images/rafting.jpg"
                    ),
                    (
                        "winter",
                        "Диво зимно приключение със снегоходки",
                        "Мальовица, Рила, България",
                        "Снежни планински пътеки, преход със снегоходки и нощувка сред дивата природа.",
                        240, 10, 42.1800, 23.3800,
                        "Мальовица, Рила, България",
                        "/static/images/wild-mountain.jpg"
                    )
                ]
            )

        # Update locations and map queries.

        updates = [
            (
                "Родопите, Юндола, България",
                "Юндола, Родопите, България",
                "planina"
            ),
            (
                "Остров Лефкада, Гърция",
                "Остров Лефкада, Гърция",
                "more"
            ),
            (
                "Река Струма, Кресненско дефиле, България",
                "Рафтинг река Струма, Кресненско дефиле, България",
                "rafting"
            ),
            (
                "Мальовица, Рила, България",
                "Мальовица, Рила, България",
                "winter"
            )
        ]

        for location, map_query, code in updates:
            connection.execute(
                """
                UPDATE tours
                SET location = ?, map_query = ?
                WHERE code = ?
                """,
                (location, map_query, code)
            )

        connection.execute(
            """
            UPDATE tours
            SET image_url = ?
            WHERE code = ?
            """,
            ("/static/images/deer.jpg", "planina")
        )

        connection.execute(
            """
            UPDATE tours
            SET image_url = ?
            WHERE code = ?
            """,
            ("/static/images/wild-mountain.jpg", "winter")
        )

        connection.execute(
            """
            UPDATE tours
            SET image_url = ?
            WHERE code = ?
            """,
            ("/static/images/kayak-iskar.png", "kayak-iskar")
        )

        # Legacy departure tables.

        connection.execute("""
            CREATE TABLE IF NOT EXISTS tour_departures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tour_id INTEGER NOT NULL,
                departure_date TEXT NOT NULL,
                capacity INTEGER NOT NULL CHECK(capacity > 0),
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK(is_active IN (0, 1)),
                FOREIGN KEY (tour_id) REFERENCES tours(id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                departure_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                participants INTEGER NOT NULL CHECK(participants > 0),
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING', 'CONFIRMED', 'CANCELLED')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (departure_id)
                    REFERENCES tour_departures(id)
            )
        """)
        booking_columns = [
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(bookings)"
            ).fetchall()
        ]

        if "user_id" not in booking_columns:
            connection.execute(
                """
                ALTER TABLE bookings
                ADD COLUMN user_id INTEGER REFERENCES users(id)
                """
            )

        departure_count = connection.execute(
            "SELECT COUNT(*) FROM tour_departures"
        ).fetchone()[0]

        if departure_count == 0:

            planina = connection.execute(
                "SELECT id FROM tours WHERE code = 'planina'"
            ).fetchone()

            if planina is not None:

                connection.executemany(
                    """
                    INSERT INTO tour_departures
                        (tour_id, departure_date, capacity)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (planina["id"], "2026-11-15", 10),
                        (planina["id"], "2026-11-22", 10),
                        (planina["id"], "2026-11-29", 10)
                    ]
                )


init_db()


def migrate_ownership():
    with get_connection() as connection:
        tour_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(tours)"
            ).fetchall()
        }

        if "operator_id" not in tour_columns:
            connection.execute(
                "ALTER TABLE tours "
                "ADD COLUMN operator_id INTEGER"
            )

        booking_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(bookings)"
            ).fetchall()
        }

        if "public_user_id" not in booking_columns:
            connection.execute(
                "ALTER TABLE bookings "
                "ADD COLUMN public_user_id INTEGER"
            )
migrate_ownership()

# =====================================================
# HOME PAGE
# =====================================================

@app.route("/")
def home():

    with get_connection() as connection:
        tours = connection.execute(
            """
            SELECT *
            FROM tours
            WHERE is_active = 1
            ORDER BY id
            """
        ).fetchall()

    return render_template("index.html", tours=tours)


# =====================================================
# TOUR DETAILS
# =====================================================

@app.route("/tours/<int:tour_id>")
def tour_detail(tour_id):

    with get_connection() as connection:

        tour = connection.execute(
            """
            SELECT *
            FROM tours
            WHERE id = ? AND is_active = 1
            """,
            (tour_id,)
        ).fetchone()

        if tour is None:
            return "Офертата не е намерена.", 404

        departures = connection.execute(
            """
            SELECT
                d.id,
                d.departure_date,
                d.capacity,
                d.capacity - COALESCE(
                    SUM(
                        CASE
                            WHEN b.status = 'CONFIRMED'
                            THEN b.participants
                            ELSE 0
                        END
                    ), 0
                ) AS available
            FROM tour_departures AS d
            LEFT JOIN bookings AS b
                ON b.departure_id = d.id
            WHERE d.tour_id = ?
              AND d.is_active = 1
            GROUP BY d.id
            ORDER BY d.departure_date
            """,
            (tour_id,)
        ).fetchall()

    return render_template(
        "tour_detail.html",
        tour=tour,
        departures=departures
    )


# =====================================================
# API TOURS
# =====================================================

@app.route("/api/tours")
def get_tours():

    with get_connection() as connection:
        tours = connection.execute(
            """
            SELECT code AS id, name, price
            FROM tours
            WHERE is_active = 1
            ORDER BY id
            """
        ).fetchall()

    return [
        {
            "id": tour["id"],
            "name": tour["name"],
            "price": tour["price"]
        }
        for tour in tours
    ]


# =====================================================
# NEW BOOKING REQUEST
# =====================================================

@app.route("/booking", methods=["POST"])
def booking():
    validate_csrf()

    customer_name = request.form.get(
        "customer_name", ""
    ).strip()

    email = request.form.get(
        "email", ""
    ).strip()

    phone = request.form.get(
        "phone", ""
    ).strip()

    fitness_level = request.form.get(
        "fitness_level", ""
    ).strip()

    preferred_date = request.form.get(
        "preferred_date", ""
    ).strip()

    notes = request.form.get(
        "notes", ""
    ).strip()

    tour_id = request.form.get(
        "tour_id", ""
    ).strip()

    try:
        participants = int(
            request.form.get("participants", "")
        )
    except ValueError:
        return "Невалидни данни.", 400

    if not customer_name or "@" not in email:
        return "Проверете името и e-mail.", 400

    if not 1 <= participants <= 10:
        return "Участниците трябва да са между 1 и 10.", 400

    if not preferred_date:
        return "Моля, изберете предпочитана дата.", 400

    with get_connection() as connection:

        tour = connection.execute(
            """
            SELECT id
            FROM tours
            WHERE code = ? AND is_active = 1
            """,
            (tour_id,)
        ).fetchone()

        if tour is None:
            return "Офертата не съществува.", 400

        connection.execute(
            """
            INSERT INTO booking_requests (
                tour_id,
                customer_name,
                email,
                phone,
                participants,
                fitness_level,
                preferred_date,
                notes,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """,
            (
                tour["id"],
                customer_name,
                email,
                phone,
                participants,
                fitness_level,
                preferred_date,
                notes
            )
        )

    return render_template("booking_success.html")


# =====================================================
# LEGACY BOOKING CREATE
# =====================================================

@app.route("/bookings/new", methods=["POST"])
@role_required("public")
def booking_create():
    validate_csrf()

    public_user_id = session["user_id"]

    customer_name = request.form.get(
        "customer_name", ""
    ).strip()

    email = request.form.get(
        "email", ""
    ).strip()

    try:
        departure_id = int(
            request.form.get("departure_id", "")
        )

        participants = int(
            request.form.get("participants", "")
        )

    except ValueError:
        return "Невалидни данни.", 400

    if not customer_name or "@" not in email:
        return "Проверете името и e-mail.", 400

    if participants < 1:
        return "Броят на участниците трябва да е поне 1.", 400

    with get_connection() as connection:

        departure = connection.execute(
            """
            SELECT id
            FROM tour_departures
            WHERE id = ? AND is_active = 1
            """,
            (departure_id,)
        ).fetchone()

        if departure is None:
            return "Избраната дата не е налична.", 400

        connection.execute(
            """
          INSERT INTO bookings (
    public_user_id,
    departure_id,
    customer_name,
    email,
    participants,
    status
)
VALUES (?, ?, ?, ?, ?, 'PENDING')
            """,
          (
    public_user_id,
    departure_id,
    customer_name,
    email,
    participants
)
        )

    return render_template("booking_success.html")


# =====================================================
# CUSTOMER BOOKINGS
# =====================================================


@app.route("/bookings")
@role_required("public")
def bookings():

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                b.id,
                b.customer_name,
                b.email,
                NULL AS phone,
                b.participants,
                NULL AS fitness_level,
                td.departure_date AS preferred_date,
                NULL AS notes,
                b.created_at,
                b.status,
                t.name AS tour_name,
                t.price
            FROM bookings AS b
            JOIN tour_departures AS td
                ON td.id = b.departure_id
            JOIN tours AS t
                ON t.id = td.tour_id
            WHERE b.public_user_id = ?
            ORDER BY b.id DESC
            """,
            (session["user_id"],)
        ).fetchall()

    return render_template(
        "bookings.html",
        bookings=rows
    )



# =====================================================
# ADMIN TOURS
# =====================================================

@app.route("/admin/tours")
@role_required("admin", "operator")
def admin_tours():
    with get_connection() as connection:
        if session["role"] == "admin":
            tours = connection.execute(
                "SELECT * FROM tours ORDER BY id"
            ).fetchall()
        else:
            tours = connection.execute(
                """
                SELECT *
                FROM tours
                WHERE operator_id = ?
                ORDER BY id
                """,
                (session["user_id"],)
            ).fetchall()

    return render_template(
        "admin_tours.html",
        tours=tours
    )
            

@app.route("/admin/users")
@role_required("admin")
def admin_users():
    with get_connection() as connection:
        users = connection.execute(
            """
            SELECT id, username, email, role, status
            FROM users
            ORDER BY id DESC
            """
        ).fetchall()

    return render_template(
        "admin_users.html",
        users=users
    )

# =====================================================
# CREATE TOUR
# =====================================================


@app.route("/admin/tours/new", methods=["GET", "POST"])
@role_required("admin", "operator")
def tour_create():

    if request.method == "GET":
        return render_template("tour_form.html", tour=None)

    validate_csrf()

    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    map_query = request.form.get("map_query", "").strip()

    try:
        price = float(request.form.get("price", ""))
        capacity = int(request.form.get("capacity", ""))

        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()

        latitude = float(latitude_raw) if latitude_raw else None
        longitude = float(longitude_raw) if longitude_raw else None

    except ValueError:
        return "Проверете цена, капацитет и координати.", 400

    if not code or not name or not location or not description:
        return "Всички основни текстови полета са задължителни.", 400

    if price < 0 or capacity < 1:
        return "Невалидна цена или капацитет.", 400

    if session["role"] == "operator":
        operator_id = session["user_id"]
    else:
        operator_id = request.form.get("operator_id") or None

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO tours (
                operator_id,
                code, name, location, description,
                price, capacity,
                latitude, longitude, map_query,
                image_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operator_id,
                code, name, location, description,
                price, capacity,
                latitude, longitude, map_query,
                request.form.get("image_url", "").strip()
            )
        )

    return redirect(url_for("admin_tours"))



# =====================================================
# EDIT TOUR
# =====================================================

@app.route("/admin/tours/<int:tour_id>/edit", methods=["GET", "POST"])
@role_required("admin", "operator")
def tour_edit(tour_id):

    with get_connection() as connection:
        tour = connection.execute(
            """
            SELECT *
            FROM tours
            WHERE id = ?
            """,
            (tour_id,)
        ).fetchone()

    if tour is None:
        return "Офертата не е намерена.", 404

    if (
        session["role"] == "operator"
        and tour["operator_id"] != session["user_id"]
    ):
        abort(403)

    if request.method == "GET":
        return render_template("tour_form.html", tour=tour)

    validate_csrf()

    code = request.form.get("code", "").strip()
    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    map_query = request.form.get("map_query", "").strip()
    image_url = request.form.get("image_url", "").strip()

    try:
        price = float(request.form.get("price", ""))
        capacity = int(request.form.get("capacity", ""))

        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()

        latitude = float(latitude_raw) if latitude_raw else None
        longitude = float(longitude_raw) if longitude_raw else None

    except ValueError:
        return "Проверете цена, капацитет и координати.", 400

    if not code or not name or not location or not description:
        return "Всички основни текстови полета са задължителни.", 400

    if price < 0 or capacity < 1:
        return "Невалидна цена или капацитет.", 400

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE tours
            SET code = ?,
                name = ?,
                location = ?,
                description = ?,
                price = ?,
                capacity = ?,
                latitude = ?,
                longitude = ?,
                map_query = ?,
                image_url = ?
            WHERE id = ?
            """,
            (
                code,
                name,
                location,
                description,
                price,
                capacity,
                latitude,
                longitude,
                map_query,
                image_url,
                tour_id
            )
        )

    return redirect(url_for("admin_tours"))


# =====================================================
# DEACTIVATE TOUR
# =====================================================

@app.route("/admin/tours/<int:tour_id>/deactivate", methods=["POST"])
@role_required("admin")
def tour_deactivate(tour_id):
    validate_csrf()
    

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE tours
            SET is_active = 0
            WHERE id = ?
            """,
            (tour_id,)
        )

    return redirect(url_for("admin_tours"))


# =====================================================
# CLEAR CUSTOMER BOOKINGS
# =====================================================

@app.route("/bookings/clear", methods=["POST"])
def clear_bookings():
    validate_csrf()

    with get_connection() as connection:
        connection.execute(
            "DELETE FROM booking_requests"
        )

    return render_template("booking_success.html")


# =====================================================
# ADMIN BOOKINGS TABLE
# =====================================================

@app.route("/admin/bookings")
@role_required("admin")
def booking_list():

    with get_connection() as connection:

        bookings = connection.execute(
            """
            SELECT
                br.id,
                br.customer_name,
                br.email,
                br.phone,
                br.participants,
                br.fitness_level,
                br.preferred_date,
                br.notes,
                br.created_at,
                br.status,
                t.name AS tour_name,
                t.location,
                t.latitude,
                t.longitude,
                t.map_query,
                t.price
            FROM booking_requests AS br
            JOIN tours AS t
                ON t.id = br.tour_id
            ORDER BY br.id DESC
            """
        ).fetchall()

    return render_template(
        "admin_bookings.html",
        bookings=bookings
    )


# =====================================================
# CONFIRM BOOKING REQUEST
# =====================================================

@app.route(
    "/admin/bookings/<int:booking_id>/confirm",
    methods=["POST"]
)
@role_required("admin")
def booking_confirm(booking_id):
    validate_csrf()
    

    with get_connection() as connection:

        booking = connection.execute(
            """
            SELECT
                id,
                tour_id,
                preferred_date,
                participants,
                status
            FROM booking_requests
            WHERE id = ?
            """,
            (booking_id,)
        ).fetchone()

        if booking is None:
            return "Заявката не е намерена.", 404

        if booking["status"] != "PENDING":
            return "Само чакащи заявки могат да бъдат потвърдени.", 400

        available = get_available_request_capacity(
            connection,
            booking["tour_id"],
            booking["preferred_date"]
        )

        if booking["participants"] > available:
            return "Недостатъчен свободен капацитет.", 400

        connection.execute(
            """
            UPDATE booking_requests
            SET status = 'CONFIRMED'
            WHERE id = ?
            """,
            (booking_id,)
        )

    return redirect(url_for("booking_list"))


# =====================================================
# CANCEL BOOKING REQUEST
# =====================================================

@app.route(
    "/admin/bookings/<int:booking_id>/cancel",
    methods=["POST"]
)
@role_required("admin")
def booking_cancel(booking_id):
    validate_csrf()

    with get_connection() as connection:

        booking = connection.execute(
            """
            SELECT id, status
            FROM booking_requests
            WHERE id = ?
            """,
            (booking_id,)
        ).fetchone()

        if booking is None:
            return "Заявката не е намерена.", 404

        if booking["status"] == "CANCELLED":
            return "Заявката вече е отказана.", 400

        connection.execute(
            """
            UPDATE booking_requests
            SET status = 'CANCELLED'
            WHERE id = ?
            """,
            (booking_id,)
        )

    return redirect(url_for("booking_list"))



@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    validate_csrf()

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    with get_connection() as connection:
        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
              AND status = 'ACTIVE'
            """,
            (username,)
        ).fetchone()

    if user is None:
        return "Невалидно потребителско име или парола.", 401

    if not check_password_hash(
        user["password_hash"],
        password
    ):
        return "Невалидно потребителско име или парола.", 401

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]

    if user["role"] == "public":
        return redirect(url_for("home"))

    return redirect(url_for("admin_tours"))


@app.route("/logout", methods=["POST"])
def logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("home"))

@app.route("/register", methods=["GET", "POST"])
def register_public():
    if request.method == "GET":
        return render_template("register_public.html")

    validate_csrf()

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not username or "@" not in email or len(password) < 8:
        return "Проверете регистрационните данни.", 400


    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users
                (username, email, password_hash, role, status)
            VALUES (?, ?, ?, 'public', 'ACTIVE')
            """,
            (
                username,
                email,
                generate_password_hash(password)
            )
        )

    return redirect(url_for("login"))


@app.route("/operator/register", methods=["GET", "POST"])
def register_operator():
    if request.method == "GET":
        return render_template("register_operator.html")

    validate_csrf()

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not username or "@" not in email or len(password) < 8:
        return "Проверете регистрационните данни.", 400

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users
                (username, email, password_hash, role, status)
            VALUES (?, ?, ?, 'operator', 'PENDING_APPROVAL')
            """,
            (
                username,
                email,
                generate_password_hash(password)
            )
        )

    return "Регистрацията е получена и очаква одобрение от администратор."

@app.route(
    "/admin/users/<int:user_id>/approve",
    methods=["POST"]
)
@role_required("admin")
def approve_operator(user_id):
    validate_csrf()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET status = 'ACTIVE'
            WHERE id = ?
              AND role = 'operator'
              AND status = 'PENDING_APPROVAL'
            """,
            (user_id,)
        )

    return redirect(url_for("admin_users"))

# =====================================================
# RUN FLASK
# =====================================================

if __name__ == "__main__":
    app.run(debug=True)
