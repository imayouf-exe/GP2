"""Cheating detection: camera capture and YOLO-based phone/peek detection."""
import os
import cv2
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from core.db import save_alert_to_db


@dataclass
class Alert:
    time: str
    label: str
    confidence: float
    is_danger: bool = False


class CheatingDetector:
    def __init__(self, app=None):
        self.app = app
        self.is_running = False
        self.camera = None
        self.video_writer = None
        self.alerts = []
        self.frame = None
        self.lock = threading.Lock()
        self.phone_model = None
        self.peek_model = None
        self.models_loaded = False
        self.frame_count = 0
        self.current_phone_boxes = []
        self.current_peek_boxes = []
        self.output_path = None
        self.current_exam_id = None
        self.start_time = None
        self.output_fps = 15.0
        self.written_frames = 0

    def init_app(self, app):
        self.app = app

    def load_models(self):
        if self.models_loaded:
            return True
        try:
            from ultralytics import YOLO
            model_dir = os.path.join(os.path.dirname(__file__), "Cheating Detection")
            phone_path = os.path.join(model_dir, "phone_model.pt")
            peek_path = os.path.join(model_dir, "peek_model.pt")
            if os.path.exists(phone_path):
                self.phone_model = YOLO(phone_path)
            if os.path.exists(peek_path):
                self.peek_model = YOLO(peek_path)
            self.models_loaded = True
            print("YOLO models loaded successfully!")
            return True
        except Exception as e:
            print(f"Could not load YOLO models: {e}")
            print("Running in demo mode (camera only, no detection)")
            return False

    def start(self, exam_id):
        if self.is_running:
            return
        self.load_models()
        self.camera = cv2.VideoCapture(0)
        self.current_exam_id = exam_id
        self.start_time = time.time()
        if not self.camera.isOpened():
            print("Error: Could not open camera")
            return
        width = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.output_fps = 15.0
        self.written_frames = 0
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        recordings_dir = os.path.join(os.path.dirname(__file__), "recordings")
        os.makedirs(recordings_dir, exist_ok=True)
        self.output_path = os.path.join(recordings_dir, f"exam_{exam_id}_{timestamp}.mp4")
        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        self.video_writer = cv2.VideoWriter(self.output_path, fourcc, self.output_fps, (width, height))
        if not self.video_writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(self.output_path, fourcc, self.output_fps, (width, height))
        self.is_running = True
        self.alerts = []
        self.frame_count = 0
        print(f"Started recording exam {exam_id} to {self.output_path}")
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def stop(self):
        self.is_running = False
        time.sleep(0.5)
        if self.camera:
            self.camera.release()
            self.camera = None
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
            print(f"Recording saved to {self.output_path}")
        return self.output_path

    def _capture_loop(self):
        target_fps = 15
        frame_interval = 1.0 / target_fps
        last_frame_time = time.time()
        while self.is_running and self.camera and self.camera.isOpened():
            success, frame = self.camera.read()
            if not success:
                continue
            current_time = time.time()
            elapsed = current_time - last_frame_time
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)
            last_frame_time = time.time()
            self.frame_count += 1
            if self.models_loaded and self.frame_count % 3 == 0:
                if self.phone_model:
                    try:
                        phone_results = self.phone_model.predict(frame, conf=0.61, imgsz=640, iou=0.45, verbose=False)
                        self.current_phone_boxes = phone_results[0].boxes
                    except Exception:
                        pass
                if self.peek_model:
                    try:
                        peek_results = self.peek_model.predict(frame, conf=0.42, imgsz=640, iou=0.45, verbose=False)
                        self.current_peek_boxes = peek_results[0].boxes
                    except Exception:
                        pass
            if self.phone_model:
                for box in self.current_phone_boxes:
                    class_id = int(box.cls[0])
                    class_name = self.phone_model.names[class_id]
                    if class_name.lower() == "normal":
                        continue
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    confidence = float(box.conf[0])
                    label = f"{class_name.title()} ({confidence:.2f})"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    if self.frame_count % 30 == 0:
                        self._add_alert(class_name, confidence, is_danger=True)
            if self.peek_model:
                for box in self.current_peek_boxes:
                    class_id = int(box.cls[0])
                    class_name = self.peek_model.names[class_id]
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    confidence = float(box.conf[0])
                    label = f"{class_name.title()} ({confidence:.2f})"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
                    if self.frame_count % 30 == 0:
                        self._add_alert(class_name, confidence, is_danger=False)
            if self.video_writer and self.start_time:
                # Keep output duration aligned with real wall-clock time.
                # If processing is slower than output FPS, duplicate frames so playback stays at normal speed.
                elapsed = max(0.0, time.time() - self.start_time)
                expected_frames = max(1, int(elapsed * self.output_fps))
                while self.written_frames < expected_frames:
                    self.video_writer.write(frame)
                    self.written_frames += 1
            with self.lock:
                self.frame = frame

    def _add_alert(self, label, confidence, is_danger):
        timestamp = datetime.now().strftime("%H:%M:%S")
        alert = Alert(time=timestamp, label=label, confidence=confidence, is_danger=is_danger)
        self.alerts.insert(0, alert)
        if len(self.alerts) > 50:
            self.alerts = self.alerts[:50]
        if self.current_exam_id and self.start_time and self.app:
            elapsed = time.time() - self.start_time
            try:
                with self.app.app_context():
                    save_alert_to_db(self.current_exam_id, label, elapsed, confidence)
            except Exception:
                pass

    def get_frame(self):
        with self.lock:
            if self.frame is None:
                return None
            ret, jpeg = cv2.imencode('.jpg', self.frame)
            return jpeg.tobytes() if ret else None

    def get_alerts(self):
        return self.alerts
