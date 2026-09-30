import cv2
from ultralytics import YOLO

# ==========================================
# 1. INITIALIZE MODELS
# ==========================================
# Load both custom AI models
phone_model = YOLO("phone_model.pt")
peek_model = YOLO("peek_model.pt")

# ==========================================
# 2. SETUP VIDEO INPUT & OUTPUT
# ==========================================
# Open the test video file (using 'r' for Windows raw paths)
video_path = 0
cap = cv2.VideoCapture(video_path)

# Get the original video's properties
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = int(cap.get(cv2.CAP_PROP_FPS)) 


# Webcam often returns 0 FPS - default to 30 for smooth playback
if fps == 0:
    fps = 30

# Setup VideoWriter to save the final presentation video
# Try H.264 codec first (best compatibility), fallback to mp4v if unavailable
fourcc = cv2.VideoWriter_fourcc(*'avc1')
out = cv2.VideoWriter("final_presentation.mp4", fourcc, fps, (width, height))



if not out.isOpened():
    print("H.264 codec unavailable, using MPEG-4 fallback...")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter("final_presentation.mp4", fourcc, fps, (width, height))

# ==========================================
# 3. PROCESSING VARIABLES
# ==========================================
frame_count = 0
current_phone_boxes = []
current_peek_boxes = []

print("Processing video... This window will close automatically when finished.")

# ==========================================
# 4. MAIN VIDEO LOOP
# ==========================================
while cap.isOpened():
    success, frame = cap.read()
    if not success:
        print("Processing complete! Check your folder for 'final_presentation.mp4' (H.264 codec).")
        break

    frame_count += 1
    
    # --- PERFORMANCE HACK: Frame Skip ---
    # Only run the heavy AI inference every 3rd frame
    if frame_count % 3 == 0:
        
        # Phone Detection: Strict confidence (61%), filtering out overlapping boxes (IoU)
        phone_results = phone_model.predict(frame, conf=0.61, imgsz=640, iou=0.45, verbose=False)
        current_phone_boxes = phone_results[0].boxes
        
        # Peek Detection:  More lenient confidence (42%) to catch subtle peeks, same IoU for consistency
        peek_results = peek_model.predict(frame, conf=0.42, imgsz=640, iou=0.45, verbose=False)
        current_peek_boxes = peek_results[0].boxes

    # --- DRAW PHONE BOXES (Red) ---
    for box in current_phone_boxes:
        class_id = int(box.cls[0])
        class_name = phone_model.names[class_id]
        
        # Hide the 'normal' label from the screen
        if class_name.lower() == "normal":
            continue
            
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        confidence = float(box.conf[0])
        label = f"{class_name.title()} ({confidence:.2f})"
        
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # --- DRAW PEEK BOXES (Orange) ---
    for box in current_peek_boxes:
        class_id = int(box.cls[0])
        class_name = peek_model.names[class_id]
        
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        confidence = float(box.conf[0])
        label = f"{class_name.title()} ({confidence:.2f})"
        
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
        cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

    # --- EXPORT AND DISPLAY ---
    
    # Save the processed frame with boxes drawn onto it to our new MP4 file
    out.write(frame)
    
    # Show it live (it will look slow-mo here, but the saved video will be smooth!)
    cv2.imshow("Processing Final Presentation Video...", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# ==========================================
# 5. CLEAN UP RESOURCES
# ==========================================
cap.release()
out.release() # CRITICAL: This physically saves the file to your hard drive
cv2.destroyAllWindows()