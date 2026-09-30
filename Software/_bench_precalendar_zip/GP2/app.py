from flask import Flask, render_template, jsonify, request, redirect, url_for, session, Response, g, send_from_directory
from functools import wraps
from dataclasses import dataclass
from datetime import datetime, timedelta
import cv2
import threading
import time
import os
import sqlite3
import hashlib

app = Flask(__name__)
app.secret_key = "exam-monitor-secret-key-change-in-production"
DATABASE = os.path.join(os.path.dirname(__file__), 'classroom_management.db')


# ============== Database Functions ==============

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def get_user_by_email(email):
    db = get_db()
    return db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()


def verify_login(email, password):
    user = get_user_by_email(email)
    if user and user['password'] == hash_password(password):
        return user
    return None


def get_teacher_by_user_id(user_id):
    db = get_db()
    return db.execute('SELECT * FROM teachers WHERE user_id = ?', (user_id,)).fetchone()


def get_student_by_user_id(user_id):
    db = get_db()
    return db.execute('SELECT * FROM students WHERE user_id = ?', (user_id,)).fetchone()


def get_courses_by_teacher(teacher_id):
    db = get_db()
    return db.execute('''
        SELECT * FROM courses WHERE teacher_id = ?
    ''', (teacher_id,)).fetchall()


def get_all_courses():
    db = get_db()
    return db.execute('''
        SELECT c.*, u.full_name as teacher_name 
        FROM courses c
        JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
    ''').fetchall()


def get_course_by_id(course_id):
    db = get_db()
    return db.execute('''
        SELECT c.*, u.full_name as teacher_name 
        FROM courses c
        JOIN teachers t ON c.teacher_id = t.id
        JOIN users u ON t.user_id = u.id
        WHERE c.id = ?
    ''', (course_id,)).fetchone()


def get_exams_by_course(course_id):
    db = get_db()
    return db.execute('''
        SELECT * FROM exam_sessions WHERE course_id = ?
    ''', (course_id,)).fetchall()


def get_all_exams():
    db = get_db()
    return db.execute('''
        SELECT e.*, c.course_code, c.course_name
        FROM exam_sessions e
        JOIN courses c ON e.course_id = c.id
    ''').fetchall()


def get_exam_by_id(exam_id):
    db = get_db()
    return db.execute('''
        SELECT e.*, c.course_code, c.course_name
        FROM exam_sessions e
        JOIN courses c ON e.course_id = c.id
        WHERE e.id = ?
    ''', (exam_id,)).fetchone()


def get_students_in_exam(exam_id):
    db = get_db()
    return db.execute('''
        SELECT u.full_name, s.student_id
        FROM exam_enrollments ee
        JOIN students s ON ee.student_id = s.id
        JOIN users u ON s.user_id = u.id
        WHERE ee.exam_id = ?
    ''', (exam_id,)).fetchall()


def get_completed_exams():
    db = get_db()
    return db.execute('''
        SELECT e.*, c.course_code, c.course_name
        FROM exam_sessions e
        JOIN courses c ON e.course_id = c.id
        WHERE e.status = 'completed'
    ''').fetchall()


def get_alerts_by_exam(exam_id):
    db = get_db()
    return db.execute('''
        SELECT * FROM cheating_alerts 
        WHERE exam_id = ?
        ORDER BY created_at DESC
    ''', (exam_id,)).fetchall()


def create_exam(course_id, exam_name):
    db = get_db()
    cursor = db.execute('''
        INSERT INTO exam_sessions (course_id, exam_name, status)
        VALUES (?, ?, 'scheduled')
    ''', (course_id, exam_name))
    db.commit()
    return cursor.lastrowid


def update_exam_status(exam_id, status, video_path=None):
    db = get_db()
    if video_path:
        expires_at = (datetime.now() + timedelta(minutes=1)).isoformat()  # Testing: 1 min (change back to days=30 for production)
        db.execute('''
            UPDATE exam_sessions SET status = ?, video_filepath = ?, expires_at = ? WHERE id = ?
        ''', (status, video_path, expires_at, exam_id))
    else:
        db.execute('''
            UPDATE exam_sessions SET status = ? WHERE id = ?
        ''', (status, exam_id))
    db.commit()


def save_alert_to_db(exam_id, alert_type, timestamp_seconds, confidence):
    db = get_db()
    db.execute('''
        INSERT INTO cheating_alerts (exam_id, alert_type, timestamp_seconds, confidence)
        VALUES (?, ?, ?, ?)
    ''', (exam_id, alert_type, timestamp_seconds, confidence))
    db.commit()


def get_exam_expiration(exam_id):
    db = get_db()
    result = db.execute('SELECT expires_at FROM exam_sessions WHERE id = ?', (exam_id,)).fetchone()
    if result and result['expires_at']:
        return datetime.fromisoformat(result['expires_at'])
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
    if current:
        new_expiry = current + timedelta(days=days)
    else:
        new_expiry = datetime.now() + timedelta(days=days)
    db.execute('UPDATE exam_sessions SET expires_at = ? WHERE id = ?', (new_expiry.isoformat(), exam_id))
    db.commit()
    return new_expiry


def get_expired_exams():
    db = get_db()
    now = datetime.now().isoformat()
    return db.execute('''
        SELECT * FROM exam_sessions 
        WHERE expires_at IS NOT NULL AND expires_at < ? AND video_filepath IS NOT NULL
    ''', (now,)).fetchall()


def delete_exam_video(exam_id):
    db = get_db()
    exam = get_exam_by_id(exam_id)
    if exam and exam['video_filepath']:
        video_path = exam['video_filepath']
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
                print(f"Deleted video: {video_path}")
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
        if exam['video_filepath']:
            video_path = exam['video_filepath']
            if os.path.exists(video_path):
                try:
                    os.remove(video_path)
                    print(f"Deleted video: {video_path}")
                except Exception as e:
                    print(f"Error deleting video: {e}")
        db.execute('DELETE FROM cheating_alerts WHERE exam_id = ?', (exam_id,))
        db.execute('DELETE FROM exam_enrollments WHERE exam_id = ?', (exam_id,))
        db.execute('DELETE FROM exam_sessions WHERE id = ?', (exam_id,))
        db.commit()
        return True
    return False


def cleanup_expired_videos():
    expired = get_expired_exams()
    deleted_count = 0
    for exam in expired:
        if delete_exam_video(exam['id']):
            deleted_count += 1
    return deleted_count


# ============== Video Detection System ==============

@dataclass
class Alert:
    time: str
    label: str
    confidence: float
    is_danger: bool = False


class CheatingDetector:
    def __init__(self):
        self.is_running = False
        self.camera = None
        self.video_writer = None
        self.alerts = []
        self.frame = None
        self.lock = threading.Lock()
        self.phone_model = None
        self.peek_model = None
        self.models_loaded = False
        self.frame_count = 0
        self.current_phone_boxes = []
        self.current_peek_boxes = []
        self.output_path = None
        self.current_exam_id = None
        self.start_time = None
        
    def load_models(self):
        if self.models_loaded:
            return True
        try:
            from ultralytics import YOLO
            model_dir = os.path.join(os.path.dirname(__file__), "Cheating Detection")
            phone_path = os.path.join(model_dir, "phone_model.pt")
            peek_path = os.path.join(model_dir, "peek_model.pt")
            
            if os.path.exists(phone_path):
                self.phone_model = YOLO(phone_path)
            if os.path.exists(peek_path):
                self.peek_model = YOLO(peek_path)
            
            self.models_loaded = True
            print("YOLO models loaded successfully!")
            return True
        except Exception as e:
            print(f"Could not load YOLO models: {e}")
            print("Running in demo mode (camera only, no detection)")
            return False
    
    def start(self, exam_id):
        if self.is_running:
            return
        
        self.load_models()
        self.camera = cv2.VideoCapture(0)
        self.current_exam_id = exam_id
        self.start_time = time.time()
        
        if not self.camera.isOpened():
            print("Error: Could not open camera")
            return
        
        width = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = 15  # Fixed FPS for consistent playback (ML processing limits actual capture rate)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        recordings_dir = os.path.join(os.path.dirname(__file__), "recordings")
        os.makedirs(recordings_dir, exist_ok=True)
        self.output_path = os.path.join(recordings_dir, f"exam_{exam_id}_{timestamp}.mp4")
        
        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        self.video_writer = cv2.VideoWriter(self.output_path, fourcc, fps, (width, height))
        if not self.video_writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(self.output_path, fourcc, fps, (width, height))
        
        self.is_running = True
        self.alerts = []
        self.frame_count = 0
        print(f"Started recording exam {exam_id} to {self.output_path}")
        
        threading.Thread(target=self._capture_loop, daemon=True).start()
    
    def stop(self):
        self.is_running = False
        time.sleep(0.5)
        
        if self.camera:
            self.camera.release()
            self.camera = None
        
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
            print(f"Recording saved to {self.output_path}")
        
        return self.output_path
    
    def _capture_loop(self):
        target_fps = 15
        frame_interval = 1.0 / target_fps
        last_frame_time = time.time()
        
        while self.is_running and self.camera and self.camera.isOpened():
            success, frame = self.camera.read()
            if not success:
                continue
            
            current_time = time.time()
            elapsed = current_time - last_frame_time
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)
            last_frame_time = time.time()
            
            self.frame_count += 1
            
            if self.models_loaded and self.frame_count % 3 == 0:
                if self.phone_model:
                    try:
                        phone_results = self.phone_model.predict(frame, conf=0.61, imgsz=640, iou=0.45, verbose=False)
                        self.current_phone_boxes = phone_results[0].boxes
                    except:
                        pass
                
                if self.peek_model:
                    try:
                        peek_results = self.peek_model.predict(frame, conf=0.42, imgsz=640, iou=0.45, verbose=False)
                        self.current_peek_boxes = peek_results[0].boxes
                    except:
                        pass
            
            if self.phone_model:
                for box in self.current_phone_boxes:
                    class_id = int(box.cls[0])
                    class_name = self.phone_model.names[class_id]
                    if class_name.lower() == "normal":
                        continue
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    confidence = float(box.conf[0])
                    label = f"{class_name.title()} ({confidence:.2f})"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    
                    if self.frame_count % 30 == 0:
                        self._add_alert(class_name, confidence, is_danger=True)
            
            if self.peek_model:
                for box in self.current_peek_boxes:
                    class_id = int(box.cls[0])
                    class_name = self.peek_model.names[class_id]
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    confidence = float(box.conf[0])
                    label = f"{class_name.title()} ({confidence:.2f})"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
                    
                    if self.frame_count % 30 == 0:
                        self._add_alert(class_name, confidence, is_danger=False)
            
            if self.video_writer:
                self.video_writer.write(frame)
            
            with self.lock:
                self.frame = frame
    
    def _add_alert(self, label, confidence, is_danger):
        timestamp = datetime.now().strftime("%H:%M:%S")
        alert = Alert(time=timestamp, label=label, confidence=confidence, is_danger=is_danger)
        self.alerts.insert(0, alert)
        if len(self.alerts) > 50:
            self.alerts = self.alerts[:50]
        
        if self.current_exam_id and self.start_time:
            elapsed = time.time() - self.start_time
            try:
                with app.app_context():
                    save_alert_to_db(self.current_exam_id, label, elapsed, confidence)
            except:
                pass
    
    def get_frame(self):
        with self.lock:
            if self.frame is None:
                return None
            ret, jpeg = cv2.imencode('.jpg', self.frame)
            return jpeg.tobytes() if ret else None
    
    def get_alerts(self):
        return self.alerts


detector = CheatingDetector()


# ============== Auth ==============

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "teacher":
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# ============== Routes ==============

@app.route("/")
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        user = verify_login(email, password)
        if user:
            session["logged_in"] = True
            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            session["role"] = user["role"]
            
            if user["role"] == "teacher":
                teacher = get_teacher_by_user_id(user["id"])
                if teacher:
                    session["teacher_id"] = teacher["id"]
            
            return redirect(url_for("dashboard"))
        error = "Invalid email or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/cheating-detection")
@login_required
def cheating_detection():
    return render_template("cheating_detection.html")


@app.route("/exam-selection")
@login_required
def exam_selection():
    exams = get_all_exams()
    return render_template("exam_selection.html", exams=exams)


@app.route("/camera-config")
@app.route("/camera-config/<int:exam_id>")
@login_required
def camera_config(exam_id=None):
    exam = get_exam_by_id(exam_id) if exam_id else None
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
@login_required
def monitoring(exam_id=None):
    exams = get_all_exams()
    exam = get_exam_by_id(exam_id) if exam_id else None
    students = get_students_in_exam(exam_id) if exam_id else []
    return render_template(
        "monitoring.html",
        exams=exams,
        exam=exam,
        students=students,
        selected_id=exam_id
    )


@app.route("/recordings/<path:filename>")
@login_required
def serve_recording(filename):
    recordings_dir = os.path.join(os.path.dirname(__file__), "recordings")
    return send_from_directory(recordings_dir, filename)


@app.route("/report")
@app.route("/report/<int:exam_id>")
@login_required
def report(exam_id=None):
    completed_exams = get_completed_exams()
    current_exam = get_exam_by_id(exam_id) if exam_id else None
    alerts = get_alerts_by_exam(exam_id) if exam_id else []
    return render_template(
        "report.html",
        exams=completed_exams,
        current_exam=current_exam,
        alerts=alerts,
        selected_id=exam_id
    )


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
    exam_id = request.json.get("exam_id")
    if exam_id:
        update_exam_status(exam_id, "active")
        detector.start(exam_id)
    return jsonify({"status": "started"})


@app.route("/api/exam/stop", methods=["POST"])
@login_required
def stop_exam():
    output_path = detector.stop()
    exam_id = detector.current_exam_id
    if exam_id:
        update_exam_status(exam_id, "completed", output_path)
    return jsonify({"status": "stopped", "video_path": output_path})


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
    data = request.json
    label = data.get("label", "Debug Alert")
    confidence = data.get("confidence", 0.85)
    is_danger = data.get("is_danger", False)
    detector._add_alert(label, confidence, is_danger)
    return jsonify({"status": "added"})


@app.route("/api/debug/exam", methods=["POST"])
@login_required
def add_debug_exam():
    db = get_db()
    courses = db.execute('SELECT id, course_code, course_name FROM courses').fetchall()
    if not courses:
        return jsonify({"status": "error", "message": "No courses found"}), 400
    
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
    
    return jsonify({
        "status": "created",
        "exam_id": exam_id,
        "exam_name": f"{course['course_code']} — {exam_name}"
    })


@app.route("/api/exam/<int:exam_id>/extend", methods=["POST"])
@login_required
def extend_exam_video(exam_id):
    days = request.json.get("days", 5)
    new_expiry = extend_exam_expiration(exam_id, days)
    return jsonify({
        "status": "extended",
        "expires_at": new_expiry.isoformat(),
        "expires_in_seconds": (new_expiry - datetime.now()).total_seconds()
    })


@app.route("/api/exam/<int:exam_id>/delete", methods=["POST"])
@login_required
def delete_exam_api(exam_id):
    success = delete_exam(exam_id)
    if success:
        return jsonify({"status": "deleted"})
    return jsonify({"status": "error", "message": "Exam not found"}), 404


@app.route("/api/exam/<int:exam_id>/expiration")
@login_required
def get_exam_expiration_api(exam_id):
    expires_at = get_exam_expiration(exam_id)
    if expires_at:
        seconds_left = (expires_at - datetime.now()).total_seconds()
        return jsonify({
            "expires_at": expires_at.isoformat(),
            "expires_in_seconds": max(0, seconds_left)
        })
    return jsonify({"expires_at": None, "expires_in_seconds": None})


@app.route("/api/cleanup-expired", methods=["POST"])
@login_required
def cleanup_expired_api():
    deleted = cleanup_expired_videos()
    return jsonify({"status": "success", "deleted_count": deleted})


# ============== API ==============

@app.route("/api/exams")
@login_required
def api_exams():
    exams = get_all_exams()
    return jsonify([dict(e) for e in exams])


@app.route("/api/exam/<int:exam_id>")
@login_required
def api_exam(exam_id):
    exam = get_exam_by_id(exam_id)
    if not exam:
        return jsonify({"error": "Exam not found"}), 404
    return jsonify(dict(exam))


@app.route("/api/courses")
@login_required
def api_courses():
    courses = get_all_courses()
    return jsonify([dict(c) for c in courses])


def run_cleanup_on_startup():
    with app.app_context():
        deleted = cleanup_expired_videos()
        if deleted > 0:
            print(f"Startup cleanup: Deleted {deleted} expired video(s)")


def background_cleanup_loop():
    """Background thread that checks for expired videos every 30 seconds"""
    while True:
        time.sleep(30)
        try:
            with app.app_context():
                deleted = cleanup_expired_videos()
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
