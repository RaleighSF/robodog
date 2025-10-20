#!/usr/bin/env python3
"""
Hybrid YOLO11 Detector with Visual Similarity Filtering
Combines YOLO11 object detection with feature-based visual similarity matching
"""
import cv2
import numpy as np
import time
from typing import List, Dict, Any, Optional, Tuple
import os
from collections import defaultdict

try:
    from ultralytics import YOLO
    import cv2
    ULTRALYTICS_AVAILABLE = True
    print("✅ Ultralytics imported successfully")
except ImportError as e:
    ULTRALYTICS_AVAILABLE = False
    print(f"⚠️ Ultralytics import failed: {e}")
    print("💡 Please install ultralytics: pip install ultralytics")

from config import get_config

class YOLOEDetector:
    """Hybrid YOLO11 detector with visual similarity filtering"""

    def __init__(self):
        self.config = get_config()
        self.model = None
        self.visual_prompts = []
        self.text_prompts = []
        self.detection_mode = "open"
        self.class_names = []
        self.initialized = False

        # Visual similarity matching cache
        self.cached_reference_images = {}  # Maps filename -> processed reference image
        self.cached_reference_features = {}  # Maps filename -> ORB features
        self.cached_prompt_metadata = {}  # Maps filename -> {class_name, quality_score, etc}
        self.matched_detections = []  # Stores detections that passed visual similarity filter

        # Feature detector for visual similarity (ORB is fast and works well for matching)
        self.feature_detector = cv2.ORB_create(nfeatures=500)
        self.feature_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        # Visual similarity threshold (0-1, higher score = more similar)
        # Using multi-method matching with consensus requirement (2+ methods must agree)
        # Set to 0.15 (15%) - requires at least 2 matching algorithms to agree
        self.similarity_threshold = 0.15  # Tune this based on testing

        if ULTRALYTICS_AVAILABLE:
            self._initialize_model()
        else:
            print("❌ YOLO detector cannot be initialized - ultralytics not available")
    
    def _initialize_model(self):
        """Initialize YOLO11 model for hybrid detection"""
        try:
            vision_config = self.config.get_vision_config()

            # Use YOLO11 model path from config
            model_path = self.config.get_model_path()

            print(f"🤖 Loading YOLO11 model: {model_path}")

            # Load model with device configuration
            device = vision_config.get("device", "auto")
            if device == "auto":
                device = "cuda" if cv2.cuda.getCudaEnabledDeviceCount() > 0 else "cpu"

            # Load YOLO11 model
            self.model = YOLO(model_path)
            self.model.to(device)

            # Get class names from model
            if hasattr(self.model, 'names'):
                self.class_names = list(self.model.names.values())

            print(f"✅ YOLO11 model loaded successfully on {device}")
            print(f"📋 Available classes: {len(self.class_names)} classes")

            # Initialize detection mode and prompts
            self._update_detection_mode()

            self.initialized = True

        except Exception as e:
            print(f"❌ Failed to initialize YOLO11 model: {e}")
            self.initialized = False
    
    def _update_detection_mode(self):
        """Update detection mode based on configuration"""
        self.visual_prompts = self.config.get_visual_prompts()

        # Check if NLP mode is enabled
        if self.config.is_nlp_enabled():
            nlp_prompt = self.config.get_nlp_prompt()
            if nlp_prompt:
                # Use NLP mapper to convert natural language to class list
                print(f"🤖 NLP Mode: Processing prompt '{nlp_prompt}'")
                from nlp_mapper import get_nlp_mapper

                api_key = self.config.get_openai_api_key()
                mapper = get_nlp_mapper(api_key)
                mapped_classes = mapper.map_prompt_to_classes(nlp_prompt)

                if mapped_classes:
                    self.text_prompts = mapped_classes
                    print(f"✅ NLP mapped to classes: {mapped_classes}")
                else:
                    print("⚠️ NLP mapping returned no classes")
                    self.text_prompts = []
            else:
                self.text_prompts = []
        else:
            # Use manual class list
            self.text_prompts = self.config.get_classes()

        self.detection_mode = self.config.get_detection_mode()

        print(f"🎯 Detection mode: {self.detection_mode}")
        if self.detection_mode == "visual":
            print(f"🖼️  Visual prompts: {len(self.visual_prompts)} images")
            # Precompute reference image features for visual similarity matching
            self._precompute_reference_features()
        elif self.detection_mode == "text":
            print(f"📝 Text prompts: {self.text_prompts}")
        elif self.detection_mode == "nlp":
            print(f"🤖 NLP prompts: {self.text_prompts}")
        else:
            print(f"🌐 Open detection: All {len(self.class_names)} classes")

    def _assess_reference_quality(self, image: np.ndarray, image_path: str) -> Dict[str, Any]:
        """
        Assess quality of reference image for visual prompting
        Returns quality metrics and recommendations
        """
        height, width = image.shape[:2]

        quality_report = {
            'resolution': {'width': width, 'height': height},
            'issues': [],
            'warnings': [],
            'recommendations': [],
            'quality_score': 100  # Start at 100, deduct for issues
        }

        # Check resolution - prefer 256-640px on short side
        short_side = min(width, height)
        if short_side < 256:
            quality_report['issues'].append(f"Resolution too low ({short_side}px) - prefer 256-640px on short side")
            quality_report['quality_score'] -= 30
        elif short_side > 1024:
            quality_report['warnings'].append(f"Resolution high ({short_side}px) - will be resized, prefer 256-640px")
            quality_report['quality_score'] -= 10

        # Check aspect ratio for tight cropping
        aspect_ratio = width / height
        if aspect_ratio > 2.0 or aspect_ratio < 0.5:
            quality_report['warnings'].append(f"Extreme aspect ratio ({aspect_ratio:.2f}) - object may not be tightly cropped")
            quality_report['quality_score'] -= 15

        # Check for JPEG compression artifacts (estimate from file extension)
        if image_path.lower().endswith('.jpg') or image_path.lower().endswith('.jpeg'):
            quality_report['warnings'].append("JPEG compression detected - use PNG for best quality")
            quality_report['quality_score'] -= 5

        # Check for potential busy background by analyzing edge density
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.count_nonzero(edges) / (width * height)

        if edge_density > 0.15:
            quality_report['warnings'].append(f"High edge density ({edge_density:.2%}) - background may be busy, prefer clean background")
            quality_report['quality_score'] -= 10

        # Recommendations based on findings
        if quality_report['quality_score'] < 70:
            quality_report['recommendations'].append("Consider retaking with: tight crop, clean background, 256-640px resolution, PNG format")

        return quality_report
    
    def _precompute_reference_features(self):
        """
        Precompute ORB features for all reference images
        This runs at configure time and caches features for runtime matching
        """
        if not self.visual_prompts:
            return

        print("🚀 Precomputing reference image features for visual similarity...")

        visual_prompts_with_names = self.config.get_visual_prompts_with_names()
        if not visual_prompts_with_names:
            return

        new_images = {}
        new_features = {}
        new_metadata = {}

        for prompt in visual_prompts_with_names:
            image_path = prompt.get('path', '')
            filename = prompt.get('filename', '')
            class_name = prompt.get('class_name', 'unknown')

            # Skip if already cached and valid
            if filename in self.cached_reference_features and filename in self.cached_prompt_metadata:
                new_images[filename] = self.cached_reference_images[filename]
                new_features[filename] = self.cached_reference_features[filename]
                new_metadata[filename] = self.cached_prompt_metadata[filename]
                print(f"✅ Using cached features for '{class_name}' ({filename})")
                continue

            if not os.path.exists(image_path):
                print(f"⚠️ Visual prompt image not found: {image_path}")
                continue

            # Load reference image
            ref_image = cv2.imread(image_path)
            if ref_image is None:
                print(f"⚠️ Failed to load visual prompt image: {image_path}")
                continue

            # Assess reference quality
            quality_report = self._assess_reference_quality(ref_image, image_path)
            print(f"📊 Quality score for '{class_name}': {quality_report['quality_score']}/100")

            if quality_report['issues']:
                for issue in quality_report['issues']:
                    print(f"  ❌ {issue}")
            if quality_report['warnings']:
                for warning in quality_report['warnings']:
                    print(f"  ⚠️ {warning}")
            if quality_report['recommendations']:
                for rec in quality_report['recommendations']:
                    print(f"  💡 {rec}")

            try:
                # Convert to grayscale for feature detection
                gray = cv2.cvtColor(ref_image, cv2.COLOR_BGR2GRAY)

                # Detect ORB keypoints and descriptors
                keypoints, descriptors = self.feature_detector.detectAndCompute(gray, None)

                if descriptors is not None and len(keypoints) > 10:
                    new_images[filename] = ref_image
                    new_features[filename] = {
                        'keypoints': keypoints,
                        'descriptors': descriptors,
                        'shape': ref_image.shape
                    }
                    new_metadata[filename] = {
                        'class_name': class_name,
                        'quality_score': quality_report['quality_score'],
                        'path': image_path,
                        'num_features': len(keypoints)
                    }
                    print(f"✅ Extracted {len(keypoints)} features for '{class_name}' ({filename})")
                else:
                    print(f"⚠️ Insufficient features detected for '{class_name}' - image may be too simple or uniform")

            except Exception as e:
                print(f"❌ Failed to extract features for '{class_name}': {e}")

        # Update caches
        self.cached_reference_images = new_images
        self.cached_reference_features = new_features
        self.cached_prompt_metadata = new_metadata

        print(f"🎯 Feature cache ready: {len(self.cached_reference_features)} reference images processed")

    def reload_config(self):
        """Reload configuration and update detection mode"""
        self.config._load_config_file()  # Reload from file
        self._update_detection_mode()
        print("🔄 YOLO-E configuration reloaded")
    
    def detect(self, frame: np.ndarray, frame_timestamp: float = None) -> List[Dict[str, Any]]:
        """
        Perform detection on frame using configured mode

        Returns:
            List of detections with schema: {
                'xyxy': [x1, y1, x2, y2],
                'class_name': str,
                'confidence': float,
                'frame_ts': float
            }
        """
        if not self.initialized or not ULTRALYTICS_AVAILABLE:
            return []

        if frame is None or frame.size == 0:
            return []

        frame_ts = frame_timestamp if frame_timestamp else time.time()

        try:
            vision_config = self.config.get_vision_config()

            # Run inference based on detection mode
            if self.detection_mode == "visual":
                results = self._visual_prompted_detection(frame, vision_config)
            elif self.detection_mode == "text" or self.detection_mode == "nlp":
                # Both text and NLP modes use text-prompted detection
                # NLP mode just uses AI-mapped classes instead of manual ones
                results = self._text_prompted_detection(frame, vision_config)
            else:
                results = self._open_detection(frame, vision_config)

            # Convert results to standard format
            detections = self._convert_results(results, frame_ts)

            return detections

        except Exception as e:
            print(f"❌ YOLO-E detection error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return []
    
    def _compute_visual_similarity(self, detection_crop: np.ndarray, ref_filename: str) -> float:
        """
        Compute visual similarity using multiple methods:
        1. Color histogram comparison (works great for logos)
        2. Template matching at multiple scales
        3. ORB feature matching as fallback
        Returns similarity score (0-1, higher = more similar)
        """
        if ref_filename not in self.cached_reference_images:
            return 0.0

        try:
            ref_image = self.cached_reference_images[ref_filename]

            # Method 1: Color Histogram Comparison (works great for logos with distinct colors)
            hist_similarity = self._compute_histogram_similarity(detection_crop, ref_image)

            # Method 2: Template matching with multiple scales
            template_similarity = self._compute_template_similarity(detection_crop, ref_image)

            # Method 3: ORB feature matching (original method)
            orb_similarity = self._compute_orb_similarity(detection_crop, ref_filename)

            # Debug: print individual scores
            # print(f"    Scores: hist={hist_similarity:.3f}, template={template_similarity:.3f}, orb={orb_similarity:.3f}", flush=True)

            # Weighted combination: Histogram and template matching work better for logos
            # BUT require consensus - at least 2 methods must score > 0.15 to avoid false positives
            scores = [hist_similarity, template_similarity, orb_similarity]
            high_scores = [s for s in scores if s > 0.15]

            # If fewer than 2 methods agree it's similar, penalize heavily
            if len(high_scores) < 2:
                # Return the max score but heavily penalized
                final_similarity = max(scores) * 0.3
                # print(f"    Consensus FAILED: only {len(high_scores)} methods > 0.15, penalized to {final_similarity:.3f}", flush=True)
                return final_similarity

            # Otherwise use weighted average
            final_similarity = (hist_similarity * 0.4) + (template_similarity * 0.4) + (orb_similarity * 0.2)
            # print(f"    Consensus OK: {len(high_scores)} methods agree, final={final_similarity:.3f}", flush=True)

            return final_similarity

        except Exception as e:
            print(f"⚠️ Error computing visual similarity: {e}", flush=True)
            return 0.0

    def _compute_histogram_similarity(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Compare color histograms - works great for logos with distinct colors"""
        try:
            # Convert to HSV for better color comparison
            hsv1 = cv2.cvtColor(img1, cv2.COLOR_BGR2HSV)
            hsv2 = cv2.cvtColor(img2, cv2.COLOR_BGR2HSV)

            # Calculate histograms
            hist1 = cv2.calcHist([hsv1], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
            hist2 = cv2.calcHist([hsv2], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])

            # Normalize
            cv2.normalize(hist1, hist1)
            cv2.normalize(hist2, hist2)

            # Compare using correlation
            similarity = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)

            # Convert from [-1, 1] to [0, 1]
            return (similarity + 1) / 2.0

        except Exception as e:
            return 0.0

    def _compute_template_similarity(self, detection: np.ndarray, template: np.ndarray) -> float:
        """Multi-scale template matching"""
        try:
            detection_gray = cv2.cvtColor(detection, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

            # Try multiple scales
            best_score = 0.0
            scales = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

            for scale in scales:
                # Resize template
                width = int(template_gray.shape[1] * scale)
                height = int(template_gray.shape[0] * scale)

                if width > detection_gray.shape[1] or height > detection_gray.shape[0]:
                    continue
                if width < 20 or height < 20:
                    continue

                resized_template = cv2.resize(template_gray, (width, height))

                # Template matching
                result = cv2.matchTemplate(detection_gray, resized_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)

                if max_val > best_score:
                    best_score = max_val

            return best_score

        except Exception as e:
            return 0.0

    def _compute_orb_similarity(self, detection_crop: np.ndarray, ref_filename: str) -> float:
        """Original ORB feature matching"""
        if ref_filename not in self.cached_reference_features:
            return 0.0

        try:
            ref_features = self.cached_reference_features[ref_filename]
            ref_descriptors = ref_features['descriptors']

            gray_crop = cv2.cvtColor(detection_crop, cv2.COLOR_BGR2GRAY)
            keypoints, descriptors = self.feature_detector.detectAndCompute(gray_crop, None)

            if descriptors is None or len(keypoints) < 10:
                return 0.0

            matches = self.feature_matcher.match(ref_descriptors, descriptors)
            if not matches:
                return 0.0

            matches = sorted(matches, key=lambda x: x.distance)
            num_good_matches = len([m for m in matches if m.distance < 50])
            max_possible_matches = min(len(ref_descriptors), len(descriptors))

            return num_good_matches / max_possible_matches if max_possible_matches > 0 else 0.0

        except Exception as e:
            return 0.0

    def _visual_prompted_detection(self, frame: np.ndarray, config: Dict) -> Any:
        """
        Direct visual search: Find regions in the frame that look like the reference image
        Uses multi-scale template matching to search the entire frame for the logo
        """
        print(f"🖼️  Running direct visual search for reference image...", flush=True)

        # If no visual prompts are loaded, return empty results
        if not self.visual_prompts or not self.cached_reference_images:
            print("⚠️ No visual prompts loaded - returning empty results", flush=True)
            return []

        try:
            self.matched_detections = []

            # Search for each reference image in the frame
            for ref_filename, ref_metadata in self.cached_prompt_metadata.items():
                ref_image = self.cached_reference_images[ref_filename]
                class_name = ref_metadata['class_name']

                # Find all instances of the reference image in the frame
                matches = self._find_template_in_frame(frame, ref_image, class_name)
                self.matched_detections.extend(matches)

            # Return mock results compatible with YOLO format
            if self.matched_detections:
                return [self._create_mock_result(frame)]
            else:
                return []

        except Exception as e:
            print(f"❌ Visual search failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return []

    def _find_template_in_frame(self, frame: np.ndarray, template: np.ndarray, class_name: str) -> List[Dict]:
        """
        Search for template in frame using feature-based matching (SIFT)
        More robust to lighting, perspective, and transformations than template matching
        """
        matches = []

        try:
            # Use SIFT for better invariance to scale, rotation, and lighting
            sift = cv2.SIFT_create()

            # Find keypoints and descriptors
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

            kp_template, des_template = sift.detectAndCompute(template_gray, None)
            kp_frame, des_frame = sift.detectAndCompute(frame_gray, None)

            if des_template is None or des_frame is None:
                return []

            # Use FLANN matcher for better performance
            FLANN_INDEX_KDTREE = 1
            index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
            search_params = dict(checks=50)
            flann = cv2.FlannBasedMatcher(index_params, search_params)

            matches_raw = flann.knnMatch(des_template, des_frame, k=2)

            # Apply Lowe's ratio test
            good_matches = []
            for match_pair in matches_raw:
                if len(match_pair) == 2:
                    m, n = match_pair
                    if m.distance < 0.7 * n.distance:  # Lowe's ratio
                        good_matches.append(m)

            # Need at least 10 matches to find the object
            if len(good_matches) >= 10:
                # Extract matched keypoint locations
                src_pts = np.float32([kp_template[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                dst_pts = np.float32([kp_frame[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

                # Find homography
                M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

                if M is not None:
                    # Get corners of template
                    h, w = template_gray.shape
                    pts = np.float32([[0, 0], [0, h-1], [w-1, h-1], [w-1, 0]]).reshape(-1, 1, 2)

                    # Transform corners to frame coordinates
                    dst = cv2.perspectiveTransform(pts, M)

                    # Get bounding box
                    x_coords = dst[:, 0, 0]
                    y_coords = dst[:, 0, 1]
                    x1, y1 = int(min(x_coords)), int(min(y_coords))
                    x2, y2 = int(max(x_coords)), int(max(y_coords))

                    # Calculate confidence based on number of inliers
                    inliers = np.sum(mask)
                    confidence = min(1.0, inliers / len(good_matches))

                    matches.append({
                        'bbox': [x1, y1, x2, y2],
                        'similarity': float(confidence),
                        'class_name': class_name,
                        'inliers': int(inliers)
                    })

        except Exception as e:
            pass  # Silently fail on feature matching errors

        return matches

    def _create_mock_result(self, frame: np.ndarray):
        """Create a mock YOLO result object for compatibility"""
        import torch

        class MockBoxes:
            def __init__(self, detections):
                self.xyxy = torch.tensor([d['bbox'] for d in detections], dtype=torch.float32)
                self.conf = torch.tensor([d['similarity'] for d in detections], dtype=torch.float32)
                self.cls = torch.tensor([0] * len(detections), dtype=torch.float32)  # Dummy class

            def __len__(self):
                return len(self.xyxy)

        class MockResult:
            def __init__(self, detections):
                self.boxes = MockBoxes(detections) if detections else None

        return MockResult(self.matched_detections)
    
    
    def _text_prompted_detection(self, frame: np.ndarray, config: Dict) -> Any:
        """Perform text-prompted detection restricted to specified classes"""
        print(f"📝 Running text-prompted detection for classes: {self.text_prompts}")
        
        # Find class indices for text prompts with flexible matching
        class_indices = []
        for class_name in self.text_prompts:
            class_name_lower = class_name.lower()
            
            # Try exact match first
            if class_name_lower in [name.lower() for name in self.class_names]:
                idx = next(i for i, name in enumerate(self.class_names) if name.lower() == class_name_lower)
                class_indices.append(idx)
                print(f"✅ Found exact match: '{class_name}' -> class {idx} ('{self.class_names[idx]}')")
            else:
                # Try partial match (e.g., "phone" matches "cell phone")
                found = False
                for i, name in enumerate(self.class_names):
                    if class_name_lower in name.lower() or name.lower() in class_name_lower:
                        class_indices.append(i)
                        print(f"✅ Found partial match: '{class_name}' -> class {i} ('{name}')")
                        found = True
                        break
                
                if not found:
                    print(f"❌ No match found for class: '{class_name}'")
                    print(f"💡 Available classes: {', '.join(self.class_names[:10])}...")
        
        if not class_indices:
            print("⚠️ No valid classes found - returning empty results to prevent detecting all classes")
            # Return empty results instead of detecting all classes
            return []
        
        print(f"🎯 Filtering to class indices: {class_indices}")
        results = self.model.predict(
            frame,
            conf=config.get("conf", 0.25),
            iou=config.get("iou", 0.45),
            max_det=config.get("max_det", 100),
            imgsz=config.get("imgsz", 640),
            classes=class_indices,
            verbose=False
        )
        
        return results
    
    def _open_detection(self, frame: np.ndarray, config: Dict) -> Any:
        """Perform open detection (detect all classes)"""
        print("🌐 Running open detection (all classes)")
        
        results = self.model.predict(
            frame,
            conf=config.get("conf", 0.25),
            iou=config.get("iou", 0.45),
            max_det=config.get("max_det", 100),
            imgsz=config.get("imgsz", 640),
            verbose=False
        )
        
        return results
    
    def _convert_results(self, results: Any, frame_ts: float) -> List[Dict[str, Any]]:
        """Convert YOLO results to standard detection format"""
        detections = []

        try:
            # Check if we're in visual mode with matched detections
            if self.detection_mode == "visual" and hasattr(self, 'matched_detections') and self.matched_detections:
                # Return detections from direct visual search (new format with bbox)
                for match in self.matched_detections:
                    detection = {
                        'xyxy': match['bbox'],
                        'class_name': match['class_name'],
                        'confidence': match['similarity'],  # Use similarity as confidence
                        'frame_ts': frame_ts,
                        'similarity': match['similarity']
                    }
                    detections.append(detection)
                    print(f"🔍 Visual Match: class_name='{match['class_name']}', similarity={match['similarity']:.3f}", flush=True)

                return detections

            # Handle standard YOLO11 results format (text or open mode)
            for result in results:
                if hasattr(result, 'boxes') and result.boxes is not None:
                    boxes = result.boxes

                    for i in range(len(boxes)):
                        # Get bounding box coordinates (xyxy format)
                        if hasattr(boxes, 'xyxy'):
                            xyxy = boxes.xyxy[i].cpu().numpy().tolist()
                        else:
                            continue

                        # Get confidence
                        if hasattr(boxes, 'conf'):
                            confidence = float(boxes.conf[i].cpu().numpy())
                        else:
                            confidence = 0.0

                        # Get class name
                        if hasattr(boxes, 'cls'):
                            class_id = int(boxes.cls[i].cpu().numpy())
                            class_name = self.class_names[class_id] if class_id < len(self.class_names) else f"class_{class_id}"
                            print(f"🔍 Detection: class_id={class_id}, class_name='{class_name}', confidence={confidence:.3f}")
                        else:
                            class_name = "unknown"
                            print(f"🔍 Detection: class_name='unknown' (no cls attribute), confidence={confidence:.3f}")

                        detection = {
                            'xyxy': xyxy,
                            'class_name': class_name,
                            'confidence': confidence,
                            'frame_ts': frame_ts
                        }

                        detections.append(detection)

        except Exception as e:
            print(f"⚠️ Error converting YOLO results: {e}")

        return detections
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model"""
        if not self.initialized:
            return {"status": "not_initialized", "available": ULTRALYTICS_AVAILABLE}
        
        return {
            "status": "initialized",
            "available": ULTRALYTICS_AVAILABLE,
            "model_path": self.config.get_model_path(),
            "engine_path": self.config.get_engine_path(),
            "detection_mode": self.detection_mode,
            "classes_available": len(self.class_names),
            "text_prompts": self.text_prompts,
            "visual_prompts_count": len(self.visual_prompts),
            "device": str(self.model.device) if self.model else "unknown"
        }
    
    def update_prompts(self, classes: List[str] = None, visual_prompts: List[str] = None):
        """Update detection prompts"""
        if classes is not None:
            self.config.update_classes(classes)
        
        if visual_prompts is not None:
            self.config.update_visual_prompts(visual_prompts)
        
        self._update_detection_mode()
        print("✅ Detection prompts updated")
    
    def has_visual_prompts(self) -> bool:
        """Check if visual prompts are configured"""
        return len(self.visual_prompts) > 0
    
    def set_detection_parameters(self, conf: float = None, iou: float = None, max_det: int = None):
        """Update detection parameters"""
        vision_config = self.config.config["vision"]
        
        if conf is not None:
            vision_config["conf"] = conf
        if iou is not None:
            vision_config["iou"] = iou
        if max_det is not None:
            vision_config["max_det"] = max_det
        
        print(f"✅ Detection parameters updated: conf={vision_config['conf']}, iou={vision_config['iou']}, max_det={vision_config['max_det']}")

# Global detector instance
detector_instance = None

def get_yoloe_detector() -> YOLOEDetector:
    """Get global YOLO-E detector instance (singleton)"""
    global detector_instance
    if detector_instance is None:
        detector_instance = YOLOEDetector()
    return detector_instance