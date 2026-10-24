#!/usr/bin/env python3
"""Smart Attendance server: serves the web app and stores its data in MongoDB Atlas.
Setup:  pip install -r requirements.txt
Run:    python server.py
Then open http://localhost:8000
"""
import base64, hashlib, json, os, secrets, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pymongo import MongoClient
from dotenv import load_dotenv

# Load local environment variables from .env
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

HERE = os.path.dirname(os.path.abspath(__file__))
MONGODB_URI = os.environ.get("MONGODB_URI", "")
DB_NAME = os.environ.get("MONGODB_DB", "smart_attendance")
HOST = os.environ.get("HOST", "0.0.0.0")          # 0.0.0.0 for hosting / LAN access
PORT = int(os.environ.get("PORT", "8000"))
LOCK = threading.Lock()
COLS = ("institutes", "users", "sections", "subjects", "students", "schedule", "settings")
CLIENT = None
SESSIONS = {}  # token -> user session dictionary

def get_db():
    global CLIENT
    if CLIENT is None:
        CLIENT = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=8000)
    return CLIENT, CLIENT[DB_NAME]

def J(v):
    return json.dumps(v, separators=(",", ":"))

def loads(s, default):
    try:
        v = json.loads(s)
        return default if v is None else v
    except Exception:
        return default

def doc(obj, pos=None, **more):
    d = dict(obj)
    d["_id"] = obj["id"]
    if pos is not None:
        d["_pos"] = pos
    d.update(more)
    return d

def clean(d, *drop):
    return {k: v for k, v in d.items() if k not in ("_id", "_pos") + drop}

def hash_pw(pw, salt):
    try:
        return hashlib.sha256(f"{salt}:{pw}".encode()).hexdigest()
    except Exception:
        return ""

# ---------- browser state -> MongoDB documents ----------
def save_state(st):
    g = lambda k, d: loads(st.get(k), d)
    subjects, sections, students = g("sa_subjects", []), g("sa_sections", []), g("sa_students", [])
    sched, att, users, insts = g("sa_sched", []), g("sa_att4", {}), g("sa_users", []), g("sa_insts", [])
    cur = st.get("sa_inst") or ""
    names = list(insts)
    if cur and cur.lower() not in [n.lower() for n in names]:
        names.append(cur)
    seen, inst_docs = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            inst_docs.append({"_id": n.lower(), "name": n, "is_current": n.lower() == cur.lower(), "_pos": len(inst_docs)})
    new = {
        "institutes": inst_docs,
        "subjects": [doc(s, i) for i, s in enumerate(subjects)],
        "sections": [doc(s, i) for i, s in enumerate(sections)],
        "students": [doc(s, i) for i, s in enumerate(students)],
        "schedule": [doc(x, i, held=isinstance(att.get(x["id"]), list),
                         present=sorted(set(att.get(x["id"]) or []))) for i, x in enumerate(sched)],
        "users": [doc(u, i) for i, u in enumerate(users)],
        "settings": [{"_id": k, "value": st[k]} for k in ("sa_cursec", "sa_cards") if k in st],
    }
    client, db = get_db()

    def txn(session):
        for name in COLS:
            db[name].delete_many({}, session=session)
            if new[name]:
                db[name].insert_many(new[name], session=session)
    with client.start_session() as s:
        s.with_transaction(txn)          # all or nothing

# ---------- MongoDB documents -> browser state ----------
def load_state():
    _, db = get_db()
    rows = {n: list(db[n].find({})) for n in COLS}
    if not any(rows[n] for n in COLS if n != "settings"):
        return None
    srt = lambda n: sorted(rows[n], key=lambda d: d.get("_pos", 0))
    sched, att = [], {}
    for d in srt("schedule"):
        sched.append(clean(d, "held", "present"))
        if d.get("held"):
            att[d["id"]] = list(d.get("present", []))
    insts = srt("institutes")
    st = {
        "sa_subjects": J([clean(d) for d in srt("subjects")]),
        "sa_sections": J([clean(d) for d in srt("sections")]),
        "sa_students": J([clean(d) for d in srt("students")]),
        "sa_sched": J(sched), "sa_att4": J(att),
        "sa_users": J([clean(d) for d in srt("users")]),
        "sa_insts": J([d["name"] for d in insts]),
        "sa_inst": next((d["name"] for d in insts if d.get("is_current")), ""),
    }
    for d in rows["settings"]:
        st[d["_id"]] = d["value"]
    return st

class H(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        path = self.path.split("?")[0]

        # Health & Status endpoint (Always open for monitoring)
        if path in ("/api/status", "/api/health"):
            try:
                t0 = time.time()
                client, db = get_db()
                db.command("ping")
                latency_ms = round((time.time() - t0) * 1000, 1)
                counts = {}
                for col in COLS:
                    counts[col] = db[col].count_documents({})
                return self._send(200, J({
                    "ok": True,
                    "connected": True,
                    "database": DB_NAME,
                    "latencyMs": latency_ms,
                    "counts": counts,
                    "totalDocs": sum(counts.values()),
                    "collections": list(db.list_collection_names())
                }).encode())
            except Exception as e:
                return self._send(503, J({"ok": False, "connected": False, "error": str(e)}).encode())

        # Current user profile endpoint
        if path == "/api/auth/me":
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                tok = auth[7:].strip()
                if tok in SESSIONS:
                    return self._send(200, J({"ok": True, "user": SESSIONS[tok]}).encode())
            return self._send(401, J({"ok": False, "error": "Not authenticated"}).encode())

        # State sync endpoint
        if path == "/api/state":
            try:
                with LOCK:
                    st = load_state()
                return self._send(200, J({"empty": st is None, "state": st or {}}).encode())
            except Exception as e:
                return self._send(503, J({"error": "database: " + str(e)}).encode())

        # Web Application HTML Page (Served cleanly without any browser HTTP basic auth prompt)
        if path in ("/", "/index.html", "/smart_attendance.html"):
            return self._send(200, open(os.path.join(HERE, "smart_attendance.html"), "rb").read(), "text/html; charset=utf-8")

        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
        except Exception:
            body = {}

        # Teacher / Student Web Login
        if path == "/api/auth/login":
            role = body.get("role", "teacher")
            try:
                _, db = get_db()
                if role == "teacher":
                    username = str(body.get("username", "")).strip().lower()
                    password = str(body.get("password", ""))
                    if not username or not password:
                        return self._send(400, J({"ok": False, "error": "Username and password are required."}).encode())

                    u = db.users.find_one({"role": "teacher", "username": username})

                    # If no teacher accounts exist yet in MongoDB, bootstrap the initial administrator account
                    if not u and username == "admin":
                        if db.users.count_documents({"role": "teacher"}) == 0:
                            salt = "smartattendance"
                            h = hash_pw(password, salt)
                            u = {"_id": "u_admin", "id": "u_admin", "role": "teacher", "username": "admin", "name": "Administrator", "salt": salt, "hash": h}
                            db.users.insert_one(u)
                            if db.institutes.count_documents({}) == 0:
                                db.institutes.insert_one({"_id": "smart institute", "name": "Smart Institute", "is_current": True, "_pos": 0})

                    if not u:
                        return self._send(401, J({"ok": False, "error": "No teacher account found with that username."}).encode())

                    if hash_pw(password, u.get("salt", "")) != u.get("hash"):
                        return self._send(401, J({"ok": False, "error": "Incorrect password. Please try again."}).encode())

                    token = secrets.token_hex(24)
                    sess_user = {"id": u["id"], "name": u.get("name", "Teacher"), "role": "teacher", "username": u["username"]}
                    SESSIONS[token] = sess_user
                    return self._send(200, J({"ok": True, "token": token, "user": sess_user}).encode())

                elif role == "student":
                    sec_id = str(body.get("section", "")).strip()
                    roll = str(body.get("roll", "")).strip().lower()
                    password = str(body.get("password", ""))
                    if not sec_id or not roll or not password:
                        return self._send(400, J({"ok": False, "error": "Please select your section and enter your roll number and password."}).encode())

                    stu = db.students.find_one({"sec": sec_id, "roll": {"$regex": f"^{roll}$", "$options": "i"}})
                    if not stu:
                        return self._send(401, J({"ok": False, "error": "No student found with that roll number in the selected section."}).encode())

                    u = db.users.find_one({"role": "student", "studentId": stu["id"]})
                    if not u or hash_pw(password, u.get("salt", "")) != u.get("hash"):
                        return self._send(401, J({"ok": False, "error": "Incorrect password. Please try again."}).encode())

                    token = secrets.token_hex(24)
                    sess_user = {"id": u["id"], "studentId": stu["id"], "name": stu["name"], "role": "student", "sec": stu["sec"], "roll": stu.get("roll", "")}
                    SESSIONS[token] = sess_user
                    return self._send(200, J({"ok": True, "token": token, "user": sess_user}).encode())

            except Exception as e:
                return self._send(500, J({"ok": False, "error": "Database error: " + str(e)}).encode())

        # Teacher Web Registration
        if path == "/api/auth/register":
            name = str(body.get("name", "")).strip()
            username = str(body.get("username", "")).strip().lower()
            password = str(body.get("password", ""))
            if not name or not username or not password:
                return self._send(400, J({"ok": False, "error": "Please fill in your full name, username, and password."}).encode())
            if len(password) < 4:
                return self._send(400, J({"ok": False, "error": "Password must be at least 4 characters."}).encode())

            try:
                _, db = get_db()
                if db.users.find_one({"role": "teacher", "username": username}):
                    return self._send(400, J({"ok": False, "error": "That username is already taken. Please choose another."}).encode())

                salt = secrets.token_hex(8)
                h = hash_pw(password, salt)
                uid = "u" + str(int(time.time() * 1000)) + secrets.token_hex(2)
                user_doc = {"_id": uid, "id": uid, "role": "teacher", "username": username, "name": name, "salt": salt, "hash": h}
                db.users.insert_one(user_doc)

                token = secrets.token_hex(24)
                sess_user = {"id": uid, "name": name, "role": "teacher", "username": username}
                SESSIONS[token] = sess_user
                return self._send(200, J({"ok": True, "token": token, "user": sess_user}).encode())
            except Exception as e:
                return self._send(500, J({"ok": False, "error": "Database error: " + str(e)}).encode())

        # Web Logout
        if path == "/api/auth/logout":
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                tok = auth[7:].strip()
                SESSIONS.pop(tok, None)
            return self._send(200, b'{"ok":true}')

        self._send(404, b'{"error":"not found"}')

    def do_PUT(self):
        if self.path.split("?")[0] != "/api/state":
            return self._send(404, b'{"error":"not found"}')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            with LOCK:
                save_state(body)
            self._send(200, b'{"ok":true}')
        except Exception as e:
            self._send(400, J({"error": str(e)}).encode())

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    if not MONGODB_URI:
        sys.exit('Set MONGODB_URI first in .env, e.g. MONGODB_URI="mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/" python server.py')
    try:
        _, db = get_db()
        db.command("ping")
        print("Connected to MongoDB Atlas, database:", DB_NAME)
    except Exception as e:
        sys.exit("Could not connect to MongoDB: %s\nCheck connection string and Network Access in Atlas." % e)
    print(f"Smart Attendance running at http://{'localhost' if HOST == '127.0.0.1' else HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
