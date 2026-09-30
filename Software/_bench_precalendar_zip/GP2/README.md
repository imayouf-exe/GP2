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


The entirety of the application will be developed using python, Database will mostly use Postgers and DBeaver 
Our team OSs: Windows, macOS
