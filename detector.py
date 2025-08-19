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

class ObjectDetector:
    def __init__(self):
        self.current_model = "YOLO"
        self.yolo_net = None
        self.yolo_classes = []
        self.yolo_colors = []
        self.resnet_net = None
        self.confidence_threshold = 0.5
        self.nms_threshold = 0.4
        
        self._load_yolo()
        
    def _load_yolo(self):
        """Load YOLO model and classes"""
        try:
            # Download YOLO files if they don't exist
            self._download_yolo_files()
            
            # Load YOLO
            weights_path = "yolov4.weights"
            config_path = "yolov4.cfg"
            classes_path = "coco.names"
            
            if os.path.exists(weights_path) and os.path.exists(config_path):
                self.yolo_net = cv2.dnn.readNetFromDarknet(config_path, weights_path)
                
                # Load class names
                with open(classes_path, 'r') as f:
                    self.yolo_classes = [line.strip() for line in f.readlines()]
                
                # Generate colors for each class
                np.random.seed(42)
                self.yolo_colors = np.random.randint(0, 255, size=(len(self.yolo_classes), 3))
                
                print(f"YOLO loaded with {len(self.yolo_classes)} classes")
            else:
                print("YOLO files not found, using backup detection")
                
        except Exception as e:
            print(f"Error loading YOLO: {e}")
            
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
                    
        # Note: YOLO weights file is large (~250MB) and requires manual download
        if not os.path.exists("yolov4.weights"):
            print("Please download yolov4.weights from: https://github.com/AlexeyAB/darknet/releases/download/darknet_yolo_v3_optimal/yolov4.weights")
            
    def _load_resnet(self):
        """Load ResNet50 model - placeholder for future implementation"""
        try:
            # This would load a pre-trained ResNet50 model
            # For now, we'll use OpenCV's DNN module with a pre-trained model
            print("ResNet50 model loading - placeholder")
        except Exception as e:
            print(f"Error loading ResNet: {e}")
            
    def switch_model(self, model_name: str):
        """Switch between detection models"""
        if model_name == "YOLO":
            self.current_model = "YOLO"
            if self.yolo_net is None:
                self._load_yolo()
        elif model_name == "ResNet50":
            self.current_model = "ResNet50"
            self._load_resnet()
            
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Perform object detection on frame"""
        if self.current_model == "YOLO" and self.yolo_net is not None:
            return self._detect_yolo(frame)
        elif self.current_model == "ResNet50":
            return self._detect_resnet(frame)
        else:
            return self._detect_fallback(frame)
            
    def _detect_yolo(self, frame: np.ndarray) -> List[Detection]:
        """YOLO object detection"""
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
                    
                    if confidence > self.confidence_threshold:
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
                    class_name = self.yolo_classes[class_ids[i]] if class_ids[i] < len(self.yolo_classes) else f"Class_{class_ids[i]}"
                    detections.append(Detection((x, y, w, h), class_ids[i], confidences[i], class_name))
                    
            return detections
            
        except Exception as e:
            print(f"YOLO detection error: {e}")
            return []
            
    def _detect_resnet(self, frame: np.ndarray) -> List[Detection]:
        """ResNet50 object detection - placeholder"""
        # This would implement ResNet50-based detection
        return []
        
    def _detect_fallback(self, frame: np.ndarray) -> List[Detection]:
        """Fallback detection using basic computer vision"""
        detections = []
        
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Apply Gaussian blur
            blurred = cv2.GaussianBlur(gray, (11, 11), 0)
            
            # Find contours for motion/object detection
            thresh = cv2.threshold(blurred, 60, 255, cv2.THRESH_BINARY)[1]
            contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filter contours by area
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > 1000:  # Minimum area threshold
                    x, y, w, h = cv2.boundingRect(contour)
                    # Create a generic "object" detection
                    detection = Detection((x, y, w, h), 0, 0.7, "Object")
                    detections.append(detection)
                    
        except Exception as e:
            print(f"Fallback detection error: {e}")
            
        return detections
        
    def draw_detections(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """Draw bounding boxes and labels on frame"""
        result_frame = frame.copy()
        
        for detection in detections:
            x, y, w, h = detection.bbox
            
            # Get color for this class
            if detection.class_id < len(self.yolo_colors):
                color = tuple(map(int, self.yolo_colors[detection.class_id]))
            else:
                color = (0, 255, 0)  # Default green
                
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