"""Admin form handling - processes POST actions and returns (redirect, error)."""
from core import db
from core import chatbot_db


def get_teachers_for_users_page():
    all_t = db.admin_get_all_teachers()
    uid = db.get_unassigned_teacher_id()
    return [t for t in all_t if uid and t['id'] != uid] if uid else all_t


def handle_admin_users_post(request):
    """Returns (redirect_name, template_context). redirect_name or ctx with error."""
    action = request.form.get("action")
    teachers = get_teachers_for_users_page()
    students = db.admin_get_all_students()
    deps = db.get_departments()
    majors = db.get_majors()
    ctx = {"teachers": teachers, "students": students, "departments": deps, "majors": majors, "error": None}

    if action == "add_teacher":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        department = request.form.get("department", "").strip() or None
        office_number = request.form.get("office_number", "").strip() or None
        if not email or not password or not full_name:
            ctx["error"] = "Email, password and full name are required"
            return (None, ctx)
        if not department:
            ctx["error"] = "Department is required"
            return (None, ctx)
        if db.admin_create_teacher(email, password, full_name, department, office_number) is None:
            ctx["error"] = "Email already exists"
            return (None, ctx)
        chatbot_db.sync_teacher_upsert(full_name, email, department, office_number)
    elif action == "add_student":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        major = request.form.get("major", "").strip() or None
        year_val = request.form.get("year", "").strip()
        year = int(year_val) if year_val.isdigit() else None
        if not email or not password or not full_name or not student_id:
            ctx["error"] = "Email, password, full name and student ID are required"
            return (None, ctx)
        if not major:
            ctx["error"] = "Major is required"
            return (None, ctx)
        if year is None:
            ctx["error"] = "Year is required"
            return (None, ctx)
        if db.admin_create_student(email, password, full_name, student_id, major, year) is None:
            ctx["error"] = "Email or student ID already exists"
            return (None, ctx)
    elif action == "edit_teacher":
        tid = request.form.get("teacher_id")
        department = request.form.get("department", "").strip() or None
        office_number = request.form.get("office_number", "").strip() or None
        if tid and department:
            db.admin_update_teacher(tid, department, office_number)
            info = db.get_teacher_info_for_sync(tid)
            if info:
                chatbot_db.sync_teacher_upsert(info["full_name"], info["email"], department, office_number)
    elif action == "edit_student":
        sid = request.form.get("student_id")
        major = request.form.get("major", "").strip() or None
        if sid and major:
            db.admin_update_student(sid, major)
    elif action == "delete_teacher":
        tid = request.form.get("teacher_id")
        if tid:
            info = db.get_teacher_info_for_sync(tid)
            db.admin_delete_teacher(tid)
            if info:
                chatbot_db.sync_teacher_remove(info["email"])
    elif action == "delete_student":
        sid = request.form.get("student_id")
        if sid:
            db.admin_delete_student(sid)
    return ("admin_users", None)


def handle_admin_courses_post(request):
    """Returns (redirect_name, error_message)."""
    action = request.form.get("action")
    if action == "add_course":
        course_code = request.form.get("course_code", "").strip()
        course_name = request.form.get("course_name", "").strip()
        section_number = request.form.get("section_number", "1").strip() or "1"
        teacher_id = request.form.get("teacher_id")
        semester = request.form.get("semester", "").strip() or None
        if not course_code or not course_name or not teacher_id:
            return (None, "Course code, name and teacher are required")
        if not semester:
            return (None, "Semester is required")
        if db.admin_create_course(course_code, course_name, section_number, teacher_id, semester) is None:
            return (None, "Course with same code and section already exists")
    elif action == "enroll":
        course_id = request.form.get("course_id")
        student_id = request.form.get("student_id")
        if course_id and student_id:
            db.admin_enroll_student(course_id, student_id)
    elif action == "unenroll":
        course_id = request.form.get("course_id")
        student_id = request.form.get("student_id")
        if course_id and student_id:
            db.admin_unenroll_student(course_id, student_id)
    elif action == "unenroll_by_id":
        course_id = request.form.get("course_id")
        student_id_str = request.form.get("student_id_str", "").strip()
        if course_id and student_id_str:
            ok, err = db.admin_unenroll_by_student_id(course_id, student_id_str)
            if not ok and err:
                return (None, err)
    elif action == "enroll_by_id":
        course_id = request.form.get("course_id")
        student_id_str = request.form.get("student_id_str", "").strip()
        if course_id and student_id_str:
            ok, err = db.admin_enroll_by_student_id(course_id, student_id_str)
            if not ok and err:
                return (None, err)
    elif action == "delete_course":
        cid = request.form.get("course_id")
        if cid:
            db.admin_delete_course(cid)
    elif action == "edit_course":
        cid = request.form.get("course_id")
        teacher_id = request.form.get("teacher_id")
        if cid is not None:
            db.admin_update_course_teacher(cid, teacher_id or None)
    return ("admin_courses", None)
