from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)

DATABASE = "rewards.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            points INTEGER DEFAULT 0,
            lifetime_points INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL DEFAULT 0,
            points INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(member_id) REFERENCES members(id)
        )
    """)

    # Important for fast phone-number lookup
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_members_phone
        ON members(phone)
    """)

    conn.commit()
    conn.close()


def get_tier(lifetime_points):
    if lifetime_points >= 1000:
        return "Gold"
    elif lifetime_points >= 500:
        return "Silver"
    return "Regular"


def get_multiplier(tier):
    if tier == "Gold":
        return 2
    elif tier == "Silver":
        return 1.5
    return 1


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/member/<phone>")
def find_member(phone):
    conn = get_db()

    member = conn.execute(
        "SELECT * FROM members WHERE phone = ?",
        (phone,)
    ).fetchone()

    conn.close()

    if not member:
        return jsonify({
            "success": False,
            "message": "Member not found"
        }), 404

    member = dict(member)
    member["tier"] = get_tier(member["lifetime_points"])

    return jsonify({
        "success": True,
        "member": member
    })


@app.route("/api/member", methods=["POST"])
def create_member():
    data = request.json

    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()

    if not name or not phone:
        return jsonify({
            "success": False,
            "message": "Name and phone are required"
        }), 400

    conn = get_db()

    try:
        cursor = conn.execute("""
            INSERT INTO members
            (name, phone, points, lifetime_points, created_at)
            VALUES (?, ?, 0, 0, ?)
        """, (
            name,
            phone,
            datetime.now().isoformat()
        ))

        conn.commit()

        member_id = cursor.lastrowid

        member = conn.execute(
            "SELECT * FROM members WHERE id = ?",
            (member_id,)
        ).fetchone()

        return jsonify({
            "success": True,
            "member": dict(member)
        })

    except sqlite3.IntegrityError:
        return jsonify({
            "success": False,
            "message": "Phone number already exists"
        }), 409

    finally:
        conn.close()


@app.route("/api/purchase", methods=["POST"])
def purchase():
    data = request.json

    phone = data.get("phone", "").strip()

    try:
        amount = float(data.get("amount", 0))
    except:
        return jsonify({
            "success": False,
            "message": "Invalid amount"
        }), 400

    if amount <= 0:
        return jsonify({
            "success": False,
            "message": "Amount must be greater than 0"
        }), 400

    conn = get_db()

    member = conn.execute(
        "SELECT * FROM members WHERE phone = ?",
        (phone,)
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({
            "success": False,
            "message": "Member not found"
        }), 404

    tier = get_tier(member["lifetime_points"])
    multiplier = get_multiplier(tier)

    # 1 point per ₹100 for Regular
    earned_points = int((amount / 100) * multiplier)

    new_points = member["points"] + earned_points
    new_lifetime_points = member["lifetime_points"] + earned_points

    conn.execute("""
        UPDATE members
        SET points = ?, lifetime_points = ?
        WHERE id = ?
    """, (
        new_points,
        new_lifetime_points,
        member["id"]
    ))

    conn.execute("""
        INSERT INTO transactions
        (member_id, type, amount, points, created_at)
        VALUES (?, 'purchase', ?, ?, ?)
    """, (
        member["id"],
        amount,
        earned_points,
        datetime.now().isoformat()
    ))

    conn.commit()

    updated_member = conn.execute(
        "SELECT * FROM members WHERE id = ?",
        (member["id"],)
    ).fetchone()

    conn.close()

    updated_member = dict(updated_member)
    updated_member["tier"] = get_tier(
        updated_member["lifetime_points"]
    )

    return jsonify({
        "success": True,
        "earned_points": earned_points,
        "member": updated_member
    })


@app.route("/api/redeem", methods=["POST"])
def redeem():
    data = request.json

    phone = data.get("phone", "").strip()

    try:
        points = int(data.get("points", 0))
    except:
        return jsonify({
            "success": False,
            "message": "Invalid points"
        }), 400

    if points <= 0:
        return jsonify({
            "success": False,
            "message": "Points must be greater than 0"
        }), 400

    conn = get_db()

    member = conn.execute(
        "SELECT * FROM members WHERE phone = ?",
        (phone,)
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({
            "success": False,
            "message": "Member not found"
        }), 404

    if member["points"] < points:
        conn.close()
        return jsonify({
            "success": False,
            "message": "Insufficient points"
        }), 400

    new_balance = member["points"] - points

    conn.execute("""
        UPDATE members
        SET points = ?
        WHERE id = ?
    """, (
        new_balance,
        member["id"]
    ))

    conn.execute("""
        INSERT INTO transactions
        (member_id, type, amount, points, created_at)
        VALUES (?, 'redemption', 0, ?, ?)
    """, (
        member["id"],
        -points,
        datetime.now().isoformat()
    ))

    conn.commit()

    updated_member = conn.execute(
        "SELECT * FROM members WHERE id = ?",
        (member["id"],)
    ).fetchone()

    conn.close()

    updated_member = dict(updated_member)
    updated_member["tier"] = get_tier(
        updated_member["lifetime_points"]
    )

    return jsonify({
        "success": True,
        "redeemed_points": points,
        "member": updated_member
    })


@app.route("/api/member/<phone>/transactions")
def transactions(phone):
    conn = get_db()

    member = conn.execute(
        "SELECT id FROM members WHERE phone = ?",
        (phone,)
    ).fetchone()

    if not member:
        conn.close()
        return jsonify([])

    rows = conn.execute("""
        SELECT type, amount, points, created_at
        FROM transactions
        WHERE member_id = ?
        ORDER BY id DESC
    """, (member["id"],)).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)