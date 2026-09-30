"""Dedicated chatbot database - FAQ/knowledge base only. No user credentials."""
import os
import sqlite3
import re
from difflib import SequenceMatcher
from flask import g

CHATBOT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chatbot.db')


def get_chatbot_db():
    """Get connection to chatbot.db (separate from main app DB)."""
    if 'chatbot_db' not in g:
        g.chatbot_db = sqlite3.connect(CHATBOT_DB)
        g.chatbot_db.row_factory = sqlite3.Row
    return g.chatbot_db


def close_chatbot_db(exception=None):
    db = g.pop('chatbot_db', None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_chatbot_db)
    init_chatbot_db()


def init_chatbot_db():
    """Create chatbot_kb and chatbot_teachers tables. Seed defaults if empty."""
    conn = sqlite3.connect(CHATBOT_DB)
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chatbot_kb (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            category TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chatbot_teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            department TEXT,
            office_number TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Sync teachers from main DB on startup (no passwords - only name, email, dept, office)
    try:
        from core import db as main_db
        main_conn = sqlite3.connect(main_db.DATABASE)
        main_conn.row_factory = sqlite3.Row
        rows = main_conn.execute('''
            SELECT u.full_name, u.email, t.department, t.office_number
            FROM teachers t JOIN users u ON t.user_id = u.id
            WHERE u.email NOT LIKE '__unassigned__%'
        ''').fetchall()
        main_conn.close()
        conn.execute('DELETE FROM chatbot_teachers')
        for r in rows:
            conn.execute('''
                INSERT INTO chatbot_teachers (full_name, email, department, office_number)
                VALUES (?, ?, ?, ?)
            ''', (r['full_name'], r['email'], r['department'], r['office_number']))
    except Exception:
        pass
    conn.commit()
    # FTS5 for keyword search (optional; falls back to LIKE if unavailable)
    try:
        conn.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS chatbot_kb_fts USING fts5(
                question, answer, content='chatbot_kb', content_rowid='id'
            )
        ''')
    except sqlite3.OperationalError:
        pass  # FTS5 might not be available
    defaults = [
        ("Where can I see my exam schedule?", "You can view your exam schedule in the Calendar. Go to Dashboard -> Calendar to see upcoming exams and deadlines.", "schedule"),
        ("How does cheating detection work?", "The platform uses AI-powered monitoring during exams. Cameras capture the exam session, and the system detects suspicious behavior like looking at phones or talking to others.", "cheating"),
        ("Where is the floor map?", "The Floor Map shows the building layout and classroom availability. Click Floor Map in the navigation to see which rooms are busy or free.", "floor_map"),
        ("How can I check today's schedule?", "Use the chatbot and ask: \"today's schedule\". The assistant can list your classes and exams happening today.", "schedule"),
        ("How can I list my courses?", "Use the chatbot command \"my courses\" or \"list my courses\" to see your enrolled/assigned courses.", "courses"),
        ("Can the chatbot tell me who teaches a course?", "Yes. Ask \"who teaches CS101\" or \"find professor for CS101\" and the chatbot will return the instructor when available.", "courses"),
        ("How can I find an exam location?", "Ask the chatbot \"exam location for CS101\". If you do not specify a course, it can suggest your next exam room.", "exams"),
        ("How do I check room availability?", "Ask \"rooms available from 10:00 to 12:00\" to get free rooms for that time range.", "rooms"),
        ("How do I check room conflicts?", "Ask \"check room conflict 205 from 09:00 to 11:00\" to verify if a room is occupied.", "rooms"),
        ("Can I add events from the chatbot?", "Event creation through chatbot is disabled. Please use the Calendar page to add or edit events.", "calendar"),
        ("What can teachers do in the chatbot?", "Teachers can check upcoming exams/classes, list courses, get enrollment summaries, check room availability/conflicts, and view schedule-related info.", "teachers"),
        ("What can students do in the chatbot?", "Students can check today's schedule, upcoming exams/classes, list courses, find instructors, check exam locations, and query room availability/conflicts.", "students"),
        ("How do I open the chatbot knowledge base?", "Admins can open Dashboard -> Chatbot Knowledge Base to add, edit, or remove FAQ entries used by the assistant.", "admin"),
        ("What should I do if the chatbot does not understand my command?", "Try short, direct phrasing such as \"my courses\", \"today's schedule\", or \"exam location for CS101\".", "help"),
        ("How can I ask for upcoming exams?", "Try: \"upcoming exams\", \"next exam\", or \"show my exams\". The chatbot will list near-term exam events.", "exams"),
        ("How can I ask for upcoming classes?", "Try: \"upcoming classes\", \"my classes\", or \"what classes do I have\".", "schedule"),
        ("How do I ask for course schedule details?", "Ask: \"course schedule for CS101\" or \"when does CS101 meet\".", "courses"),
        ("Can I ask for announcements and reminders?", "Yes. Ask: \"announcements\" or \"show reminders\" to get upcoming items relevant to your role.", "announcements"),
        ("How can a teacher check enrollment count?", "Ask: \"How many students in CS101?\" to get enrolled count for your taught course.", "teachers"),
        ("How can a teacher list student names in a course?", "Ask: \"list students in CS101\" or \"student names in CS101\".", "teachers"),
        ("What if I do not include a course code?", "The chatbot may ask a follow-up like \"Which course?\". Add a course code such as CS101 for best results.", "help"),
        ("How do I ask for room availability with natural language?", "Try: \"Which rooms are available today from 2pm to 4pm?\" or \"rooms free tomorrow 10am to 12pm\".", "rooms"),
        ("How do I ask for room conflict checks with natural language?", "Try: \"Is room 1001 free tomorrow from 9am to 11am?\" or \"check room conflict for room 204 at 1pm\".", "rooms"),
        ("Can students modify exam events?", "No. Students can view schedules but cannot delete exam events.", "students"),
        ("How do I change theme or font?", "Open Settings -> UI Preferences to switch theme, font family, and reduced-motion mode.", "settings"),
        ("How do I update my profile info?", "Open Settings -> Profile Basics to update full name, contact email, display name, and profile photo URL.", "settings"),
        ("How do I update my password?", "Open Settings -> Password & Security, enter current password, then set and confirm a new password.", "settings"),
        ("How do I change calendar defaults?", "Open Settings -> Calendar Defaults to set default view (month/week) and time format (12h/24h).", "settings"),
        ("Who can access admin pages?", "Only users with admin role can access Users, Courses, Admin Calendar, and Chatbot KB management.", "admin"),
        ("What does the confidence and sources metadata mean?", "Chat responses may include confidence and source hints (calendar, database, kb, announcements) to show how the answer was produced.", "help"),
        ("How far ahead are upcoming events usually shown?", "By default, chatbot upcoming event summaries focus on near-term windows (for example, the next 14 days).", "schedule"),
        ("What should I do if data looks outdated?", "Refresh the page first. If the issue continues, verify your role/course assignments and check Calendar entries.", "help"),
        ("Can I ask the bot in plain English instead of command format?", "Yes. Natural phrasing is supported for many intents, including schedules, rooms, conflicts, and enrollment checks.", "help"),
        ("How do I find where my next exam is?", "Ask: \"Where is my next exam?\" or \"exam location for CS101\".", "exams"),
        ("How do I find who teaches my course?", "Ask: \"Who teaches CS101?\" or \"instructor for CS101\".", "courses"),
        ("What if room search returns no available rooms?", "It means all tracked rooms are occupied in the selected time range. Try a different time window.", "rooms"),
        ("Can teachers remove events from courses they do not teach?", "No. Teachers are restricted to deleting exams/course events for their own courses only.", "teachers"),
        ("Can admins delete exam events?", "No. Admins can manage global calendar events but cannot delete exam events.", "admin"),
    ]
    for q, a, c in defaults:
        conn.execute(
            '''
            INSERT INTO chatbot_kb (question, answer, category)
            SELECT ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM chatbot_kb WHERE question = ?
            )
            ''',
            (q, a, c, q)
        )
    conn.commit()
    conn.close()


def search_kb_ranked(user_message, limit=5):
    """Return ranked KB entries with relevance score in [0,1]."""
    db = get_chatbot_db()
    message = (user_message or "").strip()
    msg_l = message.lower()
    msg_tokens = [t for t in re.findall(r"[a-z0-9]+", msg_l) if len(t) > 2]
    rows = db.execute('SELECT id, question, answer, category FROM chatbot_kb').fetchall()
    ranked = []
    for r in rows:
        q = (r["question"] or "").strip()
        a = (r["answer"] or "").strip()
        blob = f"{q} {a}".lower()
        kb_tokens = set(t for t in re.findall(r"[a-z0-9]+", blob) if len(t) > 2)
        overlap = (len(set(msg_tokens) & kb_tokens) / max(1, len(set(msg_tokens)))) if msg_tokens else 0.0
        q_ratio = SequenceMatcher(None, msg_l, q.lower()).ratio() if q else 0.0
        c_ratio = SequenceMatcher(None, msg_l, blob[:220]).ratio() if blob else 0.0
        score = max(overlap * 0.65 + q_ratio * 0.35, q_ratio * 0.9, c_ratio * 0.7)
        if msg_l and msg_l in blob:
            score = max(score, 0.95)
        ranked.append({
            "id": r["id"],
            "question": q,
            "answer": a,
            "category": r["category"],
            "score": round(float(min(score, 1.0)), 4),
        })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[: max(1, int(limit))]


def search_kb(user_message, limit=5):
    """
    Search the knowledge base for entries relevant to the user message.
    Returns list of dicts with 'question' and 'answer'.
    """
    ranked = search_kb_ranked(user_message, limit=limit)
    return [{"question": r["question"], "answer": r["answer"]} for r in ranked]


def get_all_entries():
    """Return all KB entries for admin."""
    db = get_chatbot_db()
    return db.execute(
        'SELECT id, question, answer, category, created_at FROM chatbot_kb ORDER BY id'
    ).fetchall()


def add_entry(question, answer, category=None):
    """Add a KB entry. Returns new id or None."""
    db = get_chatbot_db()
    try:
        cursor = db.execute(
            'INSERT INTO chatbot_kb (question, answer, category) VALUES (?, ?, ?)',
            (question.strip(), answer.strip(), (category or '').strip() or None)
        )
        db.commit()
        return cursor.lastrowid
    except Exception:
        return None


def update_entry(entry_id, question, answer, category=None):
    """Update a KB entry. Returns True on success."""
    db = get_chatbot_db()
    try:
        db.execute(
            'UPDATE chatbot_kb SET question=?, answer=?, category=? WHERE id=?',
            (question.strip(), answer.strip(), (category or '').strip() or None, int(entry_id))
        )
        db.commit()
        return db.total_changes > 0
    except Exception:
        return False


def delete_entry(entry_id):
    """Delete a KB entry. Returns True on success."""
    db = get_chatbot_db()
    try:
        db.execute('DELETE FROM chatbot_kb WHERE id=?', (int(entry_id),))
        db.commit()
        return db.total_changes > 0
    except Exception:
        return False


# ============== Teacher sync (NO passwords - only name, email, department, office) ==============

def sync_teacher_upsert(full_name, email, department=None, office_number=None):
    """Insert or update a teacher in chatbot_db. Called when admin creates/edits a teacher."""
    db = get_chatbot_db()
    try:
        db.execute('''
            INSERT INTO chatbot_teachers (full_name, email, department, office_number, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(email) DO UPDATE SET
                full_name=excluded.full_name,
                department=excluded.department,
                office_number=excluded.office_number,
                updated_at=CURRENT_TIMESTAMP
        ''', (full_name.strip(), email.strip(), (department or '').strip() or None, (office_number or '').strip() or None))
        db.commit()
        return True
    except Exception:
        return False


def sync_teacher_remove(email):
    """Remove a teacher from chatbot_db. Called when admin deletes a teacher."""
    db = get_chatbot_db()
    try:
        db.execute('DELETE FROM chatbot_teachers WHERE email=?', (email.strip(),))
        db.commit()
        return True
    except Exception:
        return False


def get_teachers_for_rag():
    """Return all teachers as list of dicts for RAG context. NO passwords."""
    db = get_chatbot_db()
    rows = db.execute(
        'SELECT full_name, email, department, office_number FROM chatbot_teachers ORDER BY full_name'
    ).fetchall()
    return [dict(r) for r in rows]
