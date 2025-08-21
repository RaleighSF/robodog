import cv2
import numpy as np
from typing import List, Tuple, Dict, Any
import urllib.request
import os

class Detection:
    def __init__(self, bbox: Tuple[int, int, int, int], class_id: int, 
                 confidence: float, class_name: str):
        self.bbox = bbox  # (x, y, w, h)
        self.class_id = class_id
        self.confidence = confidence
        self.class_name = class_name

class HybridDetector:
    def __init__(self):
        self.current_model = "Hybrid"
        
        # Face detection
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # YOLO detection
        self.yolo_net = None
        self.yolo_classes = []
        
        # Target classes: person (0) in COCO dataset for factory patrol monitoring
        self.target_classes = {
            0: "person"
        }
        
        # Colors for different detection types
        self.colors = {
            'face': (0, 255, 0),        # Green
            'person': (0, 0, 255)       # Red - for security alert visibility
        }
        
        self.confidence_threshold = 0.7  # Higher confidence to reduce false positives
        self.nms_threshold = 0.6         # Higher NMS to better suppress overlapping boxes
        
        self._setup_yolo()
        
    def _setup_yolo(self):
        """Set up YOLO model"""
        try:
            # Download YOLO files if they don't exist
            self._download_yolo_files()
            
            weights_path = "yolov4.weights"
            config_path = "yolov4.cfg"
            classes_path = "coco.names"
            
            if os.path.exists(weights_path) and os.path.exists(config_path):
                print("Loading YOLO model...")
                self.yolo_net = cv2.dnn.readNetFromDarknet(config_path, weights_path)
                
                # Load class names
                with open(classes_path, 'r') as f:
                    self.yolo_classes = [line.strip() for line in f.readlines()]
                
                print(f"YOLO loaded successfully with {len(self.yolo_classes)} classes")
                print(f"Target classes: {list(self.target_classes.values())}")
            else:
                print("YOLO weights file not found. Please download yolov4.weights")
                print("URL: https://github.com/AlexeyAB/darknet/releases/download/darknet_yolo_v3_optimal/yolov4.weights")
                
        except Exception as e:
            print(f"Error setting up YOLO: {e}")
            
    def _download_yolo_files(self):
        """Download YOLO configuration and class files"""
        files_to_download = [
            ("https://raw.githubusercontent.com/AlexeyAB/darknet/master/cfg/yolov4.cfg", "yolov4.cfg"),
            ("https://raw.githubusercontent.com/AlexeyAB/darknet/master/data/coco.names", "coco.names")
        ]
        
        for url, filename in files_to_download:
            if not os.path.exists(filename):
                try:
                    print(f"Downloading {filename}...")
                    urllib.request.urlretrieve(url, filename)
                    print(f"Downloaded {filename}")
                except Exception as e:
                    print(f"Failed to download {filename}: {e}")
                    
    def switch_model(self, model_name: str):
        """Switch between detection models"""
        self.current_model = model_name
        print(f"Switched to {model_name} detection")
        
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Perform YOLO detection on frame"""
        detections = []
        
        # YOLO detection for person detection only
        if self.yolo_net is not None:
            detections.extend(self._detect_yolo_filtered(frame))
        
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
                confidence = 0.8
                detection = Detection((x, y, w, h), 0, confidence, "face")
                detections.append(detection)
                
        except Exception as e:
            print(f"Face detection error: {e}")
            
        return detections
        
    def _detect_yolo_filtered(self, frame: np.ndarray) -> List[Detection]:
        """YOLO detection filtered for person detection only"""
        try:
            height, width = frame.shape[:2]
            
            # Create blob from image
            blob = cv2.dnn.blobFromImage(frame, 1/255.0, (416, 416), swapRB=True, crop=False)
            self.yolo_net.setInput(blob)
            
            # Get output layer names
            layer_names = self.yolo_net.getLayerNames()
            unconnected = self.yolo_net.getUnconnectedOutLayers()
            
            # Handle different OpenCV versions
            if isinstance(unconnected[0], (list, tuple, np.ndarray)):
                output_layers = [layer_names[i[0] - 1] for i in unconnected]
            else:
                output_layers = [layer_names[i - 1] for i in unconnected]
            
            # Run inference
            outputs = self.yolo_net.forward(output_layers)
            
            # Process outputs
            boxes = []
            confidences = []
            class_ids = []
            
            for output in outputs:
                for detection in output:
                    scores = detection[5:]
                    class_id = np.argmax(scores)
                    confidence = scores[class_id]
                    
                    # Only process target classes (person)
                    if confidence > self.confidence_threshold and class_id in self.target_classes:
                        # Convert to pixel coordinates
                        center_x = int(detection[0] * width)
                        center_y = int(detection[1] * height)
                        w = int(detection[2] * width)
                        h = int(detection[3] * height)
                        
                        # Calculate top-left corner
                        x = int(center_x - w / 2)
                        y = int(center_y - h / 2)
                        
                        boxes.append([x, y, w, h])
                        confidences.append(float(confidence))
                        class_ids.append(class_id)
            
            # Apply NMS
            indices = cv2.dnn.NMSBoxes(boxes, confidences, self.confidence_threshold, self.nms_threshold)
            
            detections = []
            if len(indices) > 0:
                for i in indices.flatten():
                    x, y, w, h = boxes[i]
                    class_name = self.target_classes[class_ids[i]]
                    detections.append(Detection((x, y, w, h), class_ids[i], confidences[i], class_name))
            
            # Additional post-processing to remove remaining overlaps
            detections = self._remove_overlapping_detections(detections)
                    
            return detections
            
        except Exception as e:
            print(f"YOLO detection error: {e}")
            return []
    
    def _remove_overlapping_detections(self, detections: List[Detection]) -> List[Detection]:
        """Remove overlapping detections, keeping only the highest confidence ones"""
        if len(detections) <= 1:
            return detections
        
        # Sort detections by confidence (highest first)
        detections.sort(key=lambda d: d.confidence, reverse=True)
        
        filtered_detections = []
        for detection in detections:
            # Check if this detection overlaps significantly with any already accepted detection
            overlaps_significantly = False
            for accepted_detection in filtered_detections:
                if self._calculate_overlap(detection, accepted_detection) > 0.3:  # 30% overlap threshold
                    overlaps_significantly = True
                    break
            
            # Only keep this detection if it doesn't overlap significantly with accepted ones
            if not overlaps_significantly:
                filtered_detections.append(detection)
        
        return filtered_detections
    
    def _calculate_overlap(self, det1: Detection, det2: Detection) -> float:
        """Calculate intersection over union (IoU) between two detections"""
        x1, y1, w1, h1 = det1.bbox
        x2, y2, w2, h2 = det2.bbox
        
        # Calculate intersection
        xi1 = max(x1, x2)
        yi1 = max(y1, y2)
        xi2 = min(x1 + w1, x2 + w2)
        yi2 = min(y1 + h1, y2 + h2)
        
        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0
        
        intersection = (xi2 - xi1) * (yi2 - yi1)
        
        # Calculate union
        area1 = w1 * h1
        area2 = w2 * h2
        union = area1 + area2 - intersection
        
        # Return IoU
        return intersection / union if union > 0 else 0.0
            
    def draw_detections(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """Draw bounding boxes and labels on frame"""
        result_frame = frame.copy()
        
        for detection in detections:
            x, y, w, h = detection.bbox
            
            # Get color based on class name
            color = self.colors.get(detection.class_name, (255, 255, 255))
            
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