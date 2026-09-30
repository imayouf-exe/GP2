"""Calendar event logic - validation, conflict check, CRUD."""
from datetime import datetime, timedelta
from flask import request, session

from core import db


def _format_datetime_for_chatbot(s):
    """Format ISO datetime for human-readable display in chatbot responses."""
    if not s:
        return ""
    s = str(s).strip()
    try:
        if "T" in s and len(s) >= 16:
            dt = datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")
            return dt.strftime("%A, %B %d at %I:%M %p")
        if len(s) >= 10:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
            return dt.strftime("%A, %B %d")
        return s
    except Exception:
        return s[:16] if len(s) >= 16 else s


def get_upcoming_events_for_chatbot(session_dict, days_ahead=14, max_events=25):
    """
    Return upcoming calendar events for the current user (exams, classes, assignments, personal).
    Used by chatbot to answer questions about schedules. Filters by start >= now.
    session_dict: {user_id, role, teacher_id}
    Returns list of dicts with title, start, end, event_type, course_name, location, etc.
    """
    database = db.get_db()
    user_id = session_dict.get("user_id")
    role = session_dict.get("role")
    teacher_id = session_dict.get("teacher_id")

    enrolled_course_ids = []
    if role == "student":
        student = db.get_student_by_user_id(user_id)
        if student:
            enrolled_course_ids = db.get_course_ids_for_student(student["id"])

    teacher_course_ids = []
    if role == "teacher" and teacher_id:
        teacher_course_ids = [c["id"] for c in db.get_courses_by_teacher(teacher_id)]

    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    cutoff = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%S")
    events = []

    try:
        db.auto_update_exam_statuses()
    except Exception:
        pass

    # Exams
    exams = database.execute("""
        SELECT e.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number, u.full_name as teacher_name
        FROM exam_sessions e
        JOIN courses c ON e.course_id = c.id
        JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
        WHERE e.scheduled_start IS NOT NULL AND e.scheduled_start >= ? AND e.scheduled_start <= ?
    """, (now_str, cutoff)).fetchall()
    for e in exams:
        ed = dict(e)
        if role == "student" and enrolled_course_ids and ed["course_id"] not in enrolled_course_ids:
            continue
        if role == "teacher" and teacher_course_ids and ed["course_id"] not in teacher_course_ids:
            continue
        events.append({
            "title": ed["exam_name"], "start": ed["scheduled_start"], "end": ed["scheduled_end"],
            "start_fmt": _format_datetime_for_chatbot(ed["scheduled_start"]),
            "end_fmt": _format_datetime_for_chatbot(ed["scheduled_end"]),
            "event_type": "exam", "course": f"{ed['course_name']} - Section {ed.get('section_number', 1)}",
            "course_code": ed.get("course_code"), "location": ed["location"], "status": ed["status"],
        })

    # Course events (classes, assignments, etc.)
    course_events = database.execute("""
        SELECT ce.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number
        FROM calendar_events ce
        LEFT JOIN courses c ON ce.course_id = c.id
        WHERE ce.calendar_type = 'course' AND ce.start_time >= ? AND ce.start_time <= ?
    """, (now_str, cutoff)).fetchall()
    for e in course_events:
        ed = dict(e)
        if role == "student" and enrolled_course_ids and (ed["course_id"] is None or ed["course_id"] not in enrolled_course_ids):
            continue
        if role == "teacher" and teacher_course_ids and (ed["course_id"] is None or ed["course_id"] not in teacher_course_ids):
            continue
        course_display = f"{ed.get('course_name') or 'Unknown'} - Section {ed.get('section_number', 1)}" if ed.get("course_name") else None
        events.append({
            "title": ed["title"], "start": ed["start_time"], "end": ed["end_time"],
            "start_fmt": _format_datetime_for_chatbot(ed["start_time"]),
            "end_fmt": _format_datetime_for_chatbot(ed["end_time"]),
            "event_type": ed["event_type"] or "class", "course": course_display,
            "location": ed["location"], "description": ed["description"],
        })

    # Global events
    global_events = database.execute("""
        SELECT ce.*, c.course_name FROM calendar_events ce
        LEFT JOIN courses c ON ce.course_id = c.id
        WHERE ce.calendar_type = 'global' AND ce.start_time >= ? AND ce.start_time <= ?
    """, (now_str, cutoff)).fetchall()
    for e in global_events:
        ed = dict(e)
        events.append({
            "title": ed["title"], "start": ed["start_time"], "end": ed["end_time"],
            "start_fmt": _format_datetime_for_chatbot(ed["start_time"]),
            "end_fmt": _format_datetime_for_chatbot(ed["end_time"]),
            "event_type": ed["event_type"] or "other", "course": None,
            "location": ed["location"], "description": ed["description"],
        })

    # Personal events (students/teachers)
    personal = database.execute(
        "SELECT * FROM calendar_events WHERE calendar_type = ? AND user_id = ? AND start_time >= ? AND start_time <= ?",
        ("personal", user_id, now_str, cutoff)
    ).fetchall()
    for e in personal:
        ed = dict(e)
        events.append({
            "title": ed["title"], "start": ed["start_time"], "end": ed["end_time"],
            "start_fmt": _format_datetime_for_chatbot(ed["start_time"]),
            "end_fmt": _format_datetime_for_chatbot(ed["end_time"]),
            "event_type": ed["event_type"] or "other", "course": None,
            "location": ed["location"], "description": ed["description"],
        })

    events.sort(key=lambda x: x["start"])
    return events[:max_events]


def get_course_class_schedule(course_id, days_ahead=30, max_events=15):
    """Return upcoming class/lecture events for a course. Used for 'when does CS101 meet'."""
    if not course_id:
        return []
    database = db.get_db()
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    cutoff = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = database.execute("""
        SELECT ce.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number
        FROM calendar_events ce
        LEFT JOIN courses c ON ce.course_id = c.id
        WHERE ce.course_id = ? AND ce.calendar_type = 'course'
          AND ce.event_type IN ('class', 'lecture')
          AND ce.start_time >= ? AND ce.start_time <= ?
        ORDER BY ce.start_time ASC
    """, (course_id, now_str, cutoff)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        out.append({
            "title": d["title"],
            "start": d["start_time"],
            "start_fmt": _format_datetime_for_chatbot(d["start_time"]),
            "end": d["end_time"],
            "end_fmt": _format_datetime_for_chatbot(d["end_time"]),
            "location": d.get("location"),
        })
    return out[:max_events]


def get_upcoming_announcements_for_chatbot(session_dict, days_ahead=14, max_events=10):
    """Return upcoming announcement/reminder/assignment events visible to the current user."""
    database = db.get_db()
    user_id = session_dict.get("user_id")
    role = session_dict.get("role")
    teacher_id = session_dict.get("teacher_id")

    enrolled_course_ids = []
    if role == "student":
        student = db.get_student_by_user_id(user_id)
        if student:
            enrolled_course_ids = db.get_course_ids_for_student(student["id"])

    teacher_course_ids = []
    if role == "teacher" and teacher_id:
        teacher_course_ids = [c["id"] for c in db.get_courses_by_teacher(teacher_id)]

    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    cutoff = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%S")
    out = []

    rows = database.execute(
        """
        SELECT ce.*, c.course_name, COALESCE(c.section_number, 1) as section_number
        FROM calendar_events ce
        LEFT JOIN courses c ON ce.course_id = c.id
        WHERE ce.event_type IN ('announcement', 'reminder', 'assignment')
          AND ce.start_time >= ? AND ce.start_time <= ?
        ORDER BY ce.start_time ASC
        """,
        (now_str, cutoff),
    ).fetchall()

    for r in rows:
        d = dict(r)
        if role == "student" and d["calendar_type"] == "course":
            if enrolled_course_ids and (d["course_id"] is None or d["course_id"] not in enrolled_course_ids):
                continue
        if role == "teacher" and d["calendar_type"] == "course":
            if teacher_course_ids and (d["course_id"] is None or d["course_id"] not in teacher_course_ids):
                continue
        if role == "student" and d["calendar_type"] == "personal" and d["user_id"] != user_id:
            continue
        course_display = None
        if d.get("course_name"):
            course_display = f"{d['course_name']} - Section {d.get('section_number', 1)}"
        out.append(
            {
                "title": d["title"],
                "event_type": d["event_type"],
                "calendar_type": d["calendar_type"],
                "start": d["start_time"],
                "start_fmt": _format_datetime_for_chatbot(d["start_time"]),
                "end": d["end_time"],
                "end_fmt": _format_datetime_for_chatbot(d["end_time"]),
                "course": course_display,
                "location": d.get("location"),
                "description": d.get("description"),
            }
        )

    return out[:max_events]


def _normalize_datetime(s):
    """Ensure datetime string has seconds for consistent DB comparison with floor map."""
    if not s or not isinstance(s, str):
        return s
    s = s.strip()
    if len(s) == 16 and s[10] == 'T' and s[13] == ':':  # YYYY-MM-DDTHH:MM
        return s + ':00'
    return s


def check_classroom_conflict(classroom_id, start, end, exclude_exam_id=None, exclude_event_id=None):
    """Returns (has_conflict, teacher_name). Checks by classroom_id."""
    if not classroom_id:
        return False, None
    database = db.get_db()
    exams = database.execute('''
        SELECT e.id, u.full_name as teacher_name
        FROM exam_sessions e
        JOIN courses c ON e.course_id = c.id
        JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
        WHERE e.classroom_id = ? AND e.scheduled_start < ? AND e.scheduled_end > ?
    ''', (int(classroom_id), end, start)).fetchall()
    for ex in exams:
        if exclude_exam_id and ex['id'] == exclude_exam_id:
            continue
        return True, ex['teacher_name'] or 'Unknown teacher'
    events = database.execute('''
        SELECT ce.id, u.full_name as teacher_name
        FROM calendar_events ce
        LEFT JOIN courses c ON ce.course_id = c.id
        LEFT JOIN teachers t ON c.teacher_id = t.id
        LEFT JOIN users u ON t.user_id = u.id
        WHERE ce.calendar_type IN ('course', 'global') AND ce.event_type = 'class'
        AND ce.classroom_id = ? AND ce.start_time < ? AND ce.end_time > ?
    ''', (int(classroom_id), end, start)).fetchall()
    for ev in events:
        if exclude_event_id and ev['id'] == exclude_event_id:
            continue
        return True, ev['teacher_name'] or 'Unknown teacher'
    return False, None


def get_available_rooms(start_str, end_str):
    """Return list of room numbers that are free during the given time range."""
    classrooms = db.get_all_classrooms()
    available = []
    for c in classrooms:
        c = dict(c)
        rn = c.get("room_number")
        if not rn:
            continue
        loc = f"Room {rn}"
        has_conflict, _ = check_location_conflict(loc, start_str, end_str)
        if not has_conflict:
            available.append(rn)
    return sorted(available, key=lambda x: (len(x), x))


def check_location_conflict(location, start, end, exclude_exam_id=None, exclude_event_id=None):
    """Returns (has_conflict, teacher_name). Resolves location to classroom when possible."""
    if not location or not str(location).strip():
        return False, None
    loc = str(location).strip()
    import re
    nums = re.findall(r'\d+', loc)
    room_num = nums[0] if nums else None
    classroom = db.get_classroom_by_room_number(room_num) if room_num else None
    if classroom:
        return check_classroom_conflict(classroom['id'], start, end, exclude_exam_id, exclude_event_id)
    database = db.get_db()
    exams = database.execute('''
        SELECT e.id, u.full_name as teacher_name FROM exam_sessions e
        JOIN courses c ON e.course_id = c.id JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
        WHERE (e.classroom_id IS NULL AND TRIM(LOWER(COALESCE(e.location,''))) = TRIM(LOWER(?)))
        AND e.scheduled_start < ? AND e.scheduled_end > ?
    ''', (loc, end, start)).fetchall()
    for ex in exams:
        if exclude_exam_id and ex['id'] == exclude_exam_id:
            continue
        return True, ex['teacher_name'] or 'Unknown teacher'
    events = database.execute('''
        SELECT ce.id, u.full_name as teacher_name FROM calendar_events ce
        LEFT JOIN courses c ON ce.course_id = c.id LEFT JOIN teachers t ON c.teacher_id = t.id
        LEFT JOIN users u ON t.user_id = u.id
        WHERE ce.calendar_type IN ('course', 'global') AND ce.event_type = 'class'
        AND (ce.classroom_id IS NULL AND TRIM(LOWER(COALESCE(ce.location,''))) = TRIM(LOWER(?)))
        AND ce.start_time < ? AND ce.end_time > ?
    ''', (loc, end, start)).fetchall()
    for ev in events:
        if exclude_event_id and ev['id'] == exclude_event_id:
            continue
        return True, ev['teacher_name'] or 'Unknown teacher'
    return False, None


def get_calendar_events():
    """Return JSON-serializable list of events for current user/role."""
    database = db.get_db()
    calendar_type = request.args.get('type', 'course')
    user_id = session.get('user_id')
    role = session.get('role')

    if role == 'admin':
        calendar_type = 'global'

    enrolled_course_ids = []
    if role == 'student':
        student = db.get_student_by_user_id(user_id)
        if student:
            enrolled_course_ids = db.get_course_ids_for_student(student['id'])

    teacher_course_ids = []
    if role == 'teacher':
        teacher_id = session.get('teacher_id')
        if teacher_id:
            teacher_course_ids = [c['id'] for c in db.get_courses_by_teacher(teacher_id)]

    events = []

    if calendar_type == 'course':
        try:
            db.auto_update_exam_statuses()
        except Exception as ex:
            print(f"auto_update_exam_statuses failed: {ex}")
        exams = database.execute('''
            SELECT e.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number, u.full_name as teacher_name
            FROM exam_sessions e
            JOIN courses c ON e.course_id = c.id
            JOIN teachers t ON c.teacher_id = t.id
            JOIN users u ON t.user_id = u.id
            WHERE e.scheduled_start IS NOT NULL
        ''').fetchall()
        for e in exams:
            if role == 'student' and enrolled_course_ids and e['course_id'] not in enrolled_course_ids:
                continue
            if role == 'teacher' and teacher_course_ids and e['course_id'] not in teacher_course_ids:
                continue
            ed = dict(e)
            events.append({
                "id": "exam_" + str(e["id"]),
                "title": e["exam_name"],
                "start": e["scheduled_start"],
                "end": e["scheduled_end"],
                "location": e["location"],
                "course_code": e["course_code"],
                "course_name": e["course_name"],
                "course_display": f"{e['course_name']} - Section {ed.get('section_number', 1)}",
                "event_type": "exam",
                "calendar_type": "course",
                "status": e["status"],
                "teacher_name": ed.get("teacher_name")
            })

        course_events = database.execute('''
            SELECT ce.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number, u.full_name as teacher_name
            FROM calendar_events ce
            LEFT JOIN courses c ON ce.course_id = c.id
            LEFT JOIN teachers t ON c.teacher_id = t.id
            LEFT JOIN users u ON t.user_id = u.id
            WHERE ce.calendar_type = 'course'
        ''').fetchall()
        for e in course_events:
            if role == 'student' and enrolled_course_ids and (e['course_id'] is None or e['course_id'] not in enrolled_course_ids):
                continue
            if role == 'teacher' and teacher_course_ids and (e['course_id'] is None or e['course_id'] not in teacher_course_ids):
                continue
            ed = dict(e)
            course_display = f"{ed.get('course_name') or 'Unknown'} - Section {ed.get('section_number', 1)}" if ed.get('course_name') else None
            events.append({
                "id": "event_" + str(e["id"]),
                "title": e["title"],
                "start": e["start_time"],
                "end": e["end_time"],
                "location": e["location"],
                "course_code": e["course_code"],
                "course_name": e["course_name"],
                "course_display": course_display,
                "event_type": e["event_type"],
                "calendar_type": "course",
                "description": e["description"],
                "teacher_name": ed.get("teacher_name")
            })

    elif calendar_type == 'global':
        rows = database.execute('''
            SELECT ce.*, c.course_code, c.course_name, COALESCE(c.section_number, 1) as section_number, u.full_name as teacher_name
            FROM calendar_events ce
            LEFT JOIN courses c ON ce.course_id = c.id
            LEFT JOIN teachers t ON c.teacher_id = t.id
            LEFT JOIN users u ON t.user_id = u.id
            WHERE ce.calendar_type = 'global'
        ''').fetchall()
        for e in rows:
            ed = dict(e)
            course_display = f"{ed.get('course_name') or 'Unknown'} - Section {ed.get('section_number', 1)}" if ed.get('course_name') else None
            events.append({
                "id": "event_" + str(e["id"]),
                "title": e["title"],
                "start": e["start_time"],
                "end": e["end_time"],
                "location": e["location"],
                "url": ed.get("url"),
                "course_code": e["course_code"],
                "course_name": e["course_name"],
                "course_display": course_display,
                "event_type": e["event_type"],
                "calendar_type": "global",
                "description": e["description"],
                "teacher_name": ed.get("teacher_name")
            })

    elif calendar_type == 'personal':
        rows = database.execute('SELECT * FROM calendar_events WHERE calendar_type = ? AND user_id = ?', ('personal', user_id)).fetchall()
        for e in rows:
            events.append({
                "id": "event_" + str(e["id"]),
                "title": e["title"],
                "start": e["start_time"],
                "end": e["end_time"],
                "location": e["location"],
                "event_type": e["event_type"],
                "calendar_type": "personal",
                "description": e["description"],
                "teacher_name": None
            })

    return events


def create_calendar_event(request, session):
    """
    Validate and create a calendar event (exam or calendar_events row).
    Returns (response_dict, status_code). status_code 200 = success.
    """
    from datetime import datetime as dt
    data = request.json
    database = db.get_db()
    user_id = session.get('user_id')
    role = session.get('role')
    calendar_type = data.get("calendar_type", "course")
    event_type = data.get("event_type", "other")

    if role == "student" and calendar_type != "personal":
        return ({"error": "Students can only add events to their personal calendar"}, 403)
    if role == "admin" and calendar_type != "global":
        return ({"error": "Admin can only add events to the Global Calendar"}, 403)

    start_str = data.get("start") or ""
    if start_str:
        try:
            start_dt = dt.fromisoformat(start_str.replace("Z", "+00:00"))
            if start_dt.tzinfo:
                start_dt = start_dt.replace(tzinfo=None)
            if start_dt < dt.now():
                return ({"error": "Cannot create an event in the past"}, 400)
        except Exception:
            pass

    course_id = data.get("course_id")
    if course_id == "" or course_id is None:
        course_id = None
    else:
        try:
            course_id = int(course_id)
        except Exception:
            course_id = None

    if calendar_type == "course" and course_id is None:
        return ({"error": "Course is required for course calendar events"}, 400)
    if role == "teacher" and calendar_type == "course" and course_id is not None:
        teacher_id = session.get('teacher_id')
        teacher_course_ids = [c['id'] for c in db.get_courses_by_teacher(teacher_id)] if teacher_id else []
        if course_id not in teacher_course_ids:
            return ({"error": "You can only add events to courses you teach"}, 403)

    if event_type == "exam" and calendar_type == "course":
        classroom_id = data.get("classroom_id")
        loc = (data.get("location") or "").strip()
        if classroom_id:
            c = db.get_classroom_by_id(int(classroom_id))
            loc = c['name'] if c else loc
        if not loc and not classroom_id:
            return ({"error": "Location is required for exams"}, 400)
        start_norm = _normalize_datetime(data["start"])
        end_norm = _normalize_datetime(data["end"])
        if classroom_id:
            conflict, other_teacher = check_classroom_conflict(int(classroom_id), start_norm, end_norm)
        else:
            conflict, other_teacher = check_location_conflict(loc, start_norm, end_norm)
        if conflict:
            return ({"error": f"Teacher {other_teacher} already has that room at that time"}, 400)
        cursor = database.execute('''
            INSERT INTO exam_sessions (course_id, exam_name, status, scheduled_start, scheduled_end, location, classroom_id)
            VALUES (?, ?, 'scheduled', ?, ?, ?, ?)
        ''', (course_id, data["title"], start_norm, end_norm, loc or None, int(classroom_id) if classroom_id else None))
        database.commit()
        return ({"id": "exam_" + str(cursor.lastrowid), "status": "created"}, 200)

    classroom_id = data.get("classroom_id")
    loc = (data.get("location") or "").strip()
    if classroom_id:
        c = db.get_classroom_by_id(int(classroom_id))
        loc = c['name'] if c else loc
    if calendar_type == "course" and event_type == "class":
        if not loc and not classroom_id:
            return ({"error": "Location is required for class events"}, 400)
        start_norm = _normalize_datetime(data["start"])
        end_norm = _normalize_datetime(data["end"])
        if classroom_id:
            conflict, other_teacher = check_classroom_conflict(int(classroom_id), start_norm, end_norm)
        else:
            conflict, other_teacher = check_location_conflict(loc, start_norm, end_norm)
        if conflict:
            return ({"error": f"Teacher {other_teacher} already has that room at that time"}, 400)

    start_norm = _normalize_datetime(data.get("start") or "")
    end_norm = _normalize_datetime(data.get("end") or "")
    cursor = database.execute('''
        INSERT INTO calendar_events (title, event_type, calendar_type, course_id, user_id, start_time, end_time, location, classroom_id, description, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data["title"],
        event_type,
        calendar_type,
        course_id if calendar_type != "personal" else None,
        user_id if calendar_type == "personal" else None,
        start_norm,
        end_norm,
        loc or None,
        int(classroom_id) if classroom_id else None,
        data.get("description"),
        data.get("url") or None
    ))
    database.commit()
    return ({"id": "event_" + str(cursor.lastrowid), "status": "created"}, 200)
