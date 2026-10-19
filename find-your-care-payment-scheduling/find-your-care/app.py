"""
Find Your Care - MVP Backend
==============================
A Flask + SQLite backend for a hackathon MVP that connects families
("Hirers") with verified, non-medical hospital caretakers/attendants
("Employees").

Run with:  python app.py
Then open: http://127.0.0.1:5000/
"""

import sqlite3
import os
from datetime import datetime, timedelta
from flask import (
    Flask, render_template, request, jsonify, session, redirect, url_for, g
)

# --------------------------------------------------------------------------
# App configuration
# --------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = "hackathon-demo-secret-key-change-in-production"  # session signing key

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "findyourcare.db")


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_db():
    """
    Returns a SQLite connection scoped to the current request context (g).
    row_factory=sqlite3.Row lets us access columns by name, which makes it
    trivial to convert rows to dicts for JSON responses.
    """
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    """Closes the DB connection at the end of every request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """
    Creates the caretakers and bookings tables if they don't already exist,
    then seeds four demo caretaker profiles the first time the app runs.
    This is intentionally idempotent so `python app.py` is always safe to run.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # Table 1: caretakers
    cur.execute("""
        CREATE TABLE IF NOT EXISTS caretakers (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT    NOT NULL,
            gender    TEXT    NOT NULL,               -- 'Male' or 'Female'
            age       INTEGER NOT NULL,
            rating    REAL    NOT NULL DEFAULT 4.5,
            verified  INTEGER NOT NULL DEFAULT 1,      -- 1 = verified, 0 = not
            status    TEXT    NOT NULL DEFAULT 'Available',  -- 'Available' | 'On-Duty'
            avatar    TEXT    NOT NULL DEFAULT '🧑'
        )
    """)

    # Table 2: bookings
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_name TEXT    NOT NULL,
            ward_bed      TEXT    NOT NULL,
            caretaker_id  INTEGER NOT NULL,
            hours         INTEGER NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'Confirmed',  -- Confirmed | Active | Completed
            scheduled_start TEXT NOT NULL DEFAULT '',
            payment_method TEXT NOT NULL DEFAULT 'Cash on arrival',
            payment_status TEXT NOT NULL DEFAULT 'Pending',
            amount        INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (caretaker_id) REFERENCES caretakers (id)
        )
    """)

    # Safe schema upgrades for existing demo databases.
    columns = {row[1] for row in cur.execute("PRAGMA table_info(bookings)").fetchall()}
    for column, declaration in [
        ("scheduled_start", "TEXT NOT NULL DEFAULT ''"),
        ("payment_method", "TEXT NOT NULL DEFAULT 'Cash on arrival'"),
        ("payment_status", "TEXT NOT NULL DEFAULT 'Pending'"),
        ("amount", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if column not in columns:
            cur.execute(f"ALTER TABLE bookings ADD COLUMN {column} {declaration}")
    conn.commit()

    # Seed caretakers only if the table is currently empty (idempotent seed)
    existing = cur.execute("SELECT COUNT(*) FROM caretakers").fetchone()[0]
    if existing == 0:
        demo_caretakers = [
            ("Priya Sharma",  "Female", 28, 4.8, 1, "Available", "👩‍⚕️"),
            ("Rajesh Kumar",  "Male",   45, 4.9, 1, "Available", "👨‍⚕️"),
            ("Anjali Verma",  "Female", 52, 4.7, 1, "Available", "👵"),
            ("Vikram Singh",  "Male",   34, 4.6, 1, "Available", "🧑"),
        ]
        cur.executemany(
            """INSERT INTO caretakers (name, gender, age, rating, verified, status, avatar)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            demo_caretakers
        )
        conn.commit()

    conn.close()


def row_to_dict(row):
    """Converts a sqlite3.Row into a plain dict (for JSON serialization)."""
    return {key: row[key] for key in row.keys()}


# --------------------------------------------------------------------------
# Auth / role helpers
# --------------------------------------------------------------------------
def require_role(role):
    """Returns True if the current session has the given role, else False."""
    return session.get("role") == role


# --------------------------------------------------------------------------
# PAGE ROUTES
# --------------------------------------------------------------------------
@app.route("/")
def login_page():
    """Landing page with the dual Hirer/Employee login card."""
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    """
    Hackathon-simplified auth: any username/password is accepted.
    We only care about which role the user selected. The role (and, for
    employees, a demo-assigned caretaker_id) is stored in the session so
    downstream pages know which view/data to render.
    """
    username = request.form.get("username", "").strip() or "Guest"
    role = request.form.get("role")  # 'hirer' or 'employee'

    if role not in ("hirer", "employee"):
        return redirect(url_for("login_page"))

    session["username"] = username
    session["role"] = role

    if role == "employee":
        # Demo simplification: for the hackathon we don't have per-employee
        # accounts, so we deterministically attach this employee session to
        # caretaker #1 (Priya Sharma) so the dashboard has real data to show.
        # In production this would come from a proper employee/caretaker
        # account link established at signup.
        db = get_db()
        caretaker = db.execute(
            "SELECT id FROM caretakers ORDER BY id LIMIT 1"
        ).fetchone()
        session["caretaker_id"] = caretaker["id"] if caretaker else None
        return redirect(url_for("employee_dashboard_page"))

    return redirect(url_for("hirer_dashboard_page"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/dashboard")
def hirer_dashboard_page():
    """Hirer search & booking view (index.html)."""
    if not require_role("hirer"):
        return redirect(url_for("login_page"))
    return render_template("index.html", username=session.get("username"))


@app.route("/employee")
def employee_dashboard_page():
    """Employee shift/task view (employee_dashboard.html)."""
    if not require_role("employee"):
        return redirect(url_for("login_page"))
    return render_template("employee_dashboard.html", username=session.get("username"))


@app.route("/tracker/<int:booking_id>")
def tracker_page(booking_id):
    """Live Care Tracker view for a specific booking."""
    if not require_role("hirer"):
        return redirect(url_for("login_page"))
    return render_template("tracker.html", booking_id=booking_id)


# --------------------------------------------------------------------------
# JSON API ROUTES
# --------------------------------------------------------------------------
@app.route("/api/search", methods=["POST"])
def api_search():
    """Find caretakers without an overlapping booking for the requested time."""
    data = request.get_json(silent=True) or {}
    gender = data.get("gender", "Any")
    age_group = data.get("age_group", "Any")
    try:
        start = datetime.fromisoformat(data.get("scheduled_start", ""))
        hours = int(data.get("hours", 0))
        if start < datetime.now() or not 1 <= hours <= 24:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Choose a future start time and duration from 1 to 24 hours."}), 400
    end = start + timedelta(hours=hours)
    query = "SELECT * FROM caretakers WHERE 1=1"
    params = []
    if gender in ("Male", "Female"):
        query += " AND gender = ?"; params.append(gender)
    if age_group == "Young":
        query += " AND age BETWEEN ? AND ?"; params.extend([20, 40])
    elif age_group == "Senior":
        query += " AND age >= ?"; params.append(40)
    query += " ORDER BY rating DESC"
    db = get_db()
    candidates = db.execute(query, params).fetchall()
    available = []
    for row in candidates:
        bookings = db.execute("""SELECT scheduled_start, hours FROM bookings
            WHERE caretaker_id = ? AND status != 'Completed' AND scheduled_start != ''""", (row['id'],)).fetchall()
        conflict = False
        for b in bookings:
            try:
                old_start = datetime.fromisoformat(b['scheduled_start'])
                old_end = old_start + timedelta(hours=int(b['hours']))
                if start < old_end and end > old_start:
                    conflict = True; break
            except (ValueError, TypeError):
                continue
        if not conflict:
            available.append(row_to_dict(row))
    return jsonify({"success": True, "count": len(available), "caretakers": available})

@app.route("/api/book", methods=["POST"])
def api_book():
    """Create a scheduled booking and record the selected demo payment method."""
    data = request.get_json(silent=True) or {}
    hospital_name = (data.get("hospital_name") or "").strip()
    ward_bed = (data.get("ward_bed") or "").strip()
    payment_method = data.get("payment_method", "Cash on arrival")
    try:
        caretaker_id = int(data.get("caretaker_id"))
        hours = int(data.get("hours"))
        scheduled_start = datetime.fromisoformat(data.get("scheduled_start", ""))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Please check the start time, duration, and caretaker."}), 400
    if not hospital_name or not ward_bed:
        return jsonify({"success": False, "error": "Hospital and ward/bed are required."}), 400
    if not 1 <= hours <= 24 or scheduled_start < datetime.now():
        return jsonify({"success": False, "error": "Choose a future start time and duration from 1 to 24 hours."}), 400
    allowed_methods = ("UPI (demo)", "Card (demo)", "Cash on arrival")
    if payment_method not in allowed_methods:
        return jsonify({"success": False, "error": "Choose a valid payment method."}), 400
    db = get_db()
    caretaker = db.execute("SELECT * FROM caretakers WHERE id = ?", (caretaker_id,)).fetchone()
    if caretaker is None:
        return jsonify({"success": False, "error": "Caretaker not found."}), 404
    end = scheduled_start + timedelta(hours=hours)
    existing = db.execute("""SELECT scheduled_start, hours FROM bookings
        WHERE caretaker_id = ? AND status != 'Completed' AND scheduled_start != ''""", (caretaker_id,)).fetchall()
    for b in existing:
        try:
            old_start = datetime.fromisoformat(b['scheduled_start'])
            old_end = old_start + timedelta(hours=int(b['hours']))
            if scheduled_start < old_end and end > old_start:
                return jsonify({"success": False, "error": "This caretaker has another booking during that time. Please choose another time or caretaker."}), 409
        except (ValueError, TypeError):
            continue
    amount = hours * 250
    # This hackathon build records a demo payment choice; it does not charge money.
    payment_status = "Pay on arrival" if payment_method == "Cash on arrival" else "Demo — not charged"
    cur = db.execute("""INSERT INTO bookings
        (hospital_name, ward_bed, caretaker_id, hours, status, scheduled_start, payment_method, payment_status, amount)
        VALUES (?, ?, ?, ?, 'Confirmed', ?, ?, ?, ?)""",
        (hospital_name, ward_bed, caretaker_id, hours, scheduled_start.isoformat(timespec='minutes'), payment_method, payment_status, amount))
    db.commit()
    return jsonify({"success": True, "booking_id": cur.lastrowid, "amount": amount, "payment_status": payment_status})

@app.route("/api/tracker/<int:booking_id>")
def api_tracker(booking_id):
    """Returns booking + caretaker details for the Live Care Tracker page."""
    db = get_db()
    row = db.execute("""
        SELECT bookings.id AS booking_id, bookings.hospital_name, bookings.ward_bed,
               bookings.hours, bookings.status, bookings.created_at,
               bookings.scheduled_start, bookings.payment_method, bookings.payment_status, bookings.amount,
               caretakers.name AS caretaker_name, caretakers.avatar, caretakers.rating
        FROM bookings
        JOIN caretakers ON caretakers.id = bookings.caretaker_id
        WHERE bookings.id = ?
    """, (booking_id,)).fetchone()

    if row is None:
        return jsonify({"success": False, "error": "Booking not found."}), 404

    return jsonify({"success": True, "booking": row_to_dict(row)})


@app.route("/api/employee/bookings")
def api_employee_bookings():
    """
    Returns the bookings currently assigned to the logged-in employee's
    caretaker profile, used to populate the Employee Dashboard task list.
    """
    if not require_role("employee"):
        return jsonify({"success": False, "error": "Not authorized."}), 403

    caretaker_id = session.get("caretaker_id")
    db = get_db()
    rows = db.execute("""
        SELECT bookings.id, bookings.hospital_name, bookings.ward_bed,
               bookings.hours, bookings.status, bookings.created_at, bookings.scheduled_start,
               bookings.payment_method, bookings.payment_status, bookings.amount
        FROM bookings
        WHERE bookings.caretaker_id = ?
        ORDER BY bookings.created_at DESC
    """, (caretaker_id,)).fetchall()

    return jsonify({"success": True, "bookings": [row_to_dict(r) for r in rows]})


@app.route("/api/employee/complete/<int:booking_id>", methods=["POST"])
def api_employee_complete(booking_id):
    """Marks a booking as Completed and frees the caretaker back to Available."""
    if not require_role("employee"):
        return jsonify({"success": False, "error": "Not authorized."}), 403

    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if booking is None:
        return jsonify({"success": False, "error": "Booking not found."}), 404

    db.execute("UPDATE bookings SET status = 'Completed' WHERE id = ?", (booking_id,))
    db.execute("UPDATE caretakers SET status = 'Available' WHERE id = ?", (booking["caretaker_id"],))
    db.commit()

    return jsonify({"success": True})


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
