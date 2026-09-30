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

# Create Users Table (students and teachers only)
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('student', 'teacher')),
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

# Create Courses Table (linked to teachers)
cursor.execute('''
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT UNIQUE NOT NULL,
    course_name TEXT NOT NULL,
    teacher_id INTEGER NOT NULL,
    semester TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
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

# Insert sample data
print("Creating sample data...")

# Create teacher user
cursor.execute('''
    INSERT INTO users (email, password, full_name, role) VALUES
    ('teacher@exam.com', ?, 'Dr. John Smith', 'teacher')
''', (hash_password('teacher123'),))
teacher_user_id = cursor.lastrowid

# Create teacher profile
cursor.execute('''
    INSERT INTO teachers (user_id, department, office_number)
    VALUES (?, 'Computer Science', 'Room 204')
''', (teacher_user_id,))
teacher_id = cursor.lastrowid

# Create student users
students_data = [
    ('alice@student.com', 'Alice Chen', 'STU001', 'Computer Science', 2),
    ('bob@student.com', 'Bob Smith', 'STU002', 'Computer Science', 2),
    ('carol@student.com', 'Carol Jones', 'STU003', 'Computer Science', 3),
    ('dave@student.com', 'Dave Wilson', 'STU004', 'Computer Science', 2),
    ('eve@student.com', 'Eve Brown', 'STU005', 'Computer Science', 3),
]

student_ids = []
for email, name, sid, major, year in students_data:
    cursor.execute('''
        INSERT INTO users (email, password, full_name, role) VALUES (?, ?, ?, 'student')
    ''', (email, hash_password('student123'), name))
    user_id = cursor.lastrowid
    
    cursor.execute('''
        INSERT INTO students (user_id, student_id, major, year) VALUES (?, ?, ?, ?)
    ''', (user_id, sid, major, year))
    student_ids.append(cursor.lastrowid)

# Create courses
cursor.execute('''
    INSERT INTO courses (course_code, course_name, teacher_id, semester) VALUES
    ('CS101', 'Introduction to Programming', ?, 'Spring 2025')
''', (teacher_id,))
cs101_id = cursor.lastrowid

cursor.execute('''
    INSERT INTO courses (course_code, course_name, teacher_id, semester) VALUES
    ('CS201', 'Data Structures', ?, 'Spring 2025')
''', (teacher_id,))
cs201_id = cursor.lastrowid

# Enroll students in courses
for student_id in student_ids:
    cursor.execute('''
        INSERT INTO course_enrollments (course_id, student_id) VALUES (?, ?)
    ''', (cs101_id, student_id))

# Enroll some students in CS201
for student_id in student_ids[:3]:
    cursor.execute('''
        INSERT INTO course_enrollments (course_id, student_id) VALUES (?, ?)
    ''', (cs201_id, student_id))

# Create an exam (trigger will auto-enroll students from the course)
cursor.execute('''
    INSERT INTO exam_sessions (course_id, exam_name, status) VALUES
    (?, 'Midterm Exam', 'scheduled')
''', (cs101_id,))

conn.commit()

# Verify the auto-enrollment worked
cursor.execute('''
    SELECT u.full_name FROM exam_enrollments ee
    JOIN students s ON ee.student_id = s.id
    JOIN users u ON s.user_id = u.id
    WHERE ee.exam_id = 1
''')
enrolled = cursor.fetchall()
print(f"\nAuto-enrolled {len(enrolled)} students in CS101 Midterm:")
for (name,) in enrolled:
    print(f"  - {name}")

conn.close()
print("\nDatabase created successfully!")

print("\n--- Login Credentials ---")
print("Teacher: teacher@exam.com / teacher123")
print("Students: alice@student.com, bob@student.com, etc. / student123")
