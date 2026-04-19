from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "railguard_secret"

DATABASE = "database.db"

# ---------------- DB SETUP ----------------
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # 🔥 FINAL TABLE WITH actual COLUMN
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            status TEXT,
            ear REAL,
            mar REAL,
            score REAL,
            actual TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

def db_query(sql, params=(), fetchone=False, commit=False):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(sql, params)

    if commit:
        conn.commit()
        conn.close()
        return None

    result = c.fetchone() if fetchone else c.fetchall()
    conn.close()
    return result

# ---------------- AUTH ----------------
VALID_USERS = {
    "admin": "railguard123",
    "driver": "driver123"
}

@app.route('/')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = request.form.get('username')
        pwd  = request.form.get('password')

        if user in VALID_USERS and VALID_USERS[user] == pwd:
            session['user'] = user
            return redirect(url_for('dashboard'))
        else:
            error = "Invalid credentials"

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------------- DASHBOARD ----------------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    logs = db_query("SELECT * FROM logs ORDER BY id DESC LIMIT 5")

    latest_status = logs[0]['status'] if logs else "NO DATA"
    latest_score  = logs[0]['score'] if logs else 100

    total_alerts = db_query(
        "SELECT COUNT(*) as c FROM logs WHERE status != 'SAFE'",
        fetchone=True
    )['c']

    return render_template(
        'dashboard.html',
        logs=logs,
        latest_status=latest_status,
        latest_score=latest_score,
        total_alerts=total_alerts
    )

# ---------------- LOG PAGE ----------------
@app.route('/logs')
def logs_page():
    if 'user' not in session:
        return redirect(url_for('login'))

    logs = db_query("SELECT * FROM logs ORDER BY id DESC LIMIT 200")
    return render_template('logs.html', logs=logs)

# ---------------- ANALYTICS ----------------
@app.route("/analytics")
def analytics():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT status, timestamp FROM logs
        ORDER BY id DESC LIMIT 100
    """).fetchall()

    rows = rows[::-1]

    counts = {
        "SAFE": 0,
        "YAWNING": 0,
        "DROWSY": 0,
        "HIGH RISK": 0,
        "CRITICAL": 0,
        "NO DRIVER": 0
    }

    timestamps = []
    values = []

    for r in rows:
        status = r["status"]

        if status in counts:
            counts[status] += 1

        timestamps.append(r["timestamp"] or "00:00:00")

        if status in ["DROWSY","HIGH RISK","CRITICAL"]:
            values.append(1)
        else:
            values.append(0)

    conn.close()

    return render_template(
        "analytics.html",
        counts=counts,
        timestamps=timestamps[-30:],
        values=values[-30:]
    )

# ---------------- LOG API ----------------
@app.route("/log", methods=["POST"])
def log():
    data = request.json

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO logs (timestamp, status, ear, mar, score, actual)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%H:%M:%S"),
        data.get("status"),
        data.get("ear"),
        data.get("mar"),
        data.get("score"),
        data.get("actual")   # 🔥 MUST COME FROM DETECTOR
    ))

    conn.commit()
    conn.close()

    return jsonify({"message": "logged"})

# ---------------- METRICS API ----------------
@app.route("/metrics")
def metrics():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT actual, status FROM logs
        WHERE actual IS NOT NULL
        ORDER BY id DESC LIMIT 200
    """).fetchall()

    TP = TN = FP = FN = 0

    for r in rows:
        actual = r["actual"]
        pred = r["status"]

        pred_label = "DROWSY" if pred in ["DROWSY","HIGH RISK","CRITICAL"] else "SAFE"

        if actual == "DROWSY" and pred_label == "DROWSY":
            TP += 1
        elif actual == "SAFE" and pred_label == "SAFE":
            TN += 1
        elif actual == "SAFE" and pred_label == "DROWSY":
            FP += 1
        elif actual == "DROWSY" and pred_label == "SAFE":
            FN += 1

    total = TP + TN + FP + FN

    accuracy  = (TP + TN) / total if total else 0
    precision = TP / (TP + FP) if (TP + FP) else 0
    recall    = TP / (TP + FN) if (TP + FN) else 0
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0

    conn.close()

    return jsonify({
        "TP": TP,
        "TN": TN,
        "FP": FP,
        "FN": FN,
        "accuracy": round(accuracy,3),
        "precision": round(precision,3),
        "recall": round(recall,3),
        "f1": round(f1,3)
    })

# ---------------- RUN ----------------
if __name__ == '__main__':
    app.run(debug=True, port=5000)