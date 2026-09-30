This is a classroom management app 

it will help students/teachers organize classrooms more efficiently

our app has main 3 parts

*Part I: The Camera*

The camera will detect classroom availability, Cheating detection during exams, and Taking attendance (not sure if we are going to do it)
Cheating detection: When the exam starts The camera will start Detecting for any suspicious activity utilizing YOLO, cv2. After the exam ends our model will start Check for cheating if theres any, It will alert the teacher with the timestamp and a clip with a description of what's happening
Room availability: it will take a screenshot of the class room and scan to see if anyone is there or not 

*Part II: Roombooking and Calendar*

Teachers can book a classroom for future exams in advance to eliminate double booking
The calendar will be split into three calendars (1) Global for all the students and teachers, (2) For teachers they can add Project/assignment deadlines, classes and exam reminders for student in that section, (3) Last one is personal calendar


*Part III: Chatbot*

The chatbot will be using dedicated database to find answers for all the questions


The entirety of the application will be developed using python, Database will mostly use sqlite3
Our team OSs: Windows, macOS


*Accounts*

- Admin
    admin@exam.com
    admin123

- Teachers
    Amir@imam.com - IT
    123
    Ahmad@imam.com - IT
    123
    fahad@imam.com - CS
    123
    ail@imam.com - CS
    123
    Aamir@imam.com - IS
    123 (forgot the password..)

- Students
    ibrahim@mayouf.com - IT
    123
    kareem@imam.com - IT
    123
    Mubarak@imam.com - CS
    123
    Suliman@imam.com - CS
    123
    tareq@mayouf.com
    123

*To add new users*
Admin's dashborde > User management

 *Courses available*

 CS101 - S1 - Intro to programming


*Run the Chatbot API (for teammates)*

### 1) Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 2) Add Gemini API key

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3) Start the app

```bash
python app.py
```

Server runs on `http://127.0.0.1:5001`.

### 3.1) Run database migrations (Alembic)

```bash
alembic upgrade head
```

This project now includes Alembic migration scaffolding in `migrations/`.
For schema updates, create a new migration file:

```bash
alembic revision -m "describe schema change"
```

### 4) Use chatbot from UI (recommended)

1. Login as **student** or **teacher** (admin is blocked from chatbot).
2. Open `http://127.0.0.1:5000/chatbot`.
3. Send messages from the chat page.

### 5) Chatbot API endpoint

- URL: `POST /api/chatbot`
- Auth: requires logged-in session cookie
- Content-Type: `application/json`
- Body:

```json
{
  "message": "What are my upcoming exams?"
}
```

- Example response:

```json
{
  "reply": "Hi ... Here are your upcoming exams: ...",
  "meta": {
    "confidence": "high",
    "sources": ["calendar"]
  }
}
```# GP2
