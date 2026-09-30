import sqlite3
import hashlib

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

conn = sqlite3.connect('classroom_management.db')
cursor = conn.cursor()

# Drop existing tables to recreate with new structure
cursor.execute('DROP TABLE IF EXISTS exam_enrollments')
cursor.execute('DROP TABLE IF EXISTS cheating_alerts')
cursor.execute('DROP TABLE IF EXISTS exam_sessions')
cursor.execute('DROP TABLE IF EXISTS course_enrollments')
cursor.execute('DROP TABLE IF EXISTS courses')
cursor.execute('DROP TABLE IF EXISTS students')
cursor.execute('DROP TABLE IF EXISTS teachers')
cursor.execute('DROP TABLE IF EXISTS users')
cursor.execute('DROP TABLE IF EXISTS departments')
cursor.execute('DROP TABLE IF EXISTS majors')

# Create Departments lookup table
cursor.execute('''
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
)
''')

# Create Majors lookup table
cursor.execute('''
CREATE TABLE IF NOT EXISTS majors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
)
''')

# Create Users Table (students and teachers only)
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('student', 'teacher', 'admin')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Create Teachers Table
cursor.execute('''
CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL,
    department TEXT,
    office_number TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
)
''')

# Create Students Table
cursor.execute('''
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL,
    student_id TEXT UNIQUE NOT NULL,
    major TEXT,
    year INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
)
''')

# Create Courses Table (linked to teachers, with section support)
# teacher_id always references a valid teacher; use placeholder "Unassigned" for no teacher
cursor.execute('''
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT NOT NULL,
    course_name TEXT NOT NULL,
    section_number INTEGER NOT NULL DEFAULT 1,
    teacher_id INTEGER NOT NULL,
    semester TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE RESTRICT,
    UNIQUE(course_code, section_number)
)
''')

# Create Course Enrollments Table (links students to courses)
cursor.execute('''
CREATE TABLE IF NOT EXISTS course_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    UNIQUE(course_id, student_id)
)
''')

# Create Exam Sessions Table (linked to courses)
cursor.execute('''
CREATE TABLE IF NOT EXISTS exam_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    exam_name TEXT NOT NULL,
    video_filepath TEXT,
    date_recorded DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled', 'active', 'completed')),
    expires_at DATETIME,
    scheduled_start TEXT,
    scheduled_end TEXT,
    location TEXT,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
)
''')

# Create Exam Enrollments Table (auto-populated from course enrollments)
cursor.execute('''
CREATE TABLE IF NOT EXISTS exam_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    FOREIGN KEY (exam_id) REFERENCES exam_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    UNIQUE(exam_id, student_id)
)
''')

# Create the Cheating Alerts Table
cursor.execute('''
CREATE TABLE IF NOT EXISTS cheating_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL,
    alert_type TEXT NOT NULL,
    timestamp_seconds REAL NOT NULL,
    confidence REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (exam_id) REFERENCES exam_sessions(id) ON DELETE CASCADE
)
''')

# Create trigger to auto-populate exam_enrollments when an exam is created
cursor.execute('''
CREATE TRIGGER IF NOT EXISTS auto_enroll_students
AFTER INSERT ON exam_sessions
BEGIN
    INSERT INTO exam_enrollments (exam_id, student_id)
    SELECT NEW.id, ce.student_id
    FROM course_enrollments ce
    WHERE ce.course_id = NEW.course_id;
END
''')

conn.commit()

# Insert departments (CS, IT, IS)
cursor.execute("INSERT INTO departments (name) VALUES ('CS')")
cursor.execute("INSERT INTO departments (name) VALUES ('IT')")
cursor.execute("INSERT INTO departments (name) VALUES ('IS')")

# Insert majors (CS, IT, IS)
cursor.execute("INSERT INTO majors (name) VALUES ('CS')")
cursor.execute("INSERT INTO majors (name) VALUES ('IT')")
cursor.execute("INSERT INTO majors (name) VALUES ('IS')")

# Insert required system data only
print("Creating database...")

# Placeholder teacher "Unassigned" (required for courses when teacher is deleted)
cursor.execute('''
    INSERT INTO users (email, password, full_name, role) VALUES
    ('__unassigned__@system.local', ?, '__Unassigned__', 'teacher')
''', (hash_password('__system__'),))
cursor.execute('INSERT INTO teachers (user_id, department) VALUES (?, ?)', (cursor.lastrowid, 'CS'))

# Admin user only – add teachers, students, courses via admin dashboard
cursor.execute('''
    INSERT INTO users (email, password, full_name, role) VALUES
    ('admin@exam.com', ?, 'Admin', 'admin')
''', (hash_password('admin123'),))

conn.commit()
conn.close()
print("Database created successfully!")

print("\n--- Login Credentials ---")
print("Admin: admin@exam.com / admin123")
