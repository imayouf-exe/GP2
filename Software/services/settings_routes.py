from flask import render_template, request, redirect, url_for, session

from core import auth
from core import db


def register_settings_routes(app):
    def settings():
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("login"))

        notice = None
        notice_type = "success"

        if request.method == "POST":
            action = (request.form.get("action") or "").strip().lower()
            if action == "profile":
                ok, err = db.update_user_profile_basics(
                    user_id,
                    request.form.get("full_name", ""),
                    request.form.get("email", ""),
                    request.form.get("display_name", ""),
                    request.form.get("profile_photo_url", ""),
                )
                if ok:
                    session["user_name"] = (request.form.get("full_name") or "").strip() or session.get("user_name")
                    notice = "Profile basics updated."
                else:
                    notice = err or "Could not update profile basics."
                    notice_type = "error"
            elif action == "password":
                new_password = request.form.get("new_password", "")
                confirm_password = request.form.get("confirm_password", "")
                if new_password != confirm_password:
                    notice = "New password and confirm password do not match."
                    notice_type = "error"
                else:
                    ok, err = db.update_user_password(
                        user_id,
                        request.form.get("current_password", ""),
                        new_password,
                    )
                    if ok:
                        notice = "Password updated successfully."
                    else:
                        notice = err or "Could not update password."
                        notice_type = "error"
            elif action == "calendar":
                ok, err = db.update_user_calendar_defaults(
                    user_id,
                    request.form.get("calendar_default_view", "month"),
                    request.form.get("calendar_time_format", "12h"),
                )
                if ok:
                    notice = "Calendar defaults updated."
                else:
                    notice = err or "Could not update calendar defaults."
                    notice_type = "error"
            elif action == "ui":
                reduced_motion = request.form.get("ui_reduced_motion") in ("1", "on", "true", "yes")
                ok, err = db.update_user_ui_preferences(
                    user_id,
                    request.form.get("ui_theme", "dark"),
                    "dm",
                    reduced_motion,
                )
                if ok:
                    notice = "UI preferences updated."
                else:
                    notice = err or "Could not update UI preferences."
                    notice_type = "error"
            else:
                notice = "Unknown settings action."
                notice_type = "error"

        user = db.get_user_by_id(user_id)
        prefs = db.get_user_preferences(user_id)
        if not user:
            return redirect(url_for("login"))
        return render_template("settings.html", user=dict(user), prefs=prefs, notice=notice, notice_type=notice_type)

    def account():
        return redirect(url_for("settings") + "#profile")

    app.add_url_rule("/settings", endpoint="settings", view_func=auth.login_required(settings), methods=["GET", "POST"])
    app.add_url_rule("/account", endpoint="account", view_func=auth.login_required(account), methods=["GET"])
