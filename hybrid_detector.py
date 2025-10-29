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

class HybridDetector:
    def __init__(self):
        # Model selection - YOLO-E is the primary and only model
        self.current_model = "yoloe"

        # Default colors for detection types (can be extended dynamically)
        self.colors = {}

        # Initialize YOLO-E as the primary detector
        try:
            from yoloe_detector import get_yoloe_detector
            self.yoloe_detector = get_yoloe_detector()
            if self.yoloe_detector and self.yoloe_detector.initialized:
                print("✅ YOLO-E detector initialized as primary model")
            else:
                print("⚠️ YOLO-E not fully initialized")
        except Exception as e:
            print(f"⚠️ YOLO-E initialization failed: {e}")

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Perform detection on frame using YOLO-E"""
        detections = []

        # Use YOLO-E for all detection
        if self.current_model == "yoloe":
            detections.extend(self._detect_yoloe(frame))
        else:
            detections.extend(self._detect_yoloe(frame))

        return detections

    def draw_detections(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """Draw bounding boxes and labels on frame"""
        result_frame = frame.copy()

        for detection in detections:
            x, y, w, h = detection.bbox

            # Get color based on class name (default to white if not specified)
            color = self.colors.get(detection.class_name, (255, 255, 255))

            # Draw bounding box
            cv2.rectangle(result_frame, (x, y), (x + w, y + h), color, 2)

            # Draw label
            label = f"{detection.class_name}: {detection.confidence:.2f}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]

            # Draw label background
            cv2.rectangle(result_frame, (x, y - label_size[1] - 10),
                         (x + label_size[0], y), color, -1)

            # Draw label text with contrasting color
            text_color = (0, 0, 0) if sum(color) > 400 else (255, 255, 255)
            cv2.putText(result_frame, label, (x, y - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)

        return result_frame

    def switch_model(self, model_type: str) -> bool:
        """Switch model (YOLO-E only)"""
        if model_type == "yoloe":
            try:
                # Initialize YOLO-E detector
                from yoloe_detector import get_yoloe_detector
                self.yoloe_detector = get_yoloe_detector()
                self.current_model = "yoloe"
                print(f"Switched to YOLO-E model with AI prompting capabilities")
                return True
            except ImportError as e:
                print(f"YOLO-E not available: {e}")
                return False
            except Exception as e:
                print(f"Error loading YOLO-E: {e}")
                return False
        
        else:
            print(f"Unknown model type: {model_type}")
            return False
    
    def get_current_model(self) -> str:
        """Get the currently active model"""
        return self.current_model

    def _detect_yoloe(self, frame: np.ndarray) -> List[Detection]:
        """YOLO-E detection method with visual and text prompting support"""
        try:
            # Initialize YOLO-E detector if not already done
            if not hasattr(self, 'yoloe_detector'):
                from yoloe_detector import get_yoloe_detector
                self.yoloe_detector = get_yoloe_detector()
            
            if not self.yoloe_detector or not self.yoloe_detector.initialized:
                return []
            
            # Get detections from YOLO-E
            import time
            frame_timestamp = time.time()
            yoloe_detections = self.yoloe_detector.detect(frame, frame_timestamp)
            
            # Convert YOLO-E detection format to our Detection format
            # YOLO-E detector handles its own confidence filtering, so we trust its results
            detections = []
            for detection in yoloe_detections:
                # YOLO-E returns xyxy format, convert to xywh
                xyxy = detection.get('xyxy', [0, 0, 0, 0])
                x1, y1, x2, y2 = xyxy
                x, y, w, h = x1, y1, x2 - x1, y2 - y1
                
                class_name = detection.get('class_name', 'unknown')
                confidence = detection.get('confidence', 0.0)
                class_id = detection.get('class_id', 0)  # Use provided class_id or default to 0

                detection_obj = Detection(
                    bbox=(int(x), int(y), int(w), int(h)),
                    class_id=class_id,
                    confidence=confidence,
                    class_name=class_name
                )
                detections.append(detection_obj)
            
            return detections

        except Exception as e:
            print(f"❌ YOLO-E detection error: {e}")
            return []
