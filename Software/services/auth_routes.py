from flask import render_template, request, session, redirect, url_for
import time

from core import db
from core import auth

_login_attempts = {}


def _rate_limited_login(key, limit=5, window_seconds=600):
    now = time.time()
    hits = [t for t in _login_attempts.get(key, []) if now - t < window_seconds]
    if len(hits) >= limit:
        _login_attempts[key] = hits
        return True
    hits.append(now)
    _login_attempts[key] = hits
    return False


def register_auth_routes(app):
    def login():
        error = None
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password")
            ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown")
            bucket_key = f"{ip}:{email}"
            if _rate_limited_login(bucket_key, limit=5, window_seconds=600):
                return render_template("login.html", error="Too many login attempts. Please wait 10 minutes and try again.")
            user = db.verify_login(email, password)
            if user:
                _login_attempts.pop(bucket_key, None)
                session["logged_in"] = True
                session["user_id"] = user["id"]
                session["user_name"] = user["full_name"]
                session["role"] = user["role"]
                if user["role"] == "teacher":
                    teacher = db.get_teacher_by_user_id(user["id"])
                    if teacher:
                        session["teacher_id"] = teacher["id"]
                    return redirect(url_for("teacher_dashboard"))
                if user["role"] == "admin":
                    return redirect(url_for("admin_dashboard"))
                student = db.get_student_by_user_id(user["id"])
                if student:
                    session["student_id"] = student["id"]
                return redirect(url_for("student_dashboard"))
            error = "Invalid email or password."
        return render_template("login.html", error=error)

    def logout():
        session.clear()
        return redirect(url_for("login"))

    def signout():
        return render_template("signout.html")

    app.add_url_rule("/", endpoint="root", view_func=login, methods=["GET", "POST"])
    app.add_url_rule("/login", endpoint="login", view_func=login, methods=["GET", "POST"])
    app.add_url_rule("/logout", endpoint="logout", view_func=logout, methods=["GET", "POST"])
    app.add_url_rule("/signout", endpoint="signout", view_func=auth.login_required(signout), methods=["GET"])
