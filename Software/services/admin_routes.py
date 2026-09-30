from flask import render_template, request, redirect, url_for, session

from core import auth
from core import db
from core import chatbot_db
from services import admin_service


def register_admin_routes(app):
    def _audit(action, target_type=None, target_id=None, details=None, outcome="success"):
        try:
            db.add_admin_audit_log(
                admin_user_id=session.get("user_id"),
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
                outcome=outcome,
                ip_address=(request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or None),
                user_agent=(request.headers.get("User-Agent") or "")[:255],
            )
        except Exception:
            # Avoid blocking admin workflows if migrations are not applied yet.
            pass

    def admin_users():
        if request.method == "POST":
            redirect_name, ctx = admin_service.handle_admin_users_post(request)
            action = (request.form.get("action") or "").strip()
            outcome = "error" if ctx else "success"
            _audit(
                action=f"admin_users:{action or 'unknown'}",
                target_type="user",
                target_id=request.form.get("teacher_id") or request.form.get("student_id"),
                details=f"email={request.form.get('email', '')[:120]}",
                outcome=outcome,
            )
            if redirect_name:
                return redirect(url_for(redirect_name))
            if ctx:
                return render_template("admin_users.html", **ctx)
        return render_template(
            "admin_users.html",
            teachers=admin_service.get_teachers_for_users_page(),
            students=db.admin_get_all_students(),
            departments=db.get_departments(),
            majors=db.get_majors(),
        )

    def admin_courses():
        teachers = db.admin_get_all_teachers()
        students = db.admin_get_all_students_for_select()
        courses = db.get_all_courses()
        unassigned_id = db.get_unassigned_teacher_id()
        selectable_teachers = [t for t in teachers if t["id"] != unassigned_id] if unassigned_id else teachers
        course_enrollments_data = {c["id"]: db.get_enrolled_students(c["id"]) for c in courses}

        def _render(error=None):
            return render_template(
                "admin_courses.html",
                teachers=teachers,
                selectable_teachers=selectable_teachers,
                students=students,
                courses=courses,
                course_enrollments=course_enrollments_data,
                unassigned_teacher_id=unassigned_id,
                error=error,
            )

        if request.method == "POST":
            redirect_name, err = admin_service.handle_admin_courses_post(request)
            action = (request.form.get("action") or "").strip()
            outcome = "error" if err else "success"
            _audit(
                action=f"admin_courses:{action or 'unknown'}",
                target_type="course",
                target_id=request.form.get("course_id"),
                details=f"student_id={request.form.get('student_id') or request.form.get('student_id_str') or ''}",
                outcome=outcome,
            )
            if redirect_name:
                return redirect(url_for(redirect_name))
            if err:
                return _render(err)
        return _render()

    def admin_calendar():
        classrooms = db.get_all_classrooms()
        return render_template("admin_calendar.html", classrooms=classrooms)

    def admin_chatbot_kb():
        if request.method == "POST":
            action = request.form.get("action", "")
            outcome = "success"
            if action == "add":
                q = request.form.get("question", "").strip()
                a = request.form.get("answer", "").strip()
                cat = request.form.get("category", "").strip() or None
                if q and a and chatbot_db.add_entry(q, a, cat):
                    _audit("admin_chatbot_kb:add", target_type="kb", details=f"question={q[:120]}", outcome="success")
                    return redirect(url_for("admin_chatbot_kb"))
                outcome = "error"
            elif action == "edit":
                eid = request.form.get("entry_id")
                q = request.form.get("question", "").strip()
                a = request.form.get("answer", "").strip()
                cat = request.form.get("category", "").strip() or None
                if eid and q and a and chatbot_db.update_entry(eid, q, a, cat):
                    _audit("admin_chatbot_kb:edit", target_type="kb", target_id=eid, details=f"question={q[:120]}", outcome="success")
                    return redirect(url_for("admin_chatbot_kb"))
                outcome = "error"
            elif action == "delete":
                eid = request.form.get("entry_id")
                if eid and chatbot_db.delete_entry(eid):
                    _audit("admin_chatbot_kb:delete", target_type="kb", target_id=eid, outcome="success")
                    return redirect(url_for("admin_chatbot_kb"))
                outcome = "error"
            _audit(f"admin_chatbot_kb:{action or 'unknown'}", target_type="kb", target_id=request.form.get("entry_id"), outcome=outcome)
        entries = chatbot_db.get_all_entries()
        return render_template("admin_chatbot_kb.html", entries=entries)

    def admin_chatbot_feedback():
        if request.method == "POST":
            row_id = request.form.get("feedback_id")
            action = request.form.get("review_action")
            note = request.form.get("review_note", "")
            if row_id and action:
                ok = db.update_chat_feedback_review(
                    feedback_id=row_id,
                    review_action=action,
                    reviewed_by=session.get("user_id"),
                    review_note=note,
                )
                _audit(
                    action=f"admin_feedback_review:{action}",
                    target_type="chat_feedback",
                    target_id=row_id,
                    details=(note or "")[:200],
                    outcome="success" if ok else "error",
                )
        only_negative = (request.args.get("only") or "").strip().lower() == "negative"
        workflow = (request.args.get("workflow") or "").strip().lower()
        workflow_allowed = {"needs_intent", "needs_ui_flow"}
        rows = db.get_recent_chat_feedback(limit=300, only_negative=only_negative)
        if workflow in workflow_allowed:
            rows = [r for r in rows if (r["review_action"] or "").strip().lower() == workflow]
        return render_template(
            "admin_chatbot_feedback.html",
            entries=rows,
            only_negative=only_negative,
            workflow=workflow if workflow in workflow_allowed else "",
        )

    app.add_url_rule("/admin/users", endpoint="admin_users", view_func=auth.admin_required(admin_users), methods=["GET", "POST"])
    app.add_url_rule("/admin/courses", endpoint="admin_courses", view_func=auth.admin_required(admin_courses), methods=["GET", "POST"])
    app.add_url_rule("/admin/calendar", endpoint="admin_calendar", view_func=auth.admin_required(admin_calendar), methods=["GET"])
    app.add_url_rule("/admin/chatbot-kb", endpoint="admin_chatbot_kb", view_func=auth.admin_required(admin_chatbot_kb), methods=["GET", "POST"])
    app.add_url_rule("/admin/chatbot-feedback", endpoint="admin_chatbot_feedback", view_func=auth.admin_required(admin_chatbot_feedback), methods=["GET", "POST"])
