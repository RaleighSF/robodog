import cv2
import threading
import time
import asyncio
from typing import Optional
import numpy as np
from unitree_client import UnitreeGo2Client
import os
import signal

class CameraManager:
    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self.cap = None
        self.current_frame = None
        self.is_running = False
        self.capture_thread = None
        self.frame_lock = threading.Lock()
        
        # Camera source options - default to Mac for reliability, Color Channel auto-starts via web UI  
        self.camera_source = "mac"  # "mac", "unitree", or "rtsp_*"
        self.unitree_client = None
        self.robot_ip = "192.168.87.25"
        
        # RTSP channel URLs with TCP transport for better reliability
        self.rtsp_channels = {
            "rtsp_color": "rtsp://192.168.86.21:8554/color",
            "rtsp_ir": "rtsp://192.168.86.21:8554/ir", 
            "rtsp_depth": "rtsp://192.168.86.21:8554/depth",
            "rtsp_test": "rtsp://192.168.86.21:8554/test"  # Keep for backward compatibility
        }
        self.rtsp_url = self.rtsp_channels["rtsp_color"]  # Default to color
        
    def set_camera_source(self, source: str, robot_ip: str = None, rtsp_url: str = None):
        """Set camera source: 'mac', 'unitree', or 'rtsp_*'"""
        valid_sources = ["mac", "unitree"] + list(self.rtsp_channels.keys())
        if source in valid_sources:
            was_running = self.is_running
            if was_running:
                self.stop()
                
            self.camera_source = source
            if robot_ip:
                self.robot_ip = robot_ip
            
            # Handle RTSP channel selection
            if source.startswith("rtsp_"):
                if source in self.rtsp_channels:
                    self.rtsp_url = self.rtsp_channels[source]
                    print(f"RTSP channel selected: {source} -> {self.rtsp_url}")
                elif rtsp_url:
                    self.rtsp_url = rtsp_url
            elif rtsp_url:
                self.rtsp_url = rtsp_url
                
            # Create Unitree client immediately when switching to Unitree
            if source == "unitree":
                print(f"Creating Unitree client for {self.robot_ip}")
                self.unitree_client = UnitreeGo2Client(self.robot_ip, serial_number="B42D4000P6PC04GE")
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
        elif self.camera_source.startswith("rtsp"):
            return self._start_rtsp_camera()
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
            print(f"Starting Unitree Go2 camera at {self.robot_ip}...")
            
            # Use existing client if available, otherwise create new one
            if not self.unitree_client:
                print("Creating new Unitree client...")
                self.unitree_client = UnitreeGo2Client(self.robot_ip, serial_number="B42D4000P6PC04GE")
            else:
                print("Using existing Unitree client")
            
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
            
    def _start_rtsp_camera(self) -> bool:
        """Start RTSP camera capture from Jetson with robust connection handling"""
        try:
            print(f"Starting RTSP camera from {self.rtsp_url}...")
            
            # Build RTSP URL with optimized transport parameters
            rtsp_options = {
                "rtsp_transport": "tcp",  # Use TCP for more reliable transport
                "rtsp_flags": "prefer_tcp",
                "stimeout": "5000000",  # 5 second socket timeout (in microseconds)
                "max_delay": "500000",  # 0.5 second max delay
                "fflags": "nobuffer+flush_packets",  # Minimize buffering
                "flags": "low_delay",
                "probesize": "32",  # Smaller probe size for faster startup
                "analyzeduration": "100000"  # 100ms analyze duration
            }
            
            # Connect to RTSP stream with retry logic
            print(f"Attempting RTSP connection to: {self.rtsp_url}")
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                    
                    # Apply optimized properties immediately after opening
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffering
                    self.cap.set(cv2.CAP_PROP_FPS, 15)        # Lower FPS for stability
                    
                    # Set FFmpeg-specific properties for better reliability
                    # Note: These may not all be supported but won't cause errors
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('H', '2', '6', '4'))
                    
                    if self.cap.isOpened():
                        print(f"✅ RTSP connection established (attempt {attempt + 1})")
                        break
                    else:
                        print(f"❌ RTSP connection failed (attempt {attempt + 1})")
                        if self.cap:
                            self.cap.release()
                        if attempt < max_retries - 1:
                            time.sleep(1)  # Wait before retry
                            
                except Exception as retry_error:
                    print(f"❌ Connection attempt {attempt + 1} error: {retry_error}")
                    if self.cap:
                        self.cap.release()
                    if attempt < max_retries - 1:
                        time.sleep(1)  # Wait before retry
            else:
                raise Exception(f"Failed to connect to RTSP stream after {max_retries} attempts")
            
            # Quick frame test with short timeout
            print("Testing RTSP stream connectivity...")
            start_time = time.time()
            test_frame = None
            
            # Give it up to 3 seconds to get first frame
            while time.time() - start_time < 3.0:
                ret, test_frame = self.cap.read()
                if ret and test_frame is not None:
                    print(f"✅ RTSP first frame received! Frame: {test_frame.shape}")
                    break
                time.sleep(0.1)  # Brief wait between attempts
                
            if test_frame is None:
                print("⚠️ RTSP stream connected but no initial frames - starting capture loop anyway...")
            
            self.is_running = True
            self.capture_thread = threading.Thread(target=self._rtsp_capture_loop_robust, daemon=True)
            self.capture_thread.start()
            
            return True
        except Exception as e:
            print(f"Failed to start RTSP camera: {e}")
            if self.cap:
                self.cap.release()
                self.cap = None
            return False
            
    def stop(self):
        """Stop the camera capture"""
        self.is_running = False
        
        # Give threads time to exit gracefully
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)  # Increased timeout
            if self.capture_thread.is_alive():
                print("⚠️ Warning: Camera thread didn't exit cleanly")
            self.capture_thread = None
            
        # Clean up camera resources
        if self.cap:
            try:
                self.cap.release()
                # Force garbage collection to help clean up semaphores
                import gc
                gc.collect()
            except Exception as e:
                print(f"Error releasing camera: {e}")
            finally:
                self.cap = None
            
        # Clean up Unitree client
        if self.unitree_client:
            try:
                self.unitree_client.disconnect()
            except Exception as e:
                print(f"Error disconnecting Unitree client: {e}")
            finally:
                self.unitree_client = None
                
        # Clear current frame to release memory
        with self.frame_lock:
            self.current_frame = None
            
    def _reconnect_rtsp(self) -> bool:
        """Attempt to reconnect to RTSP stream"""
        try:
            print("🔄 Attempting RTSP reconnection...")
            
            # Clean up old connection
            if self.cap:
                self.cap.release()
                self.cap = None
            
            # Brief delay before reconnecting
            time.sleep(1)
            
            # Create new connection
            self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            
            # Apply optimized settings
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FPS, 15)
            
            if self.cap.isOpened():
                print("✅ RTSP reconnection successful")
                return True
            else:
                print("❌ RTSP reconnection failed")
                if self.cap:
                    self.cap.release()
                    self.cap = None
                return False
                
        except Exception as e:
            print(f"💥 RTSP reconnection error: {e}")
            if self.cap:
                self.cap.release()
                self.cap = None
            return False
            
    def cleanup(self):
        """Full cleanup method for application shutdown"""
        print("🧹 Starting camera cleanup...")
        self.stop()
        
        # Additional cleanup for semaphores and OpenCV resources
        import gc
        import time
        
        # Extra time for threads to fully exit
        time.sleep(0.2)
        
        # Force multiple garbage collection cycles
        for i in range(5):
            gc.collect()
            time.sleep(0.1)
        
        # Explicitly destroy OpenCV windows and cleanup
        try:
            cv2.destroyAllWindows()
            cv2.waitKey(1)  # Process any remaining OpenCV events
        except:
            pass
        
        # Final garbage collection
        gc.collect()
        
        print("✅ Camera cleanup completed")
            
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
        print("DEBUG: Starting Unitree capture loop...")
        
        # Start test pattern immediately as fallback
        print("DEBUG: Starting immediate test pattern fallback...")
        self.unitree_client.start_video_stream()
        print(f"DEBUG: Immediate test pattern started, streaming: {self.unitree_client.is_streaming}")
        
        # Simple frame loop - just get frames from test pattern
        try:
            while self.is_running:
                frame = self.unitree_client.get_frame()
                if frame is not None:
                    with self.frame_lock:
                        self.current_frame = frame.copy()
                time.sleep(1/30)  # 30 FPS
        except Exception as e:
            print(f"DEBUG: Frame loop error: {e}")
            
    def _rtsp_capture_loop_robust(self):
        """Robust RTSP capture loop with automatic recovery"""
        print("Starting robust RTSP capture loop...")
        consecutive_failures = 0
        max_consecutive_failures = 10
        last_frame_time = time.time()
        reconnect_threshold = 30  # Reconnect if no frames for 30 seconds
        
        try:
            while self.is_running:
                if not self.cap or not self.cap.isOpened():
                    print("📡 RTSP connection lost, attempting reconnect...")
                    if self._reconnect_rtsp():
                        consecutive_failures = 0
                        last_frame_time = time.time()
                        continue
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= max_consecutive_failures:
                            print("❌ Max reconnection attempts reached, stopping RTSP capture")
                            break
                        time.sleep(2)  # Wait before next reconnect attempt
                        continue
                
                try:
                    ret, frame = self.cap.read()
                    
                    if ret and frame is not None and frame.size > 0:
                        # Successfully got a frame
                        with self.frame_lock:
                            self.current_frame = frame.copy()
                        consecutive_failures = 0
                        last_frame_time = time.time()
                        
                    else:
                        # Failed to read frame
                        consecutive_failures += 1
                        current_time = time.time()
                        
                        # Check if we've been without frames too long
                        if current_time - last_frame_time > reconnect_threshold:
                            print(f"⚠️ No frames for {reconnect_threshold}s, triggering reconnect")
                            if self.cap:
                                self.cap.release()
                                self.cap = None
                            continue
                            
                        if self.is_running and consecutive_failures % 10 == 0:  # Log every 10 failures
                            print(f"⚠️ RTSP frame read failed ({consecutive_failures} consecutive)")
                        
                        time.sleep(0.1)  # Brief pause before retry
                        
                except cv2.error as cv_error:
                    print(f"📷 OpenCV error in RTSP capture: {cv_error}")
                    consecutive_failures += 1
                    if consecutive_failures >= 5:  # Reconnect after several OpenCV errors
                        if self.cap:
                            self.cap.release()
                            self.cap = None
                    time.sleep(0.2)
                    
                except Exception as frame_error:
                    print(f"📡 Frame capture error: {frame_error}")
                    consecutive_failures += 1
                    time.sleep(0.2)
                    
        except Exception as e:
            print(f"💥 Critical RTSP capture loop error: {e}")
        finally:
            print("🛑 RTSP capture loop ended")
            # Ensure cap is released in thread before exit
            if self.cap:
                try:
                    self.cap.release()
                    print("📷 RTSP capture released")
                except Exception as cleanup_error:
                    print(f"⚠️ Error releasing RTSP capture: {cleanup_error}")
                self.cap = None
                
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
            # Return True if unitree client exists and is streaming (includes test pattern fallback)
            return self.unitree_client is not None and self.unitree_client.is_streaming
        elif self.camera_source.startswith("rtsp"):
            return self.cap is not None and self.cap.isOpened()
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
        elif self.camera_source.startswith("rtsp"):
            status.update({
                "rtsp_url": self.rtsp_url,
                "rtsp_channel": self.camera_source,
                "opencv_available": self.cap is not None,
                "connected": self.cap is not None and self.cap.isOpened()
            })
                
        return status