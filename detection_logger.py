import cv2
import os
import time
import json
import queue
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
import numpy as np
from hybrid_detector import Detection


def _atomic_imwrite(path: str, img) -> None:
    """Write an image atomically.

    cv2.imwrite writes in place, so a crash or service restart mid-write leaves a
    truncated or zero-byte file on disk. Those files still satisfy os.path.exists(),
    so they get served as 0 bytes and render as broken images forever. Writing to a
    temp file and renaming makes a partial file impossible to observe.
    """
    # cv2.imwrite selects the encoder from the file EXTENSION, so the temp
    # name must keep the real ".jpg" - a ".tmp" suffix fails every write.
    root, ext = os.path.splitext(path)
    tmp = "%s.__tmp__%s" % (root, ext)
    if not cv2.imwrite(tmp, img):
        try: os.remove(tmp)
        except OSError: pass
        raise IOError("imwrite failed for %s" % path)
    if os.path.getsize(tmp) == 0:
        os.remove(tmp)
        raise IOError("imwrite produced an empty file for %s" % path)
    os.replace(tmp, path)


class DetectionLogger:
    def __init__(self, log_dir: str = "detection_logs", cooldown_seconds: int = 5):
        self.log_dir = log_dir
        self.cooldown_seconds = cooldown_seconds
        self.last_detection_time = 0
        self.detection_logs = []
        self.max_logs = 100  # Keep only the last 100 log entries
        self._log_counter = 0

        # Create directories
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(os.path.join(self.log_dir, "thumbnails"), exist_ok=True)
        os.makedirs(os.path.join(self.log_dir, "images"), exist_ok=True)

        # Load existing logs
        self._load_logs()

        # Background I/O writer
        self._io_queue: queue.Queue = queue.Queue()
        self._io_thread = threading.Thread(target=self._io_worker, daemon=True)
        self._io_thread.start()
        
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
        if self.detection_logs:
            self._log_counter = max(e["id"] for e in self.detection_logs) + 1
        else:
            self._log_counter = 1

    def _io_worker(self):
        """Background thread that processes I/O work items"""
        while True:
            item = self._io_queue.get()
            try:
                kind = item[0]
                if kind == "thumbnail":
                    _, frame, timestamp_str = item
                    self._save_thumbnail(frame, timestamp_str)
                elif kind == "logs":
                    self._save_logs()
            except Exception as e:
                print(f"Background I/O error: {e}")
            finally:
                self._io_queue.task_done()
    
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
            _atomic_imwrite(thumb_filepath, thumbnail)
            
            # Save larger image for modal (max 800x600, maintaining aspect ratio)
            if aspect_ratio > 800/600:
                large_width = 800
                large_height = int(800 / aspect_ratio)
            else:
                large_height = 600
                large_width = int(600 * aspect_ratio)
            
            large_image = cv2.resize(frame, (large_width, large_height))
            large_filepath = os.path.join(self.log_dir, "images", filename)
            _atomic_imwrite(large_filepath, large_image)
            
            return filename
        except Exception as e:
            print(f"Error saving images: {e}")
            return ""
    
    def log_detections(self, frame: np.ndarray, detections: List[Detection], target_classes: List[str] = None) -> bool:
        """
        Log object detections with cooldown logic
        
        Args:
            frame: The current video frame
            detections: List of detected objects
            target_classes: List of class names to log (if None, uses default classes)
            
        Returns:
            bool: True if a new log entry was created
        """
        current_time = time.time()
        
        # Use default classes if none provided
        if target_classes is None:
            target_classes = ["person", "Orange Cone"]
        
        # Check if any target object was detected (substring match for flexibility)
        def _class_matches(det_class, targets):
            det_lower = det_class.lower()
            return any(t.lower() in det_lower or det_lower in t.lower() for t in targets)

        objects_detected = any(_class_matches(detection.class_name, target_classes) for detection in detections)

        if not objects_detected:
            return False
        
        # Check cooldown period
        if current_time - self.last_detection_time < self.cooldown_seconds:
            return False
        
        # Create log entry
        timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
        
        # Save thumbnail in background
        thumbnail_filename = f"detection_{timestamp_str}.jpg"
        self._io_queue.put(("thumbnail", frame.copy(), timestamp_str))
        
        # Count objects detected by type
        class_counts = {}
        for detection in detections:
            if _class_matches(detection.class_name, target_classes):
                class_counts[detection.class_name] = class_counts.get(detection.class_name, 0) + 1

        # Get highest confidence detection for additional info
        all_target_detections = [d for d in detections if _class_matches(d.class_name, target_classes)]
        max_confidence = max(d.confidence for d in all_target_detections) if all_target_detections else 0
        
        # Create appropriate alert message
        alerts = []
        for class_name, count in class_counts.items():
            # Capitalize class name and handle plurals
            display_name = class_name.title() 
            if count > 1:
                # Simple plural handling - add 's' unless it ends with 's'
                if not display_name.endswith('s'):
                    display_name += 's'
            alerts.append(f"{count} {display_name}")
        
        alert_message = f"Alert: {' & '.join(alerts)} Detected"
        
        # Create dynamic log entry with detected classes
        log_entry = {
            "id": self._log_counter,
            "timestamp": timestamp.isoformat(),
            "formatted_time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "message": alert_message,
            "max_confidence": round(max_confidence, 2),
            "thumbnail": thumbnail_filename,
            "camera_source": "unknown",  # Will be set by the caller
            "class_counts": class_counts  # Dynamic class counts
        }
        
        # Add to logs
        self.detection_logs.append(log_entry)
        self._log_counter += 1

        # Update last detection time
        self.last_detection_time = current_time

        # Save logs in background
        self._io_queue.put(("logs",))
        
        print(f"Detection logged: {log_entry['message']} at {log_entry['formatted_time']}")
        return True
    
    def get_recent_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get the most recent log entries that still have a usable thumbnail.

        Log entries and thumbnail files can drift apart: clear_logs() removes the
        files, and a crash mid-write used to leave zero-byte images behind. An
        entry whose image is gone renders as a broken tile forever, so filter
        them out here rather than shipping phantom rows to the UI.
        """
        if not self.detection_logs:
            return []
        thumb_dir = os.path.join(self.log_dir, "thumbnails")
        usable = []
        for entry in self.detection_logs:
            name = entry.get("thumbnail")
            if not name:
                continue
            path = os.path.join(thumb_dir, os.path.basename(name))
            try:
                if os.path.getsize(path) > 0:
                    usable.append(entry)
            except OSError:
                continue
        return usable[-limit:]
    
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