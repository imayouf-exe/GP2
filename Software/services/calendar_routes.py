from datetime import datetime, timedelta

from flask import jsonify, render_template, request, session

from core import auth, db
from services import calendar_service


def register_calendar_routes(app):
    login_required = auth.login_required
    student_required = auth.student_required
    teacher_required = auth.teacher_required

    @app.route("/calendar")
    @teacher_required
    def calendar():
        teacher_id = session.get('teacher_id')
        courses = db.get_courses_by_teacher(teacher_id) if teacher_id else []
        classrooms = db.get_all_classrooms()
        return render_template("calendar.html", courses=courses, is_student=False, classrooms=classrooms)

    @app.route("/student-calendar")
    @student_required
    def student_calendar():
        return render_template("student_calendar.html", is_student=True)

    @app.route("/api/calendar/events", methods=["GET"])
    @login_required
    def get_calendar_events():
        try:
            events = calendar_service.get_calendar_events()
            return jsonify(events)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(ex)}), 500

    @app.route("/api/calendar/events", methods=["POST"])
    @login_required
    def create_calendar_event():
        resp, status = calendar_service.create_calendar_event(request, session)
        return jsonify(resp), status

    @app.route("/api/calendar/events/<event_id>", methods=["DELETE"])
    @login_required
    def delete_calendar_event(event_id):
        database = db.get_db()
        role = session.get('role')
        user_id = session.get('user_id')
        print(f"Deleting event: {event_id}")

        if role == "student":
            if event_id.startswith("exam_"):
                return jsonify({"error": "Students cannot delete exam events"}), 403
            if event_id.startswith("event_"):
                ev_id = int(event_id.replace("event_", ""))
                row = database.execute('SELECT user_id FROM calendar_events WHERE id = ?', (ev_id,)).fetchone()
                if not row or row['user_id'] != user_id:
                    return jsonify({"error": "You can only delete your own personal events"}), 403

        if role == "admin":
            if event_id.startswith("exam_"):
                return jsonify({"error": "Admin cannot delete exam events"}), 403
            if event_id.startswith("event_"):
                ev_id = int(event_id.replace("event_", ""))
                ev = database.execute('SELECT calendar_type FROM calendar_events WHERE id = ?', (ev_id,)).fetchone()
                if not ev or ev['calendar_type'] != 'global':
                    return jsonify({"error": "Admin can only delete global calendar events"}), 403

        if role == "teacher":
            teacher_id = session.get('teacher_id')
            teacher_course_ids = [c['id'] for c in db.get_courses_by_teacher(teacher_id)] if teacher_id else []
            if event_id.startswith("exam_"):
                exam_id = int(event_id.replace("exam_", ""))
                exam = database.execute('SELECT course_id FROM exam_sessions WHERE id = ?', (exam_id,)).fetchone()
                if exam and exam['course_id'] not in teacher_course_ids:
                    return jsonify({"error": "You can only delete exams for your own courses"}), 403
            elif event_id.startswith("event_"):
                ev_id = int(event_id.replace("event_", ""))
                ev = database.execute('SELECT course_id, calendar_type FROM calendar_events WHERE id = ?', (ev_id,)).fetchone()
                if ev and ev['calendar_type'] == 'course' and ev['course_id'] and ev['course_id'] not in teacher_course_ids:
                    return jsonify({"error": "You can only delete events for your own courses"}), 403

        if event_id.startswith("exam_"):
            exam_id = int(event_id.replace("exam_", ""))
            database.execute('DELETE FROM cheating_alerts WHERE exam_id = ?', (exam_id,))
            database.execute('DELETE FROM exam_sessions WHERE id = ?', (exam_id,))
            print(f"Deleted exam {exam_id} and its alerts")
        elif event_id.startswith("event_"):
            ev_id = int(event_id.replace("event_", ""))
            database.execute('DELETE FROM calendar_events WHERE id = ?', (ev_id,))
            print(f"Deleted calendar event {ev_id}")
        else:
            print(f"Unknown event ID format: {event_id}")
            return jsonify({"error": "Invalid event ID format"}), 400

        database.commit()
        return jsonify({"status": "deleted"})
