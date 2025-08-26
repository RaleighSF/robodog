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
        # YOLO detection
        self.yolo_net = None
        self.yolo_classes = []
        
        # Model selection - can switch between YOLOv4 and YOLOv8
        self.current_model = "yolov4"  # Options: "yolov4", "yolov8"
        
        # Target classes for factory patrol monitoring
        self.target_classes = {
            0: "person",           # Person detection for security
            49: "Orange Cone",     # Orange cone detection for factory safety
            # Additional classes that might capture cone-like shapes:
            # 39: "bottle",        # Cone-shaped objects (YOLOv4 fallback)
            # 58: "potted plant"   # Sometimes cone-shaped objects detected as plants
        }
        
        # Colors for different detection types
        self.colors = {
            'person': (0, 0, 255),        # Red - for security alert visibility
            'Orange Cone': (0, 165, 255), # Orange - for cone detection
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
                    
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Perform YOLO detection on frame using the selected model"""
        detections = []
        
        # Route to the appropriate detection method based on current model
        if self.current_model == "yolov4":
            # Use YOLOv4 (existing method)
            if self.yolo_net is not None:
                detections.extend(self._detect_yolo_filtered(frame))
        
        elif self.current_model == "yolov8":
            # Use YOLOv8
            if hasattr(self, 'yolov8_model'):
                detections.extend(self._detect_yolov8(frame))
            else:
                print("YOLOv8 model not loaded. Falling back to YOLOv4.")
                if self.yolo_net is not None:
                    detections.extend(self._detect_yolo_filtered(frame))
        
        elif self.current_model == "yolo-world":
            # Use YOLO-World
            if hasattr(self, 'yolo_world_model'):
                detections.extend(self._detect_yolo_world(frame))
            else:
                print("YOLO-World model not loaded. Falling back to YOLOv4.")
                if self.yolo_net is not None:
                    detections.extend(self._detect_yolo_filtered(frame))
        
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
    
    def switch_model(self, model_type: str) -> bool:
        """
        Switch between different YOLO models
        
        Args:
            model_type: "yolov4", "yolov8", or "yolo-world"
            
        Returns:
            bool: True if model was switched successfully
        """
        if model_type == "yolov4":
            # Current YOLOv4 model (already initialized)
            self.current_model = "yolov4"
            print(f"Switched to YOLOv4 model")
            return True
        
        elif model_type == "yolov8":
            try:
                # Try to import and initialize YOLOv8
                from ultralytics import YOLO
                self.yolov8_model = YOLO('yolov8s.pt')  # Auto-downloads on first use
                self.current_model = "yolov8"
                print(f"Switched to YOLOv8 model")
                return True
            except ImportError:
                print("ultralytics not available. Please install: pip install ultralytics")
                return False
            except Exception as e:
                print(f"Error loading YOLOv8: {e}")
                return False
                
        elif model_type == "yolo-world":
            try:
                # Try to import and initialize YOLO-World for open-vocabulary detection
                from ultralytics import YOLOWorld
                self.yolo_world_model = YOLOWorld('yolov8s-world.pt')
                # Set custom classes for orange cone detection
                self.yolo_world_model.set_classes(['person', 'orange cone', 'traffic cone', 'construction cone'])
                self.current_model = "yolo-world"
                print(f"Switched to YOLO-World model with custom cone detection")
                return True
            except ImportError:
                print("ultralytics not available or YOLO-World not supported")
                return False
            except Exception as e:
                print(f"Error loading YOLO-World: {e}")
                return False
        
        else:
            print(f"Unknown model type: {model_type}")
            return False
    
    def get_current_model(self) -> str:
        """Get the currently active model"""
        return self.current_model
    
    def _detect_yolov8(self, frame: np.ndarray) -> List[Detection]:
        """YOLOv8 detection method"""
        try:
            results = self.yolov8_model(frame, classes=list(self.target_classes.keys()), verbose=False)
            detections = []
            
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        confidence = float(box.conf[0])
                        class_id = int(box.cls[0])
                        
                        if confidence > self.confidence_threshold and class_id in self.target_classes:
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            # Convert to our Detection format (x, y, w, h)
                            w, h = x2 - x1, y2 - y1
                            
                            detection = Detection(
                                bbox=(x1, y1, w, h),
                                class_id=class_id,
                                confidence=confidence,
                                class_name=self.target_classes[class_id]
                            )
                            detections.append(detection)
            
            # Apply the same overlap filtering as YOLOv4
            return self._remove_overlapping_detections(detections)
            
        except Exception as e:
            print(f"YOLOv8 detection error: {e}")
            return []
    
    def _detect_yolo_world(self, frame: np.ndarray) -> List[Detection]:
        """YOLO-World detection method for open-vocabulary detection"""
        try:
            results = self.yolo_world_model(frame, verbose=False)
            detections = []
            
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        confidence = float(box.conf[0])
                        class_id = int(box.cls[0])
                        class_name = self.yolo_world_model.names[class_id]
                        
                        # Map detected classes to our target classes
                        mapped_class = None
                        if 'person' in class_name.lower():
                            mapped_class = 'person'
                        elif any(cone_word in class_name.lower() for cone_word in ['cone', 'orange']):
                            mapped_class = 'Orange Cone'
                        
                        if mapped_class and confidence > self.confidence_threshold:
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            # Convert to our Detection format (x, y, w, h)
                            w, h = x2 - x1, y2 - y1
                            
                            detection = Detection(
                                bbox=(x1, y1, w, h),
                                class_id=0 if mapped_class == 'person' else 49,
                                confidence=confidence,
                                class_name=mapped_class
                            )
                            detections.append(detection)
            
            # Apply the same overlap filtering
            return self._remove_overlapping_detections(detections)
            
        except Exception as e:
            print(f"YOLO-World detection error: {e}")
            return []