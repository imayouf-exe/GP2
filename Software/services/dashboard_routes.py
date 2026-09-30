from datetime import datetime

from flask import render_template, redirect, url_for, session

from core import auth


def _get_time_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    return "Good evening"


def register_dashboard_routes(app):
    def dashboard():
        if session.get("role") == "teacher":
            return redirect(url_for("teacher_dashboard"))
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("student_dashboard"))

    def teacher_dashboard():
        return render_template("teacher_dashboard.html", greeting=_get_time_greeting())

    def student_dashboard():
        return render_template("student_dashboard.html", greeting=_get_time_greeting())

    def admin_dashboard():
        return render_template("admin_dashboard.html", greeting=_get_time_greeting())

    app.add_url_rule("/dashboard", endpoint="dashboard", view_func=auth.login_required(dashboard), methods=["GET"])
    app.add_url_rule("/teacher-dashboard", endpoint="teacher_dashboard", view_func=auth.teacher_required(teacher_dashboard), methods=["GET"])
    app.add_url_rule("/student-dashboard", endpoint="student_dashboard", view_func=auth.student_required(student_dashboard), methods=["GET"])
    app.add_url_rule("/admin", endpoint="admin_dashboard", view_func=auth.admin_required(admin_dashboard), methods=["GET"])
