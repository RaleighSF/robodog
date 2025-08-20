import cv2
import threading
import time
import asyncio
from typing import Optional
import numpy as np
from unitree_client import UnitreeGo2Client

class CameraManager:
    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self.cap = None
        self.current_frame = None
        self.is_running = False
        self.capture_thread = None
        self.frame_lock = threading.Lock()
        
        # Camera source options
        self.camera_source = "mac"  # "mac" or "unitree"
        self.unitree_client = None
        self.robot_ip = "192.168.12.1"
        
    def set_camera_source(self, source: str, robot_ip: str = None):
        """Set camera source: 'mac' or 'unitree'"""
        if source in ["mac", "unitree"]:
            was_running = self.is_running
            if was_running:
                self.stop()
                
            self.camera_source = source
            if robot_ip:
                self.robot_ip = robot_ip
                
            # Create Unitree client immediately when switching to Unitree
            if source == "unitree":
                print(f"Creating Unitree client for {self.robot_ip}")
                self.unitree_client = UnitreeGo2Client(self.robot_ip, serial_number="B42D2000P7H8JNC7")
                print(f"Unitree client created: {self.unitree_client is not None}")
            else:
                # Clean up Unitree client when switching away
                if self.unitree_client:
                    self.unitree_client.disconnect()
                    self.unitree_client = None
                    
            if was_running:
                self.start()
                
    def start(self) -> bool:
        """Start the camera capture"""
        if self.camera_source == "mac":
            return self._start_mac_camera()
        elif self.camera_source == "unitree":
            return self._start_unitree_camera()
        else:
            print(f"Unknown camera source: {self.camera_source}")
            return False
            
    def _start_mac_camera(self) -> bool:
        """Start Mac camera capture"""
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
            self.capture_thread = threading.Thread(target=self._mac_capture_loop, daemon=True)
            self.capture_thread.start()
            
            return True
        except Exception as e:
            print(f"Failed to start Mac camera: {e}")
            return False
            
    def _start_unitree_camera(self) -> bool:
        """Start Unitree Go2 camera capture"""
        try:
            print(f"Connecting to Unitree Go2 at {self.robot_ip}...")
            self.unitree_client = UnitreeGo2Client(self.robot_ip, serial_number="B42D2000P7H8JNC7")
            
            # Discover robot first
            discovery = self.unitree_client.discover_robot()
            print(f"Robot discovery: {discovery}")
            
            # Start async connection in background
            self.is_running = True
            self.capture_thread = threading.Thread(target=self._unitree_capture_loop, daemon=True)
            self.capture_thread.start()
            
            return True
        except Exception as e:
            print(f"Failed to start Unitree camera: {e}")
            return False
            
    def stop(self):
        """Stop the camera capture"""
        self.is_running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=1.0)
            
        if self.cap:
            self.cap.release()
            self.cap = None
            
        if self.unitree_client:
            self.unitree_client.disconnect()
            self.unitree_client = None
            
    def _mac_capture_loop(self):
        """Internal capture loop for Mac camera running in separate thread"""
        while self.is_running and self.cap:
            ret, frame = self.cap.read()
            if ret:
                with self.frame_lock:
                    self.current_frame = frame.copy()
            else:
                time.sleep(0.01)  # Brief pause if frame capture fails
                
    def _unitree_capture_loop(self):
        """Internal capture loop for Unitree Go2 camera"""
        async def connect_and_stream():
            try:
                # Connect to robot
                connected = await self.unitree_client.connect()
                if connected:
                    print("Connected to Unitree Go2!")
                    
                    # Set up frame callback
                    def frame_callback(frame):
                        with self.frame_lock:
                            self.current_frame = frame.copy()
                    
                    # Start video stream
                    self.unitree_client.start_video_stream(frame_callback)
                    
                    # Keep alive while streaming
                    while self.is_running:
                        await asyncio.sleep(0.1)
                        
                else:
                    print("Failed to connect to Unitree Go2, starting test pattern...")
                    self.unitree_client.start_video_stream()
                    
                    while self.is_running:
                        frame = self.unitree_client.get_frame()
                        if frame is not None:
                            with self.frame_lock:
                                self.current_frame = frame.copy()
                        await asyncio.sleep(1/30)  # 30 FPS
                        
            except Exception as e:
                print(f"Unitree capture error: {e}")
                
        # Run async event loop in thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(connect_and_stream())
        finally:
            loop.close()
                
    def get_frame(self) -> Optional[np.ndarray]:
        """Get the most recent frame"""
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
        return None
        
    def is_camera_available(self) -> bool:
        """Check if camera is available"""
        if self.camera_source == "mac":
            return self.cap is not None and self.cap.isOpened()
        elif self.camera_source == "unitree":
            return self.unitree_client is not None and self.unitree_client.is_connected
        return False
        
    def get_camera_status(self) -> dict:
        """Get detailed camera status"""
        status = {
            "source": self.camera_source,
            "is_running": self.is_running,
            "available": self.is_camera_available()
        }
        
        if self.camera_source == "mac":
            status.update({
                "camera_index": self.camera_index,
                "opencv_available": self.cap is not None
            })
        elif self.camera_source == "unitree":
            status.update({
                "robot_ip": self.robot_ip,
                "unitree_client": self.unitree_client is not None
            })
            
            if self.unitree_client:
                status.update(self.unitree_client.get_robot_status())
                
        return status

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