import cv2
import os
import time
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
import numpy as np
from hybrid_detector import Detection

class DetectionLogger:
    def __init__(self, log_dir: str = "detection_logs", cooldown_seconds: int = 5):
        self.log_dir = log_dir
        self.cooldown_seconds = cooldown_seconds
        self.last_detection_time = 0
        self.detection_logs = []
        self.max_logs = 100  # Keep only the last 100 log entries
        
        # Create directories
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(os.path.join(self.log_dir, "thumbnails"), exist_ok=True)
        os.makedirs(os.path.join(self.log_dir, "images"), exist_ok=True)
        
        # Load existing logs
        self._load_logs()
        
    def _load_logs(self):
        """Load existing logs from file"""
        log_file = os.path.join(self.log_dir, "detection_log.json")
        try:
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    self.detection_logs = json.load(f)
        except Exception as e:
            print(f"Error loading logs: {e}")
            self.detection_logs = []
    
    def _save_logs(self):
        """Save logs to file"""
        log_file = os.path.join(self.log_dir, "detection_log.json")
        try:
            # Keep only the most recent logs
            if len(self.detection_logs) > self.max_logs:
                self.detection_logs = self.detection_logs[-self.max_logs:]
            
            with open(log_file, 'w') as f:
                json.dump(self.detection_logs, f, indent=2)
        except Exception as e:
            print(f"Error saving logs: {e}")
    
    def _save_thumbnail(self, frame: np.ndarray, timestamp_str: str) -> str:
        """Save both thumbnail and larger image, return filename"""
        try:
            height, width = frame.shape[:2]
            filename = f"detection_{timestamp_str}.jpg"
            
            # Save small thumbnail (320x240 max, maintaining aspect ratio)
            aspect_ratio = width / height
            if aspect_ratio > 320/240:
                thumb_width = 320
                thumb_height = int(320 / aspect_ratio)
            else:
                thumb_height = 240
                thumb_width = int(240 * aspect_ratio)
            
            thumbnail = cv2.resize(frame, (thumb_width, thumb_height))
            thumb_filepath = os.path.join(self.log_dir, "thumbnails", filename)
            cv2.imwrite(thumb_filepath, thumbnail)
            
            # Save larger image for modal (max 800x600, maintaining aspect ratio)
            if aspect_ratio > 800/600:
                large_width = 800
                large_height = int(800 / aspect_ratio)
            else:
                large_height = 600
                large_width = int(600 * aspect_ratio)
            
            large_image = cv2.resize(frame, (large_width, large_height))
            large_filepath = os.path.join(self.log_dir, "images", filename)
            cv2.imwrite(large_filepath, large_image)
            
            return filename
        except Exception as e:
            print(f"Error saving images: {e}")
            return ""
    
    def log_detections(self, frame: np.ndarray, detections: List[Detection]) -> bool:
        """
        Log person detections with cooldown logic
        
        Args:
            frame: The current video frame
            detections: List of detected objects
            
        Returns:
            bool: True if a new log entry was created
        """
        current_time = time.time()
        
        # Check if any person was detected
        person_detected = any(detection.class_name == "person" for detection in detections)
        
        if not person_detected:
            return False
        
        # Check cooldown period
        if current_time - self.last_detection_time < self.cooldown_seconds:
            return False
        
        # Create log entry
        timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
        
        # Save thumbnail
        thumbnail_filename = self._save_thumbnail(frame, timestamp_str)
        
        # Count persons detected
        person_count = sum(1 for detection in detections if detection.class_name == "person")
        
        # Get highest confidence person detection for additional info
        person_detections = [d for d in detections if d.class_name == "person"]
        max_confidence = max(d.confidence for d in person_detections) if person_detections else 0
        
        log_entry = {
            "id": len(self.detection_logs) + 1,
            "timestamp": timestamp.isoformat(),
            "formatted_time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "message": "Alert: Person Detected",
            "person_count": person_count,
            "max_confidence": round(max_confidence, 2),
            "thumbnail": thumbnail_filename,
            "camera_source": "unknown"  # Will be set by the caller
        }
        
        # Add to logs
        self.detection_logs.append(log_entry)
        
        # Update last detection time
        self.last_detection_time = current_time
        
        # Save logs
        self._save_logs()
        
        print(f"Detection logged: {log_entry['message']} at {log_entry['formatted_time']}")
        return True
    
    def get_recent_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get the most recent log entries"""
        return self.detection_logs[-limit:] if self.detection_logs else []
    
    def clear_logs(self):
        """Clear all logs, thumbnails, and images"""
        try:
            # Clear log file
            self.detection_logs = []
            self._save_logs()
            
            # Remove thumbnail files
            thumbnail_dir = os.path.join(self.log_dir, "thumbnails")
            if os.path.exists(thumbnail_dir):
                for filename in os.listdir(thumbnail_dir):
                    if filename.endswith('.jpg'):
                        os.remove(os.path.join(thumbnail_dir, filename))
            
            # Remove larger image files
            images_dir = os.path.join(self.log_dir, "images")
            if os.path.exists(images_dir):
                for filename in os.listdir(images_dir):
                    if filename.endswith('.jpg'):
                        os.remove(os.path.join(images_dir, filename))
            
            print("Detection logs cleared")
        except Exception as e:
            print(f"Error clearing logs: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get logging statistics"""
        total_logs = len(self.detection_logs)
        
        if total_logs == 0:
            return {
                "total_detections": 0,
                "last_detection": None,
                "cooldown_seconds": self.cooldown_seconds
            }
        
        return {
            "total_detections": total_logs,
            "last_detection": self.detection_logs[-1]["formatted_time"] if self.detection_logs else None,
            "cooldown_seconds": self.cooldown_seconds
        }