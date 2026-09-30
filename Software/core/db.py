"""Database connection and query helpers."""
import os
import sqlite3
import hashlib
from datetime import datetime, timedelta
from flask import g

DATABASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'classroom_management.db')
UNASSIGNED_TEACHER_EMAIL = '__unassigned__@system.local'


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def get_user_by_email(email):
    db = get_db()
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    return db.execute("SELECT * FROM users WHERE LOWER(email) = ?", (normalized,)).fetchone()


def verify_login(email, password):
    user = get_user_by_email(email)
    if user and user['password'] == hash_password(password):
        return user
    return None


def get_user_by_id(user_id):
    db = get_db()
    return db.execute('SELECT * FROM users WHERE id = ?', (int(user_id),)).fetchone()


def init_user_preferences_table():
    """Create per-user settings table."""
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            profile_photo_url TEXT,
            ui_theme TEXT NOT NULL DEFAULT 'dark',
            ui_font TEXT NOT NULL DEFAULT 'dm',
            ui_reduced_motion INTEGER NOT NULL DEFAULT 0,
            calendar_default_view TEXT NOT NULL DEFAULT 'month',
            calendar_time_format TEXT NOT NULL DEFAULT '12h',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    db.commit()


def init_chat_feedback_table():
    """Create chatbot feedback table for review loop."""
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS chat_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            user_message TEXT NOT NULL,
            bot_reply TEXT NOT NULL,
            confidence TEXT,
            sources TEXT,
            feedback TEXT,
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    ''')
    db.commit()


def init_admin_audit_log_table():
    """Create admin audit table."""
    db = get_db()
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            details TEXT,
            outcome TEXT NOT NULL DEFAULT 'success',
            ip_address TEXT,
            user_agent TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        '''
    )
    db.commit()


def add_admin_audit_log(admin_user_id, action, target_type=None, target_id=None, details=None, outcome="success", ip_address=None, user_agent=None):
    db = get_db()
    db.execute(
        '''
        INSERT INTO admin_audit_log (
            admin_user_id, action, target_type, target_id, details, outcome, ip_address, user_agent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            int(admin_user_id) if admin_user_id else None,
            (action or "").strip() or "unknown",
            (target_type or "").strip() or None,
            str(target_id).strip() if target_id is not None else None,
            (details or "").strip() or None,
            (outcome or "").strip() or "success",
            (ip_address or "").strip() or None,
            (user_agent or "").strip() or None,
        ),
    )
    db.commit()


def add_chat_feedback(user_id, role, user_message, bot_reply, confidence=None, sources=None, feedback=None, note=None):
    """Insert one feedback/log row for chatbot quality review."""
    db = get_db()
    db.execute('''
        INSERT INTO chat_feedback (
            user_id, role, user_message, bot_reply, confidence, sources, feedback, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        int(user_id) if user_id else None,
        (role or '').strip() or None,
        (user_message or '').strip(),
        (bot_reply or '').strip(),
        (confidence or '').strip() or None,
        (sources or '').strip() or None,
        (feedback or '').strip() or None,
        (note or '').strip() or None,
    ))
    db.commit()
    row_id = db.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
    return row_id


def update_chat_feedback_vote(feedback_id, feedback, note=None):
    """Update vote/note for a previously logged chatbot row."""
    db = get_db()
    db.execute('''
        UPDATE chat_feedback
        SET feedback = ?, note = ?
        WHERE id = ?
    ''', (
        (feedback or '').strip() or None,
        (note or '').strip() or None,
        int(feedback_id),
    ))
    db.commit()
    return db.total_changes > 0


def update_chat_feedback_review(feedback_id, review_action, reviewed_by=None, review_note=None):
    """Update triage workflow for chatbot feedback."""
    action = (review_action or "").strip().lower()
    allowed = {"fixed_kb", "needs_intent", "needs_ui_flow", "ignore"}
    if action not in allowed:
        return False
    if action == "fixed_kb":
        status = "resolved"
    elif action in {"needs_intent", "needs_ui_flow"}:
        status = "triaged"
    else:
        status = "ignored"
    db = get_db()
    db.execute(
        '''
        UPDATE chat_feedback
        SET review_action = ?, review_status = ?, review_note = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        ''',
        (
            action,
            status,
            (review_note or "").strip() or None,
            int(reviewed_by) if reviewed_by else None,
            int(feedback_id),
        ),
    )
    db.commit()
    return db.total_changes > 0


def get_recent_chat_feedback(limit=200, only_negative=False):
    """Return recent chatbot rows where the user voted (up or down). Unvoted log rows are excluded."""
    db = get_db()
    base = '''
        SELECT cf.*, u.full_name, u.email
        FROM chat_feedback cf
        LEFT JOIN users u ON cf.user_id = u.id
    '''
    if only_negative:
        rows = db.execute(base + ' WHERE cf.feedback = ? ORDER BY cf.created_at DESC LIMIT ?', ('down', int(limit))).fetchall()
    else:
        rows = db.execute(
            base + " WHERE cf.feedback IN ('up', 'down') ORDER BY cf.created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return rows


def _ensure_user_preferences_row(user_id):
    db = get_db()
    row = db.execute('SELECT user_id FROM user_preferences WHERE user_id = ?', (int(user_id),)).fetchone()
    if not row:
        db.execute('INSERT INTO user_preferences (user_id) VALUES (?)', (int(user_id),))
        db.commit()


def get_user_preferences(user_id):
    _ensure_user_preferences_row(user_id)
    db = get_db()
    row = db.execute('''
        SELECT user_id, display_name, profile_photo_url, ui_theme, ui_font, ui_reduced_motion,
               calendar_default_view, calendar_time_format
        FROM user_preferences
        WHERE user_id = ?
    ''', (int(user_id),)).fetchone()
    return dict(row) if row else {}


def update_user_profile_basics(user_id, full_name, email, display_name=None, profile_photo_url=None):
    db = get_db()
    email = (email or '').strip().lower()
    full_name = (full_name or '').strip()
    if not full_name or not email:
        return False, "Full name and email are required."

    existing = db.execute(
        "SELECT id FROM users WHERE LOWER(email) = ? AND id != ?", (email, int(user_id))
    ).fetchone()
    if existing:
        return False, "Email is already used by another account."

    try:
        db.execute('UPDATE users SET full_name = ?, email = ? WHERE id = ?', (full_name, email, int(user_id)))
        _ensure_user_preferences_row(user_id)
        db.execute('''
            UPDATE user_preferences
            SET display_name = ?, profile_photo_url = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', ((display_name or '').strip() or None, (profile_photo_url or '').strip() or None, int(user_id)))
        db.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "Could not update profile due to a data conflict."


def update_user_password(user_id, current_password, new_password):
    user = get_user_by_id(user_id)
    if not user:
        return False, "User not found."
    if user['password'] != hash_password((current_password or '').strip()):
        return False, "Current password is incorrect."
    if not new_password or len(new_password.strip()) < 6:
        return False, "New password must be at least 6 characters."
    db = get_db()
    db.execute('UPDATE users SET password = ? WHERE id = ?', (hash_password(new_password.strip()), int(user_id)))
    db.commit()
    return True, None


def update_user_calendar_defaults(user_id, default_view='month', time_format='12h'):
    allowed_views = {'month', 'week'}
    allowed_time = {'12h', '24h'}
    view_val = default_view if default_view in allowed_views else 'month'
    time_val = time_format if time_format in allowed_time else '12h'
    db = get_db()
    _ensure_user_preferences_row(user_id)
    db.execute('''
        UPDATE user_preferences
        SET calendar_default_view = ?, calendar_time_format = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
    ''', (view_val, time_val, int(user_id)))
    db.commit()
    return True, None


def update_user_ui_preferences(user_id, theme='dark', font='dm', reduced_motion=False):
    allowed_themes = {'dark', 'light', 'system'}
    allowed_fonts = {'dm', 'inter', 'manrope', 'space'}
    theme_val = theme if theme in allowed_themes else 'dark'
    font_val = font if font in allowed_fonts else 'dm'
    reduced_val = 1 if reduced_motion else 0
    db = get_db()
    _ensure_user_preferences_row(user_id)
    db.execute('''
        UPDATE user_preferences
        SET ui_theme = ?, ui_font = ?, ui_reduced_motion = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
    ''', (theme_val, font_val, reduced_val, int(user_id)))
    db.commit()
    return True, None


def get_unassigned_teacher_id():
    db = get_db()
    u = db.execute('SELECT id FROM users WHERE email = ?', (UNASSIGNED_TEACHER_EMAIL,)).fetchone()
    if u:
        t = db.execute('SELECT id FROM teachers WHERE user_id = ?', (u['id'],)).fetchone()
        if t:
            return t['id']
    return None


def get_teacher_by_user_id(user_id):
    db = get_db()
    return db.execute('SELECT * FROM teachers WHERE user_id = ?', (user_id,)).fetchone()


def get_student_by_user_id(user_id):
    db = get_db()
    return db.execute('SELECT * FROM students WHERE user_id = ?', (user_id,)).fetchone()


def get_courses_by_teacher(teacher_id):
    db = get_db()
    return db.execute('SELECT * FROM courses WHERE teacher_id = ?', (teacher_id,)).fetchall()


def get_course_ids_for_student(student_id):
    db = get_db()
    rows = db.execute('SELECT course_id FROM course_enrollments WHERE student_id = ?', (student_id,)).fetchall()
    return [r['course_id'] for r in rows]


def get_courses_for_student(student_id):
    """Return list of courses (with teacher_name) the student is enrolled in."""
    db = get_db()
    rows = db.execute('''
        SELECT c.*, u.full_name as teacher_name
        FROM course_enrollments ce
        JOIN courses c ON ce.course_id = c.id
        JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
        WHERE ce.student_id = ?
        ORDER BY c.course_code, c.section_number
    ''', (student_id,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d['teacher_name'] = _teacher_name_for_display(r['teacher_id'], r['teacher_name'])
        result.append(d)
    return result


def _teacher_name_for_display(teacher_id, teacher_name):
    uid = get_unassigned_teacher_id()
    if uid and teacher_id == uid:
        return 'None'
    return teacher_name


def get_all_courses():
    db = get_db()
    unassigned_id = get_unassigned_teacher_id()
    rows = db.execute('''
        SELECT c.*, u.full_name as teacher_name
        FROM courses c
        JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
        ORDER BY c.course_code, c.section_number
    ''').fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d['teacher_name'] = _teacher_name_for_display(r['teacher_id'], r['teacher_name'])
        result.append(d)
    return result


def get_course_by_id(course_id):
    db = get_db()
    row = db.execute('''
        SELECT c.*, u.full_name as teacher_name
        FROM courses c
        JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
        WHERE c.id = ?
    ''', (course_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d['teacher_name'] = _teacher_name_for_display(row['teacher_id'], row['teacher_name'])
    return d


def get_exams_by_course(course_id):
    db = get_db()
    return db.execute('SELECT * FROM exam_sessions WHERE course_id = ?', (course_id,)).fetchall()


def auto_update_exam_statuses():
    db = get_db()
    now = datetime.now().isoformat()
    db.execute('''
        UPDATE exam_sessions SET status = 'active'
        WHERE status = 'scheduled' AND scheduled_start IS NOT NULL AND scheduled_end IS NOT NULL
        AND scheduled_start <= ? AND scheduled_end > ?
    ''', (now, now))
    db.execute('''
        UPDATE exam_sessions SET status = 'completed'
        WHERE status = 'active' AND scheduled_end IS NOT NULL AND scheduled_end <= ?
        AND video_filepath IS NULL
    ''', (now,))
    db.commit()


def get_all_exams(teacher_id=None):
    db = get_db()
    auto_update_exam_statuses()
    if teacher_id is not None:
        return db.execute('''
            SELECT e.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number
            FROM exam_sessions e JOIN courses c ON e.course_id = c.id
            WHERE c.teacher_id = ?
            ORDER BY CASE e.status WHEN 'active' THEN 1 WHEN 'scheduled' THEN 2 ELSE 3 END, e.scheduled_start ASC
        ''', (teacher_id,)).fetchall()
    return db.execute('''
        SELECT e.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number
        FROM exam_sessions e JOIN courses c ON e.course_id = c.id
        ORDER BY CASE e.status WHEN 'active' THEN 1 WHEN 'scheduled' THEN 2 ELSE 3 END, e.scheduled_start ASC
    ''').fetchall()


def get_exam_by_id(exam_id):
    db = get_db()
    return db.execute('''
        SELECT e.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number, c.teacher_id as course_teacher_id
        FROM exam_sessions e JOIN courses c ON e.course_id = c.id WHERE e.id = ?
    ''', (exam_id,)).fetchone()


def exam_belongs_to_teacher(exam_id, teacher_id):
    if not teacher_id:
        return False
    exam = get_exam_by_id(exam_id)
    return exam and dict(exam).get('course_teacher_id') == teacher_id


def get_exam_classroom_id(exam_id):
    """Return classroom_id for an exam (from classroom_id or by resolving location)."""
    exam = get_exam_by_id(exam_id)
    if not exam:
        return None
    exam = dict(exam)
    if exam.get('classroom_id'):
        return exam['classroom_id']
    loc = exam.get('location') or ''
    for c in get_all_classrooms():
        if _location_matches_classroom(loc, c['room_number']):
            return c['id']
    return None


def get_students_in_exam(exam_id):
    db = get_db()
    return db.execute('''
        SELECT u.full_name, s.student_id FROM exam_enrollments ee
        JOIN students s ON ee.student_id = s.id JOIN users u ON s.user_id = u.id
        WHERE ee.exam_id = ?
    ''', (exam_id,)).fetchall()


def get_completed_exams(teacher_id=None):
    db = get_db()
    if teacher_id is not None:
        return db.execute('''
            SELECT e.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number
            FROM exam_sessions e JOIN courses c ON e.course_id = c.id
            WHERE e.status = 'completed' AND c.teacher_id = ?
        ''', (teacher_id,)).fetchall()
    return db.execute('''
        SELECT e.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number
        FROM exam_sessions e JOIN courses c ON e.course_id = c.id WHERE e.status = 'completed'
    ''').fetchall()


def get_alerts_by_exam(exam_id):
    db = get_db()
    return db.execute('SELECT * FROM cheating_alerts WHERE exam_id = ? ORDER BY created_at DESC', (exam_id,)).fetchall()


def create_exam(course_id, exam_name):
    db = get_db()
    cursor = db.execute('INSERT INTO exam_sessions (course_id, exam_name, status) VALUES (?, ?, "scheduled")', (course_id, exam_name))
    db.commit()
    return cursor.lastrowid


def update_exam_status(exam_id, status, video_path=None):
    db = get_db()
    if video_path:
        expires_at = (datetime.now() + timedelta(minutes=1)).isoformat()
        db.execute('UPDATE exam_sessions SET status = ?, video_filepath = ?, expires_at = ? WHERE id = ?',
                   (status, video_path, expires_at, exam_id))
    else:
        db.execute('UPDATE exam_sessions SET status = ? WHERE id = ?', (status, exam_id))
    db.commit()


def save_alert_to_db(exam_id, alert_type, timestamp_seconds, confidence):
    db = get_db()
    db.execute('INSERT INTO cheating_alerts (exam_id, alert_type, timestamp_seconds, confidence) VALUES (?, ?, ?, ?)',
               (exam_id, alert_type, timestamp_seconds, confidence))
    db.commit()


def get_exam_expiration(exam_id):
    db = get_db()
    r = db.execute('SELECT expires_at FROM exam_sessions WHERE id = ?', (exam_id,)).fetchone()
    if r and r['expires_at']:
        return datetime.fromisoformat(r['expires_at'])
    return None


def set_exam_expiration(exam_id, days=30):
    db = get_db()
    expires_at = datetime.now() + timedelta(days=days)
    db.execute('UPDATE exam_sessions SET expires_at = ? WHERE id = ?', (expires_at.isoformat(), exam_id))
    db.commit()
    return expires_at


def extend_exam_expiration(exam_id, days=5):
    db = get_db()
    current = get_exam_expiration(exam_id)
    new_expiry = (current + timedelta(days=days)) if current else datetime.now() + timedelta(days=days)
    db.execute('UPDATE exam_sessions SET expires_at = ? WHERE id = ?', (new_expiry.isoformat(), exam_id))
    db.commit()
    return new_expiry


def get_expired_exams():
    db = get_db()
    return db.execute('''
        SELECT * FROM exam_sessions WHERE expires_at IS NOT NULL AND expires_at < ? AND video_filepath IS NOT NULL
    ''', (datetime.now().isoformat(),)).fetchall()


def delete_exam_video(exam_id):
    db = get_db()
    exam = get_exam_by_id(exam_id)
    if exam and exam['video_filepath']:
        video_path = exam['video_filepath']
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception as e:
                print(f"Error deleting video: {e}")
        db.execute('UPDATE exam_sessions SET video_filepath = NULL WHERE id = ?', (exam_id,))
        db.execute('DELETE FROM cheating_alerts WHERE exam_id = ?', (exam_id,))
        db.commit()
        return True
    return False


def delete_exam(exam_id):
    db = get_db()
    exam = get_exam_by_id(exam_id)
    if exam:
        if exam['video_filepath'] and os.path.exists(exam['video_filepath']):
            try:
                os.remove(exam['video_filepath'])
            except Exception as e:
                print(f"Error deleting video: {e}")
        db.execute('DELETE FROM cheating_alerts WHERE exam_id = ?', (exam_id,))
        db.execute('DELETE FROM exam_enrollments WHERE exam_id = ?', (exam_id,))
        db.execute('DELETE FROM exam_sessions WHERE id = ?', (exam_id,))
        db.commit()
        return True
    return False


def cleanup_expired_videos():
    deleted = 0
    for exam in get_expired_exams():
        if delete_exam_video(exam['id']):
            deleted += 1
    return deleted


# Admin helpers
DEPARTMENTS = ['CS', 'IT', 'IS']
MAJORS = ['CS', 'IT', 'IS']


def get_departments():
    try:
        db = get_db()
        rows = db.execute('SELECT id, name FROM departments ORDER BY name').fetchall()
        return [dict(r) for r in rows] if rows else [{'id': n, 'name': n} for n in DEPARTMENTS]
    except Exception:
        return [{'id': n, 'name': n} for n in DEPARTMENTS]


def get_majors():
    try:
        db = get_db()
        rows = db.execute('SELECT id, name FROM majors ORDER BY name').fetchall()
        return [dict(r) for r in rows] if rows else [{'id': n, 'name': n} for n in MAJORS]
    except Exception:
        return [{'id': n, 'name': n} for n in MAJORS]


def admin_get_all_teachers():
    db = get_db()
    return db.execute('SELECT t.*, u.email, u.full_name FROM teachers t JOIN users u ON t.user_id = u.id ORDER BY u.full_name').fetchall()


def admin_get_all_students():
    db = get_db()
    return db.execute('SELECT s.*, u.email, u.full_name FROM students s JOIN users u ON s.user_id = u.id ORDER BY u.full_name').fetchall()


def admin_create_user(email, password, full_name, role):
    db = get_db()
    email = (email or "").strip().lower()
    if not email:
        return None
    try:
        cursor = db.execute('INSERT INTO users (email, password, full_name, role) VALUES (?, ?, ?, ?)',
                            (email, hash_password(password), full_name, role))
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def admin_create_teacher(email, password, full_name, department=None, office_number=None):
    user_id = admin_create_user(email, password, full_name, 'teacher')
    if not user_id:
        return None
    db = get_db()
    db.execute('INSERT INTO teachers (user_id, department, office_number) VALUES (?, ?, ?)',
               (user_id, department, office_number))
    db.commit()
    return db.execute('SELECT id FROM teachers WHERE user_id = ?', (user_id,)).fetchone()['id']


def admin_update_teacher(teacher_id, department, office_number=None):
    db = get_db()
    db.execute('UPDATE teachers SET department = ?, office_number = ? WHERE id = ?', (department, office_number, teacher_id))
    db.commit()


def get_teacher_info_for_sync(teacher_id):
    """Return {full_name, email, department, office_number} for chatbot sync. No password."""
    db = get_db()
    row = db.execute('''
        SELECT u.full_name, u.email, t.department, t.office_number
        FROM teachers t JOIN users u ON t.user_id = u.id
        WHERE t.id = ?
    ''', (teacher_id,)).fetchone()
    return dict(row) if row else None


def admin_update_student(student_id, major):
    db = get_db()
    db.execute('UPDATE students SET major = ? WHERE id = ?', (major, student_id))
    db.commit()


def admin_create_student(email, password, full_name, student_id, major=None, year=None):
    user_id = admin_create_user(email, password, full_name, 'student')
    if not user_id:
        return None
    db = get_db()
    db.execute('INSERT INTO students (user_id, student_id, major, year) VALUES (?, ?, ?, ?)',
               (user_id, student_id, major, year))
    db.commit()
    return db.execute('SELECT id FROM students WHERE user_id = ?', (user_id,)).fetchone()['id']


def admin_get_all_students_for_select():
    db = get_db()
    return db.execute('SELECT s.id, s.student_id, u.full_name FROM students s JOIN users u ON s.user_id = u.id ORDER BY u.full_name').fetchall()


def admin_create_course(course_code, course_name, section_number, teacher_id, semester=None):
    db = get_db()
    try:
        db.execute('INSERT INTO courses (course_code, course_name, section_number, teacher_id, semester) VALUES (?, ?, ?, ?, ?)',
                   (course_code, course_name, int(section_number or 1), int(teacher_id), semester))
        db.commit()
        return db.execute('SELECT id FROM courses ORDER BY id DESC LIMIT 1').fetchone()['id']
    except sqlite3.IntegrityError:
        return None


def admin_enroll_student(course_id, student_id):
    db = get_db()
    try:
        db.execute('INSERT INTO course_enrollments (course_id, student_id) VALUES (?, ?)', (int(course_id), int(student_id)))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def admin_unenroll_student(course_id, student_id):
    db = get_db()
    db.execute('DELETE FROM course_enrollments WHERE course_id = ? AND student_id = ?', (int(course_id), int(student_id)))
    db.commit()


def get_student_by_student_id(student_id_str):
    db = get_db()
    return db.execute('SELECT * FROM students WHERE student_id = ?', (student_id_str.strip(),)).fetchone()


def get_course_by_code_section(course_code, section_number):
    db = get_db()
    return db.execute('SELECT * FROM courses WHERE course_code = ? AND section_number = ?',
                      (course_code.strip(), int(section_number))).fetchone()


def admin_enroll_by_student_id(course_id, student_id_str):
    s = get_student_by_student_id(student_id_str)
    if not s:
        return False, "Student not found"
    if admin_enroll_student(course_id, s['id']):
        return True, None
    return False, "Already enrolled"


def admin_unenroll_by_student_id(course_id, student_id_str):
    s = get_student_by_student_id(student_id_str)
    if not s:
        return False, "Student not found"
    admin_unenroll_student(course_id, s['id'])
    return True, None


def admin_delete_teacher(teacher_id):
    unassigned_id = get_unassigned_teacher_id()
    if unassigned_id and int(teacher_id) == unassigned_id:
        return False
    db = get_db()
    t = db.execute('SELECT user_id FROM teachers WHERE id = ?', (teacher_id,)).fetchone()
    if not t:
        return False
    if not unassigned_id:
        return False
    db.execute('UPDATE courses SET teacher_id = ? WHERE teacher_id = ?', (unassigned_id, teacher_id))
    db.execute('DELETE FROM teachers WHERE id = ?', (teacher_id,))
    db.execute('DELETE FROM users WHERE id = ?', (t['user_id'],))
    db.commit()
    return True


def admin_delete_student(student_id):
    db = get_db()
    s = db.execute('SELECT user_id FROM students WHERE id = ?', (student_id,)).fetchone()
    if not s:
        return False
    db.execute('DELETE FROM users WHERE id = ?', (s['user_id'],))
    db.commit()
    return True


def admin_delete_course(course_id):
    db = get_db()
    db.execute('DELETE FROM courses WHERE id = ?', (int(course_id),))
    db.commit()
    return True


def admin_update_course_teacher(course_id, teacher_id):
    db = get_db()
    tid = int(teacher_id) if teacher_id and str(teacher_id).strip() else get_unassigned_teacher_id()
    if not tid:
        return False
    db.execute('UPDATE courses SET teacher_id = ? WHERE id = ?', (tid, int(course_id)))
    db.commit()
    return True


def get_enrolled_students(course_id):
    db = get_db()
    return db.execute('''
        SELECT ce.student_id, s.student_id as sid, u.full_name
        FROM course_enrollments ce
        JOIN students s ON ce.student_id = s.id
        JOIN users u ON s.user_id = u.id
        WHERE ce.course_id = ?
    ''', (course_id,)).fetchall()


def get_all_classrooms():
    """Return all classrooms ordered by room_number."""
    db = get_db()
    return db.execute('SELECT * FROM classrooms ORDER BY room_number').fetchall()


def get_classroom_by_id(classroom_id):
    """Return classroom by id, or None."""
    if not classroom_id:
        return None
    db = get_db()
    return db.execute('SELECT * FROM classrooms WHERE id = ?', (int(classroom_id),)).fetchone()


def get_classroom_by_room_number(room_number):
    """Return classroom by room_number, or None."""
    if not room_number:
        return None
    db = get_db()
    return db.execute('SELECT * FROM classrooms WHERE room_number = ?', (str(room_number).strip(),)).fetchone()


def set_classroom_recording(classroom_id, is_recording):
    """Set is_recording flag for a classroom (used by monitoring system)."""
    if not classroom_id:
        return
    db = get_db()
    db.execute('UPDATE classrooms SET is_recording = ? WHERE id = ?', (1 if is_recording else 0, int(classroom_id)))
    db.commit()


def _location_matches_classroom(location, room_number):
    """Check if location string refers to the given room (e.g. 1001)."""
    if not location or not str(location).strip() or not room_number:
        return False
    loc = str(location).strip().lower()
    rn = str(room_number)
    return rn in loc or ('classroom ' + rn) in loc or ('room ' + rn) in loc


def _parse_dt(s):
    """Parse datetime string from DB to datetime. Handles YYYY-MM-DDTHH:MM and YYYY-MM-DDTHH:MM:SS."""
    if not s:
        return None
    s = str(s).strip().replace(' ', 'T')
    if len(s) == 16 and s[13] == ':':
        s = s + ':00'
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')[:19])
    except (ValueError, TypeError):
        return None


def get_room_occupancy(dt):
    """Return dict: room_number -> { busy, event_type, title, start, end, is_recording }.
    dt: datetime to check (exam/class overlapping this time).
    Uses Python datetime comparison to avoid SQL string format issues.
    """
    db = get_db()
    classrooms = get_all_classrooms()
    results = {}
    for c in classrooms:
        row = dict(c)
        rn = row['room_number']
        results[rn] = {
            'busy': False, 'event_type': None, 'title': None, 'start': None, 'end': None,
            'is_recording': bool(row.get('is_recording', 0))
        }

    # Fetch exams in a 24h window around dt to avoid SQL datetime format issues
    window_start = (dt - timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M')
    window_end = (dt + timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M')
    exams = db.execute('''
        SELECT e.id, e.exam_name as title, e.scheduled_start, e.scheduled_end, e.location, e.classroom_id
        FROM exam_sessions e
        WHERE e.scheduled_start IS NOT NULL AND e.scheduled_end IS NOT NULL
        AND e.scheduled_start < ? AND e.scheduled_end > ?
    ''', (window_end, window_start)).fetchall()

    for ex in exams:
        ex = dict(ex)
        start_dt = _parse_dt(ex.get('scheduled_start'))
        end_dt = _parse_dt(ex.get('scheduled_end'))
        if start_dt is None or end_dt is None or not (start_dt <= dt < end_dt):
            continue
        for c in classrooms:
            row = dict(c)
            rn = row['room_number']
            cid = row['id']
            ex_cid = ex.get('classroom_id')
            ex_loc = ex.get('location') or ''
            if ex_cid is not None and int(ex_cid) == int(cid):
                results[rn] = {
                    'busy': True, 'event_type': 'exam',
                    'title': ex['title'], 'start': ex['scheduled_start'], 'end': ex['scheduled_end'],
                    'is_recording': results[rn].get('is_recording', False)
                }
                break
            elif _location_matches_classroom(ex_loc, rn) or (str(ex_loc) == str(cid) or str(ex_loc) == rn):
                results[rn] = {
                    'busy': True, 'event_type': 'exam',
                    'title': ex['title'], 'start': ex['scheduled_start'], 'end': ex['scheduled_end'],
                    'is_recording': results[rn].get('is_recording', False)
                }
                break

    # Fetch calendar events in same window, filter by overlap in Python
    events = db.execute('''
        SELECT ce.id, ce.title, ce.start_time, ce.end_time, ce.location, ce.classroom_id
        FROM calendar_events ce
        WHERE ce.calendar_type IN ('course', 'global')
        AND ce.event_type IN ('class', 'lecture')
        AND ce.start_time < ? AND ce.end_time > ?
    ''', (window_end, window_start)).fetchall()

    for ev in events:
        ev = dict(ev)
        start_dt = _parse_dt(ev.get('start_time'))
        end_dt = _parse_dt(ev.get('end_time'))
        if start_dt is None or end_dt is None or not (start_dt <= dt < end_dt):
            continue
        for c in classrooms:
            row = dict(c)
            rn = row['room_number']
            cid = row['id']
            ev_cid = ev.get('classroom_id')
            ev_loc = ev.get('location') or ''
            if ev_cid is not None and int(ev_cid) == int(cid):
                results[rn] = {
                    'busy': True, 'event_type': 'lecture',
                    'title': ev['title'], 'start': ev['start_time'], 'end': ev['end_time'],
                    'is_recording': results[rn].get('is_recording', False)
                }
                break
            elif _location_matches_classroom(ev_loc, rn) or (str(ev_loc) == str(cid) or str(ev_loc) == rn):
                results[rn] = {
                    'busy': True, 'event_type': 'lecture',
                    'title': ev['title'], 'start': ev['start_time'], 'end': ev['end_time'],
                    'is_recording': results[rn].get('is_recording', False)
                }
                break

    return results


def get_room_schedule(room_number, start_dt, end_dt):
    """Return list of events (exam/class) for a room in the given time range, with booking contact info."""
    database = get_db()
    classroom = get_classroom_by_room_number(room_number)
    if not classroom:
        return []
    cid = classroom['id']
    start_str = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
    end_str = end_dt.strftime('%Y-%m-%dT%H:%M:%S')
    out = []

    # Exams: join course -> teacher -> user for contact info
    exams = database.execute('''
        SELECT e.exam_name as title, e.scheduled_start, e.scheduled_end, e.location, e.classroom_id,
               u.full_name as booked_by, u.email as booked_email,
               t.office_number as booked_office, c.course_code, c.course_name
        FROM exam_sessions e
        JOIN courses c ON e.course_id = c.id
        JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
        WHERE e.scheduled_start IS NOT NULL AND e.scheduled_end IS NOT NULL
        AND e.scheduled_start < ? AND e.scheduled_end > ?
    ''', (end_str, start_str)).fetchall()
    for ex in exams:
        ex = dict(ex)
        ex_cid, ex_loc = ex.get('classroom_id'), ex.get('location') or ''
        if (ex_cid is not None and ex_cid == cid) or _location_matches_classroom(ex_loc, room_number) or str(ex_loc) == str(cid) or str(ex_loc) == room_number:
            out.append({
                'title': ex['title'], 'start': ex['scheduled_start'], 'end': ex['scheduled_end'],
                'event_type': 'exam',
                'booked_by': ex.get('booked_by'), 'booked_email': ex.get('booked_email'),
                'booked_office': ex.get('booked_office'), 'course_code': ex.get('course_code'),
                'course_name': ex.get('course_name')
            })

    # Calendar events: course events -> teacher; global events -> user
    events = database.execute('''
        SELECT ce.id, ce.title, ce.start_time, ce.end_time, ce.location, ce.classroom_id,
               ce.course_id, ce.user_id, ce.calendar_type, ce.description,
               u.full_name as booked_by, u.email as booked_email,
               t.office_number as booked_office, c.course_code, c.course_name
        FROM calendar_events ce
        LEFT JOIN courses c ON ce.course_id = c.id
        LEFT JOIN teachers t ON c.teacher_id = t.id
        LEFT JOIN users u ON COALESCE(t.user_id, ce.user_id) = u.id
        WHERE ce.calendar_type IN ('course', 'global') AND ce.event_type = 'class'
        AND ce.start_time < ? AND ce.end_time > ?
    ''', (end_str, start_str)).fetchall()
    for ev in events:
        ev = dict(ev)
        ev_cid, ev_loc = ev.get('classroom_id'), ev.get('location') or ''
        if (ev_cid is not None and ev_cid == cid) or _location_matches_classroom(ev_loc, room_number) or str(ev_loc) == str(cid) or str(ev_loc) == room_number:
            out.append({
                'title': ev['title'], 'start': ev['start_time'], 'end': ev['end_time'],
                'event_type': 'lecture',
                'booked_by': ev.get('booked_by'), 'booked_email': ev.get('booked_email'),
                'booked_office': ev.get('booked_office'), 'course_code': ev.get('course_code'),
                'course_name': ev.get('course_name'), 'description': ev.get('description')
            })

    return sorted(out, key=lambda x: x['start'])


def init_classrooms_table():
    """Create classrooms table and add classroom_id to exam_sessions and calendar_events."""
    database = get_db()
    database.execute('''
        CREATE TABLE IF NOT EXISTS classrooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_number TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            is_recording INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    for stmt in [
        'ALTER TABLE exam_sessions ADD COLUMN classroom_id INTEGER REFERENCES classrooms(id)',
        'ALTER TABLE calendar_events ADD COLUMN classroom_id INTEGER REFERENCES classrooms(id)',
    ]:
        try:
            database.execute(stmt)
        except Exception:
            pass
    # Seed default classrooms if empty
    if database.execute('SELECT COUNT(*) FROM classrooms').fetchone()[0] == 0:
        for rn in ['1001', '1002', '1003', '1004', '1005', '1006', '1007', '1008', '1009', '1010']:
            database.execute('INSERT INTO classrooms (room_number, name) VALUES (?, ?)',
                            (rn, 'Classroom ' + rn))
    # Migrate existing location strings to classroom_id where possible
    for c in database.execute('SELECT id, room_number, name FROM classrooms').fetchall():
        cid, rn, name = c[0], c[1], c[2]  # avoid Row .get()
        try:
            # Match: location = id (e.g. "1"), room_number (e.g. "1001"), or name substring
            database.execute('''
                UPDATE exam_sessions SET classroom_id = ?
                WHERE classroom_id IS NULL AND (
                    TRIM(COALESCE(location,'')) = ? OR TRIM(COALESCE(location,'')) = ?
                    OR location LIKE ? OR location LIKE ? OR location LIKE ?
                )
            ''', (cid, str(cid), str(rn), '%' + rn + '%', '%' + name + '%', '%' + name.lower() + '%'))
            database.execute('''
                UPDATE calendar_events SET classroom_id = ?
                WHERE classroom_id IS NULL AND (
                    TRIM(COALESCE(location,'')) = ? OR TRIM(COALESCE(location,'')) = ?
                    OR location LIKE ? OR location LIKE ? OR location LIKE ?
                )
            ''', (cid, str(cid), str(rn), '%' + rn + '%', '%' + name + '%', '%' + name.lower() + '%'))
        except Exception:
            pass
    database.commit()


def init_calendar_table():
    """Run calendar table migrations."""
    database = get_db()
    for stmt, _ in [
        ('ALTER TABLE courses ADD COLUMN section_number INTEGER NOT NULL DEFAULT 1', 'courses'),
        ('ALTER TABLE exam_sessions ADD COLUMN scheduled_start TEXT', 'exam_sessions'),
        ('ALTER TABLE exam_sessions ADD COLUMN scheduled_end TEXT', 'exam_sessions'),
        ('ALTER TABLE exam_sessions ADD COLUMN location TEXT', 'exam_sessions'),
        ('ALTER TABLE calendar_events ADD COLUMN url TEXT', 'calendar_events'),
    ]:
        try:
            database.execute(stmt)
        except Exception:
            pass
    database.execute('''
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_type TEXT NOT NULL,
            calendar_type TEXT NOT NULL,
            course_id INTEGER,
            user_id INTEGER,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            location TEXT,
            description TEXT,
            url TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    database.commit()
    init_classrooms_table()
    print("Calendar tables initialized successfully")
