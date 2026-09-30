import os
import re
import time
from datetime import datetime, timedelta

from flask import jsonify, redirect, render_template, request, session, url_for

from core import auth, chatbot_db, db
from services import calendar_service
from services.chatbot_intents import (
    any_match as _any_match,
    extract_course_from_message as _extract_course_from_message,
    extract_date_hint as _extract_date_hint,
    extract_kv_command as _extract_kv_command,
    extract_room_from_text as _extract_room_from_text,
    extract_time_range_from_text as _extract_time_range_from_text,
    format_actionable_events as _format_actionable_events,
    fuzzy_contains as _fuzzy_contains,
    intent_with_typos as _intent_with_typos,
    normalize_message as _normalize_message,
    parse_natural_datetime as _parse_natural_datetime,
)


def register_chatbot_routes(app):
    def _is_question_like(text_l):
        return bool(
            re.search(r"\b(what|how|where|when|who|can|could|should|why)\b", text_l)
            or text_l.endswith("?")
            or "help" in text_l
        )

    login_required = auth.login_required
    chatbot_attempts = {}

    def _rate_limited_chatbot(key, limit=5, window_seconds=60):
        now = time.time()
        hits = [t for t in chatbot_attempts.get(key, []) if now - t < window_seconds]
        if len(hits) >= limit:
            chatbot_attempts[key] = hits
            return True
        hits.append(now)
        chatbot_attempts[key] = hits
        return False

    @app.route("/chatbot")
    @login_required
    def chatbot():
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        role = session.get("role", "student")
        user_name = session.get("user_name", "")
        teacher_courses = []
        student_courses = []
        if role == "teacher" and session.get("teacher_id"):
            teacher_courses = db.get_courses_by_teacher(session["teacher_id"]) or []
        if role == "student":
            student = db.get_student_by_user_id(session.get("user_id"))
            if student:
                student_courses = [dict(c) for c in db.get_courses_for_student(student["id"])]
        return render_template("chatbot.html", role=role, user_name=user_name, teacher_courses=teacher_courses, student_courses=student_courses)

    @app.route("/api/chatbot", methods=["POST"])
    @login_required
    def api_chatbot():
        if session.get("role") == "admin":
            return jsonify({"error": "Forbidden"}), 403
        user_key = f"{session.get('user_id') or 'anon'}:{request.remote_addr or 'ip'}"
        if _rate_limited_chatbot(user_key, limit=20, window_seconds=60):
            return jsonify({"error": "Too many requests. Please wait a minute."}), 429
        data = request.get_json() or {}
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "Message is required"}), 400

        api_key = (os.environ.get("GEMINI_API_KEY") or "").strip().strip('"').strip("'")
        if not api_key:
            return jsonify({"reply": "Chatbot is not configured. Set GEMINI_API_KEY in .env."}), 200

        user_name = session.get("user_name", "the user")
        user_role = session.get("role", "user")
        session_dict = {"user_id": session.get("user_id"), "role": user_role, "teacher_id": session.get("teacher_id")}
        try:
            upcoming = calendar_service.get_upcoming_events_for_chatbot(session_dict)
        except Exception:
            upcoming = []
        try:
            announcements = calendar_service.get_upcoming_announcements_for_chatbot(session_dict)
        except Exception:
            announcements = []

        message_l = _normalize_message(message)

        if _intent_with_typos(
            message_l,
            [r"\b(add|create|schedule)\s+(an?\s+)?(event|class|exam|reminder)\b", r"\badd\s+to\s+calendar\b"],
            ["add event", "create event", "schedule event", "add to calendar"],
        ):
            return jsonify({
                "reply": "Event creation via chatbot is disabled. Please use the Calendar page to add or edit events.",
                "meta": {"confidence": "high", "sources": ["guardrail"]},
            })

        if any(k in message_l for k in ["announcement", "announcements", "reminder", "reminders"]):
            reply = f"Hi {user_name}! Here are your upcoming announcements/reminders:\n" + _format_actionable_events(announcements[:8])
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["calendar", "announcements"]}})

        if _intent_with_typos(message_l, [
            r"\b(what\s+do\s+i\s+have\s+today|today'?s?\s+schedule|today\s+schedule|my\s+schedule\s+today|what'?s\s+today)\b",
            r"\b(today|tonight)\b.*\b(classes?|exams?|schedule|plan)\b",
        ], ["today schedule", "my schedule today", "what do i have today"]):
            today_start = datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S")
            today_end = (datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
            today_events = [e for e in upcoming if e.get("start") and today_start <= str(e.get("start", "")) < today_end]
            reply = f"Hi {user_name}! Here's your schedule for today:\n" + _format_actionable_events(today_events[:12])
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["calendar"]}})

        if _intent_with_typos(
            message_l,
            [
                r"\b(tomorrow'?s?\s+schedule|schedule\s+for\s+tomorrow|what\s+do\s+i\s+have\s+tomorrow)\b",
                r"\btomorrow\b.*\b(classes?|exams?|schedule|plan)\b",
            ],
            ["tomorrow schedule", "my schedule tomorrow", "what do i have tomorrow"],
        ):
            t0 = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
            t1 = t0 + timedelta(days=1)
            tomorrow_start = t0.strftime("%Y-%m-%dT%H:%M:%S")
            tomorrow_end = t1.strftime("%Y-%m-%dT%H:%M:%S")
            tomorrow_events = [e for e in upcoming if e.get("start") and tomorrow_start <= str(e.get("start", "")) < tomorrow_end]
            reply = f"Hi {user_name}! Here's your schedule for tomorrow:\n" + _format_actionable_events(tomorrow_events[:12])
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["calendar"]}})

        if _intent_with_typos(message_l, [r"\b(upcoming|next|schedule|exam|class|classes|assignment|assignments)\b"], ["upcoming exams", "upcoming classes", "next exam"]) and not _any_match(
            message_l, [r"\bcheck\s+conflict\b", r"\bis\s+room\b", r"\brooms?\s+available\b", r"\brooms?\s+free\b"]
        ):
            filtered = upcoming
            label = "upcoming events"
            if "exam" in message_l:
                filtered = [e for e in upcoming if e.get("event_type") == "exam"]
                label = "upcoming exams"
            elif "assignment" in message_l:
                filtered = [e for e in upcoming if e.get("event_type") == "assignment"]
                label = "upcoming assignments"
            elif "class" in message_l or "classes" in message_l:
                filtered = [e for e in upcoming if e.get("event_type") in ("class", "lecture")]
                label = "upcoming classes"
            reply = f"Hi {user_name}! Here are your {label}:\n" + _format_actionable_events(filtered[:8])
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["calendar"]}})

        if user_role == "student" and _intent_with_typos(
            message_l,
            [
                r"\b(list|show|display)\s+my\s+courses\b",
                r"\bmy\s+courses\b",
                r"\bwhat\s+courses\b",
                r"\bcourses?\s+am\s+i\s+in\b",
                r"\benrolled\s+courses\b",
                r"\bwhat\s+am\s+i\s+taking\b",
            ],
            ["my courses", "list my courses", "show my courses"],
        ) and "teach" not in message_l and "who " not in message_l:
            student = db.get_student_by_user_id(session.get("user_id"))
            courses = [dict(c) for c in db.get_courses_for_student(student["id"])] if student else []
            if not courses:
                return jsonify({"reply": "You're not enrolled in any courses yet.", "meta": {"confidence": "high", "sources": ["database"]}})
            lines = []
            for c in courses:
                code = c.get("course_code") or "?"
                name = c.get("course_name") or "Unknown"
                sec = c.get("section_number", 1)
                teacher = c.get("teacher_name") or "TBD"
                lines.append(f"- {code} - {name} (Section {sec}) — {teacher}")
            reply = f"Hi {user_name}! Here are your courses:\n" + "\n".join(lines)
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["database"]}})

        if _intent_with_typos(message_l, [r"\bwho\s+teaches\b", r"\bwho\s+is\s+the\s+professor\b", r"\binstructor\s+for\b", r"\bprofessor\s+for\b", r"\bteacher\s+for\b", r"\bwho'?s\s+the\s+teacher\b"], ["who teaches", "instructor for", "professor for"]):
            all_courses = db.get_all_courses()
            course_ref = _extract_course_from_message(message_l, all_courses)
            if not course_ref:
                return jsonify({"reply": "Which course? Specify a course code, e.g. CS101.", "meta": {"confidence": "high", "sources": ["guardrail"]}})
            code = course_ref.get("course_code") or "?"
            name = course_ref.get("course_name") or "Unknown"
            teacher = course_ref.get("teacher_name") or "TBD"
            reply = f"Hi {user_name}! {name} ({code}) is taught by {teacher}."
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["database"]}})

        if _intent_with_typos(message_l, [r"\b(where\s+is|exam\s+location|exam\s+room|where'?s\s+my|what\s+room)\b"], ["exam location", "exam room", "where is my exam"]) and ("exam" in message_l or _fuzzy_contains(message_l, "exam")):
            exam_events = [e for e in upcoming if e.get("event_type") == "exam"]
            course_ref = _extract_course_from_message(message_l, exam_events)
            if not exam_events:
                reply = f"Hi {user_name}! You don't have any upcoming exams in the next 14 days."
            elif not course_ref and ("next" in message_l or "first" in message_l):
                e = exam_events[0]
                loc = e.get("location") or "TBD"
                reply = f"Hi {user_name}! Your next exam ({e.get('course', 'exam')}) is in {loc}."
            elif not course_ref:
                reply = f"Hi {user_name}! Which exam? Your upcoming exams:\n" + _format_actionable_events(exam_events[:5])
            else:
                loc = course_ref.get("location") or "TBD"
                reply = f"Hi {user_name}! Your {course_ref.get('course', 'exam')} exam is in {loc}."
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["calendar"]}})

        if _intent_with_typos(message_l, [r"\bwhen\s+does\b", r"\bmeet\b", r"\bcourse\s+schedule\b", r"\bclass\s+schedule\b"], ["course schedule", "class schedule", "when does"]) or re.search(r"schedule\s+(for\s+)?[a-z]{2,5}\s*\d{3,4}", message_l, re.I):
            enrolled_ids = []
            if user_role == "student":
                student = db.get_student_by_user_id(session.get("user_id"))
                if student:
                    enrolled_ids = db.get_course_ids_for_student(student["id"])
            all_courses = db.get_all_courses()
            course_ref = _extract_course_from_message(message_l, all_courses)
            course_id = course_ref.get("id") if course_ref else None
            course_name = (course_ref.get("course_name") or course_ref.get("course_code")) if course_ref else None
            if not course_id:
                return jsonify({"reply": "Which course? Specify a course code, e.g. CS101.", "meta": {"confidence": "high", "sources": ["guardrail"]}})
            if user_role == "student" and enrolled_ids and course_id not in enrolled_ids:
                return jsonify({"reply": f"You're not enrolled in {course_name}. You can only view schedules for your enrolled courses.", "meta": {"confidence": "high", "sources": ["guardrail"]}})
            classes = calendar_service.get_course_class_schedule(course_id)
            if not classes:
                reply = f"Hi {user_name}! No scheduled classes for {course_name} in the next 30 days."
            else:
                lines = [f"- {e['title']}: {e['start_fmt']} - {e['end_fmt']}" + (f" @ {e['location']}" if e.get("location") else "") for e in classes]
                reply = f"Hi {user_name}! {course_name} upcoming classes:\n" + "\n".join(lines)
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["calendar"]}})

        if _intent_with_typos(
            message_l,
            [
                r"\brooms?\s+available\b",
                r"\brooms?\s+free\b",
                r"\bwhich\s+rooms?\b",
                r"\bavailable\s+rooms?\b",
                r"\bfree\s+rooms?\b",
                r"\bempty\s+rooms?\b",
                r"\bclassrooms?\s+available\b",
                r"\bclassrooms?\s+free\b",
            ],
            ["rooms available", "rooms free", "available rooms", "free classrooms", "available classroom"],
        ):
            rooms_cmd = _extract_kv_command(message, "rooms available")
            if rooms_cmd:
                date_text = rooms_cmd.get("date", "today")
                start_text = rooms_cmd.get("start", "9am")
                end_text = rooms_cmd.get("end", "11am")
            else:
                date_text = _extract_date_hint(message_l)
                start_text, end_text = _extract_time_range_from_text(message_l, "9am", "11am")
            start_dt = _parse_natural_datetime(date_text, start_text)
            end_dt = _parse_natural_datetime(date_text, end_text)
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(hours=1)
            available = calendar_service.get_available_rooms(
                start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            if not available:
                reply = f"No rooms are available from {start_dt.strftime('%I:%M %p')} to {end_dt.strftime('%I:%M %p')} on {start_dt.strftime('%A, %B %d')}."
            else:
                reply = f"Rooms available from {start_dt.strftime('%I:%M %p')} to {end_dt.strftime('%I:%M %p')} on {start_dt.strftime('%A, %B %d')}: {', '.join(available)}"
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["calendar"]}})

        if user_role == "teacher" and _intent_with_typos(
            message_l,
            [
                r"\b(list|show|display)\s+my\s+courses\b",
                r"\bmy\s+courses\b",
                r"\bwhat\s+courses\b",
                r"\bcourses?\s+i\s+teach\b",
                r"\bcourses?\s+do\s+i\s+teach\b",
                r"\bmy\s+teaching\s+courses\b",
            ],
            ["my courses", "courses i teach", "show my courses"],
        ) and "enroll" not in message_l and "student" not in message_l:
            teacher_id = session.get("teacher_id")
            courses_raw = db.get_courses_by_teacher(teacher_id) or [] if teacher_id else []
            courses = [dict(c) for c in courses_raw]
            if not courses:
                return jsonify({"reply": "You don't have any courses assigned yet.", "meta": {"confidence": "high", "sources": ["database"]}})
            lines = []
            for c in courses:
                code = c.get("course_code") or "?"
                name = c.get("course_name") or "Unknown"
                sec = c.get("section_number", 1)
                lines.append(f"- {code} - {name} (Section {sec})")
            reply = f"Hi {user_name}! Here are your courses:\n" + "\n".join(lines)
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["database"]}})

        if user_role == "teacher" and _intent_with_typos(
            message_l,
            [
                r"\bhow\s+many\s+students\b",
                r"\bstudents\s+in\b",
                r"\benrolled\s+in\b",
                r"\benrollment\b",
                r"\bwho\s+is\s+in\b",
                r"\bwho'?s\s+in\b",
                r"\benrollment\s+for\b",
                r"\blist\s+students\b",
                r"\bshow\s+students\b",
                r"\bstudent\s+names?\b",
                r"\bnames?\s+of\s+students\b",
                r"\bnames?\s+in\b",
            ],
            ["how many students", "students in", "enrollment for", "list students", "student names"],
        ):
            teacher_id = session.get("teacher_id")
            teacher_courses_raw = db.get_courses_by_teacher(teacher_id) or [] if teacher_id else []
            teacher_courses = [dict(c) for c in teacher_courses_raw]
            selected_course = _extract_course_from_message(message_l, teacher_courses)
            course_ref = None
            course_id = None
            course_name = None
            if selected_course:
                course_ref = selected_course.get("course_code")
                course_id = selected_course.get("id")
                course_name = selected_course.get("course_name") or course_ref
            if not course_ref:
                codes = ", ".join((c.get("course_code") or "?") for c in teacher_courses)
                return jsonify({"reply": f"Which course? Specify a course code, e.g. CS101. Your courses: {codes or 'none'}.", "meta": {"confidence": "high", "sources": ["guardrail"]}})
            students_raw = db.get_enrolled_students(course_id) or []
            students = [dict(s) for s in students_raw]
            count = len(students)
            if "how many" in message_l or "count" in message_l or "number" in message_l:
                reply = f"Hi {user_name}! {course_name} ({course_ref}) has {count} enrolled student{'s' if count != 1 else ''}."
            else:
                if not students:
                    reply = f"Hi {user_name}! No students are enrolled in {course_name} ({course_ref}) yet."
                else:
                    names = [s.get("full_name") or s.get("sid") or "Unknown" for s in students]
                    reply = f"Hi {user_name}! Students enrolled in {course_name} ({course_ref}) ({count} total):\n" + "\n".join(f"- {n}" for n in names[:20])
                    if count > 20:
                        reply += f"\n... and {count - 20} more"
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["database"]}})

        conflict_cmd = _extract_kv_command(message, "check conflict")
        if not conflict_cmd and _intent_with_typos(message_l, [r"\bcheck\s+conflict\b", r"\broom\s+conflict\b", r"\bis\s+room\b.*\b(free|available)\b"], ["check conflict", "room conflict", "is room free"]):
            room_hint = _extract_room_from_text(message_l)
            date_hint = _extract_date_hint(message_l)
            start_hint, end_hint = _extract_time_range_from_text(message_l, "9am", "10am")
            conflict_cmd = {"room": room_hint or "", "date": date_hint, "start": start_hint, "end": end_hint}
        if conflict_cmd:
            room = conflict_cmd.get("room") or conflict_cmd.get("location")
            date_text = conflict_cmd.get("date", "today")
            start_text = conflict_cmd.get("start", "9am")
            end_text = conflict_cmd.get("end", "10am")
            if not room:
                return jsonify({"reply": "Specify the room. Example: check conflict: room=1001, date=tomorrow, start=9am, end=11am", "meta": {"confidence": "high", "sources": ["guardrail"]}})
            start_dt = _parse_natural_datetime(date_text, start_text)
            end_dt = _parse_natural_datetime(date_text, end_text)
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(hours=1)
            has_conflict, owner = calendar_service.check_location_conflict(
                room,
                start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            if has_conflict:
                reply = f"Room {room} is NOT available from {start_dt.strftime('%I:%M %p')} to {end_dt.strftime('%I:%M %p')} ({owner} already booked it)."
            else:
                reply = f"Room {room} looks available from {start_dt.strftime('%I:%M %p')} to {end_dt.strftime('%I:%M %p')}."
            return jsonify({"reply": reply, "meta": {"confidence": "high", "sources": ["calendar_conflict"]}})

        kb_ranked = chatbot_db.search_kb_ranked(message, limit=5)
        kb_entries = [{"question": e["question"], "answer": e["answer"]} for e in kb_ranked]
        top_kb = kb_ranked[0] if kb_ranked else None

        # Tier 2 fallback: answer directly from KB when confidence is strong.
        if top_kb and (_is_question_like(message_l) or len(message_l.split()) <= 8):
            if top_kb.get("score", 0) >= 0.72:
                kb_conf = "high" if top_kb["score"] >= 0.86 else "medium"
                reply = top_kb["answer"]
                return jsonify({
                    "reply": reply,
                    "meta": {
                        "confidence": kb_conf,
                        "sources": ["kb"],
                        "tier": "kb",
                        "kb_question": top_kb["question"],
                        "kb_score": top_kb["score"],
                    },
                })
        kb_context = ""
        if kb_entries:
            kb_context = "\n\nRelevant knowledge base entries:\n"
            for e in kb_entries:
                kb_context += f"- Q: {e['question']}\n  A: {e['answer']}\n"

        teachers = chatbot_db.get_teachers_for_rag()
        teacher_context = ""
        if teachers:
            teacher_context = "\n\nTeacher directory:\n"
            for t in teachers:
                parts = [f"{t['full_name']} ({t['email']})"]
                if t.get("department"):
                    parts.append(f"Department: {t['department']}")
                if t.get("office_number"):
                    parts.append(f"Office: {t['office_number']}")
                teacher_context += "- " + ", ".join(parts) + "\n"

        role_behavior = (
            "If user role is student, focus on their personal/enrolled schedule. "
            "If user role is teacher, focus on their courses, scheduling, room conflicts, and teaching support. "
            "If information is missing, explicitly say you're not fully sure and ask one clarifying question. "
            "You cannot add events via chat. If the user asks to add an event, direct them to use the Calendar page instead. "
            "Never guess a course if the user message could match multiple courses; ask for the exact course code. "
            "If an answer is not grounded in calendar/database/kb context, explicitly say uncertainty and ask a short follow-up."
        )
        calendar_context = "\n\nUpcoming events for this user:\n" + _format_actionable_events(upcoming[:10]) if upcoming else "\n\nNo upcoming events for this user in next 14 days."
        announcement_context = "\n\nUpcoming announcements/reminders:\n" + _format_actionable_events(announcements[:10]) if announcements else ""
        user_context = f"\n\nThe current user is {user_name} (role: {user_role})."

        system_prompt = (
            "You are a helpful classroom assistant. Give actionable answers with concrete names/dates/locations when available. "
            "Never reveal or ask for passwords. "
            + role_behavior
            + user_context
            + kb_context
            + teacher_context
            + calendar_context
            + announcement_context
        )

        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_prompt)
            response = model.generate_content(message)
            reply = response.text or "I couldn't generate a response."
            confidence = "low"
            sources = []
            if upcoming:
                sources.append("calendar")
            if kb_entries:
                sources.append("kb")
            if teachers:
                sources.append("teacher_directory")
            if announcements:
                sources.append("announcements")
            if not sources:
                sources = ["llm"]
            elif len(sources) >= 2:
                confidence = "medium"
            if len(sources) >= 3:
                confidence = "high"
        except Exception as e:
            reply = f"I’m not fully sure right now because of a processing issue: {str(e)}"
            confidence = "low"
            sources = ["guardrail"]
        return jsonify({"reply": reply, "meta": {"confidence": confidence, "sources": sources, "tier": "llm"}})

    @app.route("/api/chatbot/feedback", methods=["POST"])
    @login_required
    def api_chatbot_feedback():
        if session.get("role") == "admin":
            return jsonify({"error": "Forbidden"}), 403
        payload = request.get_json() or {}
        row_id = payload.get("feedback_id")
        vote = (payload.get("feedback") or "").strip().lower()
        note = (payload.get("note") or "").strip()

        if row_id:
            if vote not in ("up", "down", ""):
                return jsonify({"error": "Invalid feedback value"}), 400
            ok = db.update_chat_feedback_vote(row_id, vote or None, note or None)
            return jsonify({"ok": bool(ok)})

        user_message = (payload.get("user_message") or "").strip()
        bot_reply = (payload.get("bot_reply") or "").strip()
        if not user_message or not bot_reply:
            return jsonify({"error": "user_message and bot_reply are required"}), 400

        meta = payload.get("meta") or {}
        confidence = (meta.get("confidence") or "").strip()
        sources = meta.get("sources") or []
        if isinstance(sources, list):
            sources_str = ", ".join(str(s).strip() for s in sources if str(s).strip())
        else:
            sources_str = str(sources).strip()

        feedback_id = db.add_chat_feedback(
            session.get("user_id"),
            session.get("role"),
            user_message,
            bot_reply,
            confidence=confidence or None,
            sources=sources_str or None,
            feedback=vote if vote in ("up", "down") else None,
            note=note or None,
        )
        return jsonify({"ok": True, "feedback_id": feedback_id})
