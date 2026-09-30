from dotenv import load_dotenv
load_dotenv()

import os
import re
import secrets
from flask import Flask, render_template, jsonify, request, redirect, url_for, session, Response, send_from_directory
from datetime import datetime, timedelta
import threading
import time

from core import db
from core import auth
from core import chatbot_db
from services.admin_routes import register_admin_routes
from services.auth_routes import register_auth_routes
from services.calendar_routes import register_calendar_routes
from services.chatbot_routes import register_chatbot_routes
from services.dashboard_routes import register_dashboard_routes
from services.settings_routes import register_settings_routes
from detector import CheatingDetector

app = Flask(__name__)
app.secret_key = "exam-monitor-secret-key-change-in-production"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(os.environ.get("FLASK_ENV") == "production"),
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)

db.init_app(app)
chatbot_db.init_app(app)
detector = CheatingDetector()
detector.init_app(app)
register_chatbot_routes(app)
register_calendar_routes(app)
register_auth_routes(app)
register_dashboard_routes(app)
register_settings_routes(app)
register_admin_routes(app)

login_required = auth.login_required
teacher_required = auth.teacher_required
student_required = auth.student_required
admin_required = auth.admin_required

def api_ok(payload=None, status=200):
    body = {"ok": True}
    if isinstance(payload, dict):
        body.update(payload)
    elif payload is not None:
        body["data"] = payload
    return jsonify(body), status


def api_error(message, status=400, code=None):
    body = {"ok": False, "error": message}
    if code:
        body["code"] = code
    return jsonify(body), status


def _client_ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown")


def _rate_limited(bucket, key, limit=5, window_seconds=60):
    now = time.time()
    hits = [t for t in bucket.get(key, []) if now - t < window_seconds]
    if len(hits) >= limit:
        bucket[key] = hits
        return True
    hits.append(now)
    bucket[key] = hits
    return False


def _get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.before_request
def enforce_csrf_and_session_timeout():
    # Sliding timeout for authenticated sessions.
    if session.get("logged_in"):
        session.permanent = True
        now = int(time.time())
        last_seen = int(session.get("_last_seen_at") or now)
        timeout_s = int(app.permanent_session_lifetime.total_seconds())
        if now - last_seen > timeout_s:
            session.clear()
            if request.path.startswith("/api/"):
                return api_error("Session expired", status=401, code="session_expired")
            return redirect(url_for("login"))
        session["_last_seen_at"] = now

    if request.method != "POST":
        return None

    # Skip CSRF for static and preflight-like calls.
    if request.endpoint in (None, "static"):
        return None

    sent_token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    expected = session.get("_csrf_token")
    if not expected or sent_token != expected:
        if request.path.startswith("/api/"):
            return api_error("CSRF token invalid or missing", status=400, code="csrf_invalid")
        return render_template("400.html", message="Invalid CSRF token. Please refresh and try again."), 400


@app.errorhandler(404)
def handle_not_found(err):
    if request.path.startswith("/api/"):
        return api_error("Not found", status=404, code="not_found")
    return render_template("404.html"), 404


@app.errorhandler(500)
def handle_server_error(err):
    if request.path.startswith("/api/"):
        return api_error("Internal server error", status=500, code="server_error")
    return render_template("500.html"), 500


@app.context_processor
def inject_user_ui_preferences():
    """Expose saved UI preferences to templates for global styling."""
    prefs = {
        "ui_theme": "dark",
        "ui_font": "dm",
        "ui_reduced_motion": 0,
    }
    if session.get("logged_in") and session.get("user_id"):
        try:
            user_prefs = db.get_user_preferences(session.get("user_id"))
            if user_prefs:
                prefs["ui_theme"] = user_prefs.get("ui_theme") or "dark"
                prefs["ui_font"] = user_prefs.get("ui_font") or "dm"
                prefs["ui_reduced_motion"] = int(user_prefs.get("ui_reduced_motion") or 0)
        except Exception:
            pass
    return {"user_ui_prefs": prefs, "csrf_token": _get_csrf_token()}


@app.route("/cheating-detection")
@teacher_required
def cheating_detection():
    return render_template("cheating_detection.html")


@app.route("/exam-selection")
@teacher_required
def exam_selection():
    exams = db.get_all_exams(teacher_id=session.get('teacher_id'))
    return render_template("exam_selection.html", exams=exams)


@app.route("/camera-config")
@app.route("/camera-config/<int:exam_id>")
@teacher_required
def camera_config(exam_id=None):
    teacher_id = session.get('teacher_id')
    exam = None
    if exam_id and db.exam_belongs_to_teacher(exam_id, teacher_id):
        exam = db.get_exam_by_id(exam_id)
    features = [
        {"name": "Face Detection", "description": "Track student faces to ensure they remain in frame", "enabled": True},
        {"name": "Head Movement Alerts", "description": "Flag excessive looking away from screen", "enabled": True},
        {"name": "Multiple Person Detection", "description": "Alert when more than one person appears in frame", "enabled": True},
        {"name": "Phone / Device Detection", "description": "Flag use of secondary devices", "enabled": True},
        {"name": "Tab Switch Detection", "description": "Requires browser integration. Detect leaving exam tab", "enabled": False},
    ]
    return render_template("camera_config.html", features=features, exam=exam)


@app.route("/monitoring")
@app.route("/monitoring/<int:exam_id>")
@teacher_required
def monitoring(exam_id=None):
    teacher_id = session.get('teacher_id')
    exams = db.get_all_exams(teacher_id=teacher_id)
    exam = None
    if exam_id and db.exam_belongs_to_teacher(exam_id, teacher_id):
        exam = db.get_exam_by_id(exam_id)
    students = db.get_students_in_exam(exam_id) if exam and exam_id else []
    return render_template(
        "monitoring.html",
        exams=exams,
        exam=exam,
        students=students,
        selected_id=exam['id'] if exam else None
    )


@app.route("/recordings/<path:filename>")
@login_required
def serve_recording(filename):
    recordings_dir = os.path.join(os.path.dirname(__file__), "recordings")
    return send_from_directory(recordings_dir, filename)


@app.route("/report")
@app.route("/report/<int:exam_id>")
@teacher_required
def report(exam_id=None):
    teacher_id = session.get('teacher_id')
    completed_exams = db.get_completed_exams(teacher_id=teacher_id)
    current_exam = None
    if exam_id and db.exam_belongs_to_teacher(exam_id, teacher_id):
        current_exam = db.get_exam_by_id(exam_id)
    alerts = db.get_alerts_by_exam(exam_id) if current_exam and exam_id else []
    return render_template(
        "report.html",
        exams=completed_exams,
        current_exam=current_exam,
        alerts=alerts,
        selected_id=current_exam['id'] if current_exam else None
    )


@app.route("/floor-map")
@login_required
def floor_map():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    is_teacher = session.get("role") == "teacher"
    classrooms = db.get_all_classrooms()
    return render_template("floor_map.html", is_teacher=is_teacher, classrooms=classrooms)


@app.route("/api/floor-map/rooms")
@login_required
def api_floor_map_rooms():
    if session.get("role") == "admin":
        return api_error("Forbidden", status=403, code="forbidden")
    dt_str = request.args.get("datetime")
    if dt_str:
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")[:19])
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
        except ValueError:
            dt = datetime.now()
    else:
        dt = datetime.now()
    occupancy = db.get_room_occupancy(dt)
    return api_ok({"rooms": occupancy})


@app.route("/api/floor-map/room/<room_num>/schedule")
@login_required
def api_room_schedule(room_num):
    if session.get("role") == "admin":
        return api_error("Forbidden", status=403, code="forbidden")
    if not db.get_classroom_by_room_number(room_num):
        return api_error("Invalid room", status=400, code="invalid_room")
    start_dt = datetime.now()
    end_dt = start_dt + timedelta(days=7)
    events = db.get_room_schedule(room_num, start_dt, end_dt)
    return api_ok({"room": room_num, "events": events})


# ============== Video Streaming ==============

def generate_frames():
    while True:
        frame = detector.get_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.033)
        else:
            time.sleep(0.1)


@app.route("/video_feed")
@login_required
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route("/api/exam/start", methods=["POST"])
@login_required
def start_exam():
    data = request.get_json(silent=True) or {}
    exam_id = data.get("exam_id")
    if exam_id and session.get('role') == 'teacher':
        try:
            eid = int(exam_id)
        except (TypeError, ValueError):
            eid = 0
        if not db.exam_belongs_to_teacher(eid, session.get('teacher_id')):
            return api_error("Access denied", status=403, code="access_denied")
    if exam_id:
        db.update_exam_status(exam_id, "active")
        detector.start(exam_id)
        cid = db.get_exam_classroom_id(exam_id)
        if cid:
            db.set_classroom_recording(cid, True)
    return api_ok({"status": "started"})


@app.route("/api/exam/stop", methods=["POST"])
@login_required
def stop_exam():
    output_path = detector.stop()
    exam_id = detector.current_exam_id
    if exam_id:
        cid = db.get_exam_classroom_id(exam_id)
        if cid:
            db.set_classroom_recording(cid, False)
        db.update_exam_status(exam_id, "completed", output_path)
    return api_ok({"status": "stopped", "video_path": output_path})


@app.route("/api/alerts")
@login_required
def get_alerts():
    alerts = detector.get_alerts()
    return jsonify([{
        "time": a.time,
        "label": a.label,
        "confidence": a.confidence,
        "is_danger": a.is_danger
    } for a in alerts])


@app.route("/api/debug/alert", methods=["POST"])
@login_required
def add_debug_alert():
    if session.get("role") != "teacher":
        return api_error("Forbidden", status=403, code="forbidden")
    import random

    data = request.get_json(silent=True) or {}
    if data.get("random"):
        scenarios = [
            ("cell phone", True),
            ("Peeking", False),
            ("looking away", False),
            ("multiple persons", True),
            ("head turn", False),
            ("hand under desk", True),
            ("suspicious posture", False),
            ("talking", False),
            ("notes visible", True),
        ]
        label, is_danger = random.choice(scenarios)
        confidence = round(random.uniform(0.58, 0.98), 2)
        detector._add_alert(label, confidence, is_danger)
        return api_ok({"status": "added", "label": label, "is_danger": is_danger})
    label = data.get("label", "Debug Alert")
    confidence = float(data.get("confidence", 0.85))
    is_danger = bool(data.get("is_danger", False))
    detector._add_alert(label, confidence, is_danger)
    return api_ok({"status": "added"})


@app.route("/api/debug/exam", methods=["POST"])
@login_required
def add_debug_exam():
    db = db.get_db()
    courses = db.execute('SELECT id, course_code, course_name FROM courses').fetchall()
    if not courses:
        return api_error("No courses found", status=400, code="no_courses")
    
    import random
    course = random.choice(courses)
    exam_names = ["Midterm Exam", "Final Exam", "Quiz 1", "Quiz 2", "Lab Test", "Practice Exam"]
    exam_name = random.choice(exam_names)
    
    cursor = db.execute('''
        INSERT INTO exam_sessions (course_id, exam_name, status)
        VALUES (?, ?, 'scheduled')
    ''', (course['id'], exam_name))
    db.commit()
    exam_id = cursor.lastrowid
    
    return api_ok({
        "status": "created",
        "exam_id": exam_id,
        "exam_name": f"{course['course_code']} — {exam_name}"
    })


@app.route("/api/exam/<int:exam_id>/extend", methods=["POST"])
@login_required
def extend_exam_video(exam_id):
    if session.get('role') == 'teacher' and not db.exam_belongs_to_teacher(exam_id, session.get('teacher_id')):
        return api_error("Access denied", status=403, code="access_denied")
    data = request.get_json(silent=True) or {}
    days = data.get("days", 5)
    new_expiry = db.extend_exam_expiration(exam_id, days)
    return api_ok({
        "status": "extended",
        "expires_at": new_expiry.isoformat(),
        "expires_in_seconds": (new_expiry - datetime.now()).total_seconds()
    })


@app.route("/api/exam/<int:exam_id>/delete", methods=["POST"])
@login_required
def delete_exam_api(exam_id):
    if session.get('role') == 'teacher' and not db.exam_belongs_to_teacher(exam_id, session.get('teacher_id')):
        return api_error("Access denied", status=403, code="access_denied")
    success = db.delete_exam(exam_id)
    if success:
        return api_ok({"status": "deleted"})
    return api_error("Exam not found", status=404, code="exam_not_found")


@app.route("/api/exam/<int:exam_id>/expiration")
@login_required
def get_exam_expiration_api(exam_id):
    if session.get('role') == 'teacher' and not db.exam_belongs_to_teacher(exam_id, session.get('teacher_id')):
        return api_error("Access denied", status=403, code="access_denied")
    expires_at = db.get_exam_expiration(exam_id)
    if expires_at:
        seconds_left = (expires_at - datetime.now()).total_seconds()
        return api_ok({
            "expires_at": expires_at.isoformat(),
            "expires_in_seconds": max(0, seconds_left)
        })
    return api_ok({"expires_at": None, "expires_in_seconds": None})


@app.route("/api/cleanup-expired", methods=["POST"])
@login_required
def cleanup_expired_api():
    deleted = db.cleanup_expired_videos()
    return api_ok({"status": "success", "deleted_count": deleted})


# ============== API ==============

@app.route("/api/exams")
@login_required
def api_exams():
    teacher_id = session.get('teacher_id') if session.get('role') == 'teacher' else None
    exams = db.get_all_exams(teacher_id=teacher_id)
    return api_ok({"items": [dict(e) for e in exams]})


@app.route("/api/exam/<int:exam_id>")
@login_required
def api_exam(exam_id):
    exam = db.get_exam_by_id(exam_id)
    if not exam:
        return api_error("Exam not found", status=404, code="exam_not_found")
    if session.get('role') == 'teacher' and not db.exam_belongs_to_teacher(exam_id, session.get('teacher_id')):
        return api_error("Access denied", status=403, code="access_denied")
    return api_ok({"exam": dict(exam)})


@app.route("/api/courses")
@login_required
def api_courses():
    courses = db.get_all_courses()
    return api_ok({"items": [dict(c) for c in courses]})


def run_cleanup_on_startup():
    with app.app_context():
        db.init_calendar_table()
        deleted = db.cleanup_expired_videos()
        if deleted > 0:
            print(f"Startup cleanup: Deleted {deleted} expired video(s)")


def background_cleanup_loop():
    """Background thread that checks for expired videos every 30 seconds"""
    while True:
        time.sleep(30)
        try:
            with app.app_context():
                deleted = db.cleanup_expired_videos()
                if deleted > 0:
                    print(f"Auto cleanup: Deleted {deleted} expired video(s)")
        except Exception as e:
            print(f"Cleanup error: {e}")


if __name__ == "__main__":
    run_cleanup_on_startup()
    cleanup_thread = threading.Thread(target=background_cleanup_loop, daemon=True)
    cleanup_thread.start()
    print("Background cleanup thread started (checks every 30 seconds)")
    app.run(debug=True, port=5001, threaded=True)
