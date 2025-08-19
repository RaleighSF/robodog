import cv2
import threading
import time
from typing import Optional
import numpy as np

class CameraManager:
    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self.cap = None
        self.current_frame = None
        self.is_running = False
        self.capture_thread = None
        self.frame_lock = threading.Lock()
        
    def start(self) -> bool:
        """Start the camera capture"""
        try:
            # Try different camera indices if default fails
            for cam_idx in [0, 1, 2]:
                print(f"Trying camera index {cam_idx}...")
                self.cap = cv2.VideoCapture(cam_idx)
                
                if self.cap.isOpened():
                    # Test if we can actually read a frame
                    ret, test_frame = self.cap.read()
                    if ret and test_frame is not None:
                        print(f"Camera {cam_idx} working!")
                        break
                    else:
                        self.cap.release()
                        continue
                else:
                    if self.cap:
                        self.cap.release()
                    continue
            else:
                raise Exception("No working camera found. Please check camera permissions in System Preferences > Security & Privacy > Camera")
                
            # Set camera properties for better performance on Mac
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            
            self.is_running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()
            
            return True
        except Exception as e:
            print(f"Failed to start camera: {e}")
            return False
            
    def stop(self):
        """Stop the camera capture"""
        self.is_running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=1.0)
            
        if self.cap:
            self.cap.release()
            self.cap = None
            
    def _capture_loop(self):
        """Internal capture loop running in separate thread"""
        while self.is_running and self.cap:
            ret, frame = self.cap.read()
            if ret:
                with self.frame_lock:
                    self.current_frame = frame.copy()
            else:
                time.sleep(0.01)  # Brief pause if frame capture fails
                
    def get_frame(self) -> Optional[np.ndarray]:
        """Get the most recent frame"""
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
        return None
        
    def is_camera_available(self) -> bool:
        """Check if camera is available"""
        return self.cap is not None and self.cap.isOpened()

class WebRTCManager:
    """Placeholder for future WebRTC integration"""
    def __init__(self):
        self.is_connected = False
        
    def connect(self, stream_url: str):
        """Connect to WebRTC stream - to be implemented"""
        pass
        
    def disconnect(self):
        """Disconnect from WebRTC stream - to be implemented"""
        pass
        
    def get_frame(self) -> Optional[np.ndarray]:
        """Get frame from WebRTC stream - to be implemented"""
        return None