import cv2
import numpy as np
from typing import List, Tuple, Dict, Any

class Detection:
    def __init__(self, bbox: Tuple[int, int, int, int], class_id: int, 
                 confidence: float, class_name: str):
        self.bbox = bbox  # (x, y, w, h)
        self.class_id = class_id
        self.confidence = confidence
        self.class_name = class_name

class SimpleObjectDetector:
    def __init__(self):
        self.current_model = "Simple"
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2(detectShadows=True)
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        self.body_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_fullbody.xml')
        
        # Colors for different detection types
        self.colors = {
            'face': (0, 255, 0),      # Green
            'body': (255, 0, 0),      # Blue  
            'motion': (0, 165, 255),  # Orange
            'contour': (255, 255, 0)  # Cyan
        }
        
    def switch_model(self, model_name: str):
        """Switch between detection models"""
        self.current_model = model_name
        print(f"Switched to {model_name} detection")
        
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Perform object detection on frame"""
        detections = []
        
        # Face detection only
        detections.extend(self._detect_faces(frame))
        
        return detections
        
    def _detect_faces(self, frame: np.ndarray) -> List[Detection]:
        """Detect faces using Haar cascades"""
        detections = []
        
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            
            for (x, y, w, h) in faces:
                confidence = 0.8  # Haar cascades don't provide confidence scores
                detection = Detection((x, y, w, h), 1, confidence, "Face")
                detections.append(detection)
                
        except Exception as e:
            print(f"Face detection error: {e}")
            
        return detections
        
    def _detect_bodies(self, frame: np.ndarray) -> List[Detection]:
        """Detect full bodies using Haar cascades"""
        detections = []
        
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            bodies = self.body_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=3, minSize=(50, 50)
            )
            
            for (x, y, w, h) in bodies:
                confidence = 0.6  # Lower confidence for body detection
                detection = Detection((x, y, w, h), 2, confidence, "Person")
                detections.append(detection)
                
        except Exception as e:
            print(f"Body detection error: {e}")
            
        return detections
        
    def _detect_motion(self, frame: np.ndarray) -> List[Detection]:
        """Detect motion using background subtraction"""
        detections = []
        
        try:
            # Apply background subtraction
            fg_mask = self.background_subtractor.apply(frame)
            
            # Remove noise
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            
            # Find contours
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > 500:  # Minimum area for motion detection
                    x, y, w, h = cv2.boundingRect(contour)
                    
                    # Filter out very small or very large detections
                    if w > 20 and h > 20 and w < frame.shape[1]//2 and h < frame.shape[0]//2:
                        confidence = min(0.9, area / 5000)  # Scale confidence by area
                        detection = Detection((x, y, w, h), 3, confidence, "Motion")
                        detections.append(detection)
                        
        except Exception as e:
            print(f"Motion detection error: {e}")
            
        return detections
        
    def draw_detections(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """Draw bounding boxes and labels on frame"""
        result_frame = frame.copy()
        
        for detection in detections:
            x, y, w, h = detection.bbox
            
            # Get color based on class name
            color = self.colors.get(detection.class_name.lower(), (255, 255, 255))
            
            # Draw bounding box
            cv2.rectangle(result_frame, (x, y), (x + w, y + h), color, 2)
            
            # Draw label
            label = f"{detection.class_name}: {detection.confidence:.2f}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
            
            # Draw label background
            cv2.rectangle(result_frame, (x, y - label_size[1] - 10), 
                         (x + label_size[0], y), color, -1)
            
            # Draw label text
            cv2.putText(result_frame, label, (x, y - 5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                       
        return result_frame