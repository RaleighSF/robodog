#!/usr/bin/env python3
"""
Configuration management for Watch Dog Vision System
Supports YOLO-E detector with flexible configuration
"""
import os
import json
import yaml
from typing import List, Dict, Any, Optional

class VisionConfig:
    """Vision system configuration with YOLO-E support"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_default_config()
        self._load_config_file()
        
    def _load_default_config(self) -> Dict[str, Any]:
        """Load default configuration"""
        return {
            "vision": {
                "detector": "yoloe",
                "model_path": "yolo11s-seg.pt",
                "engine_path": "",  # Optional TensorRT engine path
                "source": "rtsp://192.168.86.21:8554/color",
                "rtsp_tcp": True,
                "classes": [],  # Text prompts - empty = detect all
                "visual_prompts": [],  # Image paths for visual prompting
                "nlp_prompt": "",  # Natural language prompt for AI-based class mapping
                "nlp_enabled": False,  # Enable NLP-based class mapping
                "openai_api_key": "",  # OpenAI API key for NLP mapping
                "conf": 0.25,  # Confidence threshold
                "iou": 0.45,   # IoU threshold for NMS
                "max_det": 100,  # Maximum detections per frame
                "device": "auto",  # "auto", "cpu", "cuda"
                "imgsz": 640   # Input image size
            },
            "rtsp": {
                "reconnect_interval": 5,  # seconds
                "max_reconnect_attempts": 10,
                "buffer_size": 1,
                "timeout": 30000  # milliseconds
            },
            "detection": {
                "save_images": True,
                "save_thumbnails": True,
                "log_detections": True,
                "detection_cooldown": 2.0  # seconds between alerts
            }
        }
    
    def _load_config_file(self):
        """Load configuration from file if it exists"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    if self.config_path.endswith('.yaml') or self.config_path.endswith('.yml'):
                        file_config = yaml.safe_load(f)
                    else:
                        file_config = json.load(f)
                
                # Merge with default config
                self._deep_merge(self.config, file_config)
                print(f"✅ Loaded configuration from {self.config_path}")
            except Exception as e:
                print(f"⚠️ Error loading config file: {e}, using defaults")
        else:
            print(f"📄 No config file found at {self.config_path}, using defaults")
    
    def _deep_merge(self, base_dict: Dict, update_dict: Dict):
        """Deep merge two dictionaries"""
        for key, value in update_dict.items():
            if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                self._deep_merge(base_dict[key], value)
            else:
                base_dict[key] = value
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            with open(self.config_path, 'w') as f:
                if self.config_path.endswith('.yaml') or self.config_path.endswith('.yml'):
                    yaml.safe_dump(self.config, f, default_flow_style=False, indent=2)
                else:
                    json.dump(self.config, f, indent=2)
            print(f"✅ Configuration saved to {self.config_path}")
        except Exception as e:
            print(f"❌ Error saving config: {e}")
    
    def get_vision_config(self) -> Dict[str, Any]:
        """Get vision configuration"""
        return self.config.get("vision", {})
    
    def get_detector_type(self) -> str:
        """Get current detector type"""
        return self.config.get("vision", {}).get("detector", "yoloe")
    
    def is_yoloe(self) -> bool:
        """Check if using YOLO-E detector"""
        return self.get_detector_type() == "yoloe"
    
    def get_model_path(self) -> str:
        """Get model path for current detector"""
        return self.config["vision"]["model_path"]
    
    def get_engine_path(self) -> Optional[str]:
        """Get TensorRT engine path if available"""
        engine_path = self.config["vision"].get("engine_path", "")
        return engine_path if engine_path and os.path.exists(engine_path) else None
    
    def get_classes(self) -> List[str]:
        """Get text prompt classes"""
        return self.config["vision"].get("classes", [])
    
    def get_visual_prompts(self) -> List[str]:
        """Get visual prompt image paths (legacy support)"""
        prompts = self.config["vision"].get("visual_prompts", [])
        # Handle both old format (list of strings) and new format (list of objects)
        if not prompts:
            return []
        
        result_paths = []
        for prompt in prompts:
            if isinstance(prompt, str):
                # Old format - prompt is a path string
                if os.path.exists(prompt):
                    result_paths.append(prompt)
            elif isinstance(prompt, dict):
                # New format - prompt is an object with path
                path = prompt.get("path", "")
                if path and os.path.exists(path):
                    result_paths.append(path)
        
        return result_paths
    
    def get_visual_prompts_with_names(self) -> List[Dict[str, str]]:
        """Get visual prompts with class names"""
        prompts = self.config["vision"].get("visual_prompts", [])
        if not prompts:
            return []
        
        result_prompts = []
        string_counter = 1
        
        for prompt in prompts:
            if isinstance(prompt, str):
                # Old format - prompt is a path string
                if os.path.exists(prompt):
                    result_prompts.append({
                        "path": prompt,
                        "class_name": f"custom-{string_counter}",
                        "filename": os.path.basename(prompt)
                    })
                    string_counter += 1
            elif isinstance(prompt, dict):
                # New format - prompt is an object
                path = prompt.get("path", "")
                if path and os.path.exists(path):
                    result_prompts.append({
                        "path": path,
                        "class_name": prompt.get("class_name", f"custom-{len(result_prompts)+1}"),
                        "filename": prompt.get("filename", os.path.basename(path))
                    })
        
        return result_prompts
    
    def has_visual_prompts(self) -> bool:
        """Check if visual prompts are configured"""
        return len(self.get_visual_prompts()) > 0
    
    def has_text_prompts(self) -> bool:
        """Check if text prompts (classes) are configured"""
        return len(self.get_classes()) > 0
    
    def get_detection_mode(self) -> str:
        """Determine detection mode: 'nlp', 'visual', 'text', or 'open'"""
        if self.is_nlp_enabled():
            return "nlp"     # NLP-prompted detection (AI natural language)
        elif self.has_visual_prompts():
            return "visual"  # Visual-prompted detection
        elif self.has_text_prompts():
            return "text"    # Text-prompted detection
        else:
            return "open"    # Open detection (detect everything)
    
    def update_classes(self, classes: List[str]):
        """Update text prompt classes"""
        self.config["vision"]["classes"] = classes
    
    def update_visual_prompts(self, image_paths: List[str]):
        """Update visual prompt images (legacy format)"""
        # Validate paths exist
        valid_paths = [p for p in image_paths if os.path.exists(p)]
        self.config["vision"]["visual_prompts"] = valid_paths
    
    def update_visual_prompts_with_names(self, prompts: List[Dict[str, str]]):
        """Update visual prompts with class names (new format)"""
        # Validate paths exist and format properly
        valid_prompts = []
        for prompt in prompts:
            if isinstance(prompt, dict) and "path" in prompt and os.path.exists(prompt["path"]):
                formatted_prompt = {
                    "path": prompt["path"],
                    "class_name": prompt.get("class_name", "custom"),
                    "filename": os.path.basename(prompt["path"])
                }
                valid_prompts.append(formatted_prompt)
        
        self.config["vision"]["visual_prompts"] = valid_prompts
    
    def add_visual_prompt(self, image_path: str, class_name: str = None) -> bool:
        """Add a visual prompt image with optional class name"""
        if not os.path.exists(image_path):
            return False
        
        # Initialize visual_prompts as empty list if needed
        if "visual_prompts" not in self.config["vision"]:
            self.config["vision"]["visual_prompts"] = []
        
        visual_prompts = self.config["vision"]["visual_prompts"]
        
        # Check if we already have this path in any format
        for i, prompt in enumerate(visual_prompts):
            if isinstance(prompt, str) and prompt == image_path:
                return False  # Already exists
            elif isinstance(prompt, dict) and prompt.get("path") == image_path:
                return False  # Already exists
        
        # Add new visual prompt with class name
        if class_name:
            new_prompt = {
                "path": image_path,
                "class_name": class_name,
                "filename": os.path.basename(image_path)
            }
        else:
            # Generate default class name if none provided
            prompt_count = len([p for p in visual_prompts if isinstance(p, dict) or isinstance(p, str)])
            new_prompt = {
                "path": image_path,
                "class_name": f"custom-{prompt_count + 1}",
                "filename": os.path.basename(image_path)
            }
        
        visual_prompts.append(new_prompt)
        return True
    
    def remove_visual_prompt(self, image_path: str) -> bool:
        """Remove a visual prompt image"""
        visual_prompts = self.config["vision"].get("visual_prompts", [])
        
        # Find and remove the prompt (handle both old and new format)
        for i, prompt in enumerate(visual_prompts):
            if isinstance(prompt, str) and prompt == image_path:
                visual_prompts.pop(i)
                return True
            elif isinstance(prompt, dict) and prompt.get("path") == image_path:
                visual_prompts.pop(i)
                return True
        
        return False
    
    def get_rtsp_config(self) -> Dict[str, Any]:
        """Get RTSP configuration"""
        return self.config.get("rtsp", {})
    
    def get_detection_config(self) -> Dict[str, Any]:
        """Get detection configuration"""
        return self.config.get("detection", {})
    
    def is_alert_logging_enabled(self) -> bool:
        """Check if alert logging is enabled"""
        return self.config.get("detection", {}).get("alert_logging", True)
    
    def set_alert_logging(self, enabled: bool) -> None:
        """Enable or disable alert logging"""
        if "detection" not in self.config:
            self.config["detection"] = {}
        self.config["detection"]["alert_logging"] = enabled
        self.save_config()

    def get_nlp_prompt(self) -> str:
        """Get natural language prompt"""
        return self.config["vision"].get("nlp_prompt", "")

    def is_nlp_enabled(self) -> bool:
        """Check if NLP-based class mapping is enabled"""
        return self.config["vision"].get("nlp_enabled", False)

    def get_openai_api_key(self) -> str:
        """Get OpenAI API key"""
        return self.config["vision"].get("openai_api_key", "")

    def set_nlp_prompt(self, prompt: str, enabled: bool = True):
        """Set natural language prompt and enable NLP mode"""
        self.config["vision"]["nlp_prompt"] = prompt
        self.config["vision"]["nlp_enabled"] = enabled
        self.save_config()

    def set_openai_api_key(self, api_key: str):
        """Set OpenAI API key"""
        self.config["vision"]["openai_api_key"] = api_key
        self.save_config()

    def disable_nlp(self):
        """Disable NLP-based class mapping"""
        self.config["vision"]["nlp_enabled"] = False
        self.save_config()

# Global configuration instance
config = VisionConfig()

def get_config() -> VisionConfig:
    """Get global configuration instance"""
    return config