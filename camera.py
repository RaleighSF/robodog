import cv2
from robot_host import robot_host
import threading
import time
import asyncio
from typing import Optional
import numpy as np
from unitree_client import UnitreeGo2Client
import os
import signal
import requests
from io import BytesIO

class CameraManager:
    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self.cap = None
        self.current_frame = None
        self.is_running = False
        self.capture_thread = None
        self.frame_lock = threading.Lock()
        
        # Camera source options - default to Mac for reliability, Color Channel auto-starts via web UI
        self.camera_source = "mac"  # "mac", "unitree", "rtsp_*", or "go2_webrtc"
        self.unitree_client = None
        self.robot_ip = "192.168.87.25"

        # RTSP URLs derive from the resolved robot host (rtsp_channels property).
        self.rtsp_url = self.rtsp_channels["rtsp_color"]  # Default to color

        # go2_service_url is a property resolved per access.
        self.go2_stream_active = False
        self.http_stream_active = False
        
    # ---- robot address, resolved at access time -------------------------------
    @property
    def rtsp_channels(self):
        return {f"rtsp_{c}": robot_host.rtsp_url(c) for c in ("color", "ir", "depth", "test")}

    @property
    def go2_service_url(self):
        return robot_host.service_url()

    def set_camera_source(self, source: str, robot_ip: str = None, rtsp_url: str = None):
        """Set camera source: 'mac', 'unitree', 'rtsp_*', or 'go2_webrtc' with robust cleanup"""
        valid_sources = ["mac", "unitree", "go2_webrtc"] + list(self.rtsp_channels.keys())
        if source in valid_sources:
            print(f"🔄 Camera source change: {self.camera_source} -> {source}")
            
            # Always stop completely first - don't auto-restart
            if self.is_running:
                print("⏹️ Stopping current camera for source switch")
                self.stop()
                
                # Extra time for complete cleanup
                import time
                time.sleep(0.1)
                
            # Clean up any existing resources before switching
            self._cleanup_current_source()
                
            # Update source configuration
            old_source = self.camera_source
            self.camera_source = source
            
            if robot_ip:
                self.robot_ip = robot_ip
            
            # Handle RTSP channel selection
            if source.startswith("rtsp_"):
                if source in self.rtsp_channels:
                    self.rtsp_url = self.rtsp_channels[source]
                    print(f"📡 RTSP channel selected: {source} -> {self.rtsp_url}")
                elif rtsp_url:
                    self.rtsp_url = rtsp_url
                    print(f"📡 Custom RTSP URL: {rtsp_url}")
            elif rtsp_url:
                self.rtsp_url = rtsp_url
                
            # Set up new source-specific resources
            if source == "unitree":
                try:
                    print(f"🤖 Creating Unitree client for {self.robot_ip}")
                    self.unitree_client = UnitreeGo2Client(self.robot_ip, serial_number="B42D4000P6PC04GE")
                    print(f"✅ Unitree client created successfully")
                except Exception as e:
                    print(f"❌ Failed to create Unitree client: {e}")
                    # Don't fail the whole switch, just log the error
            
            print(f"✅ Camera source switched: {old_source} -> {source}")
            
        else:
            raise ValueError(f"Invalid camera source: {source}. Valid sources: {valid_sources}")
            
    def _cleanup_current_source(self):
        """Clean up resources for the current camera source"""
        try:
            # Clean up Unitree client if exists
            if self.unitree_client:
                print("🧹 Cleaning up Unitree client")
                self.unitree_client.disconnect()
                self.unitree_client = None
                
            # Clean up OpenCV capture if exists  
            if self.cap:
                print("🧹 Cleaning up OpenCV capture")
                self.cap.release()
                self.cap = None
                
            # Clear current frame
            with self.frame_lock:
                self.current_frame = None

        except Exception as e:
            print(f"⚠️ Error during source cleanup: {e}")
                
    def start(self) -> bool:
        """Start the camera capture"""
        if self.camera_source == "mac":
            return self._start_mac_camera()
        elif self.camera_source == "unitree":
            return self._start_unitree_camera()
        elif self.camera_source == "go2_webrtc":
            return self._start_go2_webrtc_camera()
        elif self.camera_source.startswith("rtsp"):
            return self._start_rtsp_camera()
        else:
            print(f"Unknown camera source: {self.camera_source}")
            return False
            
    def _start_mac_camera(self) -> bool:
        """Start Mac camera capture"""
        try:
            print("🎥 DEBUG: Starting Mac camera initialization...")
            # Try different camera indices if default fails
            for cam_idx in [0, 1, 2]:
                print(f"🎥 DEBUG: Trying camera index {cam_idx}...")
                self.cap = cv2.VideoCapture(cam_idx)
                print(f"🎥 DEBUG: cv2.VideoCapture({cam_idx}) created")

                if self.cap.isOpened():
                    print(f"🎥 DEBUG: Camera {cam_idx} isOpened() = True, testing frame read...")
                    # Test if we can actually read a frame
                    ret, test_frame = self.cap.read()
                    print(f"🎥 DEBUG: Frame read result: ret={ret}, frame shape={test_frame.shape if test_frame is not None else None}")
                    if ret and test_frame is not None:
                        print(f"✅ Camera {cam_idx} working!")
                        break
                    else:
                        print(f"❌ Camera {cam_idx} opened but frame read failed")
                        self.cap.release()
                        continue
                else:
                    print(f"❌ Camera {cam_idx} isOpened() = False")
                    if self.cap:
                        self.cap.release()
                    continue
            else:
                raise Exception("No working camera found. Please check camera permissions in System Preferences > Security & Privacy > Camera")

            print("🎥 DEBUG: Setting camera properties...")
            # Set camera properties for better performance on Mac
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 30)

            print("🎥 DEBUG: Starting capture thread...")
            self.is_running = True
            self.capture_thread = threading.Thread(target=self._mac_capture_loop, daemon=True)
            self.capture_thread.start()

            print("✅ Mac camera started successfully!")
            return True
        except Exception as e:
            print(f"❌ Failed to start Mac camera: {e}")
            import traceback
            traceback.print_exc()
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

    def _start_go2_webrtc_camera(self) -> bool:
        """Start GO2 WebRTC camera capture from service"""
        try:
            print(f"Starting GO2 WebRTC camera from service at {self.go2_service_url}...")

            # Test service connectivity
            try:
                response = requests.get(f"{self.go2_service_url}/status", timeout=2)
                if response.status_code == 200:
                    print("GO2 service is accessible")
                else:
                    print(f"GO2 service returned status {response.status_code}")
                    return False
            except requests.exceptions.RequestException as e:
                print(f"Failed to connect to GO2 service: {e}")
                return False

            # Start capture thread
            self.is_running = True
            self.go2_stream_active = True
            self.capture_thread = threading.Thread(target=self._go2_webrtc_capture_loop, daemon=True)
            self.capture_thread.start()

            print("GO2 WebRTC camera started successfully")
            return True
        except Exception as e:
            print(f"Failed to start GO2 WebRTC camera: {e}")
            return False
            
    def _start_rtsp_camera(self) -> bool:
        """Start RTSP camera capture from Jetson with robust connection handling"""
        try:
            if self.camera_source in self.rtsp_channels:
                self.rtsp_url = self.rtsp_channels[self.camera_source]   # re-resolve host
            print(f"Starting RTSP camera from {self.rtsp_url}...")

            if self.rtsp_url.startswith(('http://', 'https://')):
                return self._start_http_mjpeg_stream(self.rtsp_url)

            # Set OpenCV environment variable for shorter RTSP timeout (5 seconds instead of 30)
            os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|stimeout;5000000'

            # Connect to RTSP stream with retry logic
            print(f"Attempting RTSP connection to: {self.rtsp_url}")

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    print(f"📡 DEBUG: Creating cv2.VideoCapture for RTSP (attempt {attempt+1})...")
                    self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                    print(f"📡 DEBUG: cv2.VideoCapture created (attempt {attempt+1})")
                    
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
        """Stop the camera capture with proper cleanup ordering"""
        print("🛑 DEBUG: stop() called")
        self.is_running = False

        # Wait for capture thread to exit BEFORE releasing resources
        if self.capture_thread:
            print(f"🛑 DEBUG: Waiting for capture thread to exit (timeout=2s)...")
            self.capture_thread.join(timeout=2.0)
            if self.capture_thread.is_alive():
                print("⚠️ Warning: Camera thread didn't exit cleanly")
            else:
                print("✅ DEBUG: Capture thread exited cleanly")
            self.capture_thread = None

        # Now release camera after thread is done
        if self.cap:
            print("🛑 DEBUG: Releasing camera capture...")
            try:
                self.cap.release()
                print("🛑 DEBUG: Camera released")
                cv2.destroyAllWindows()
            except Exception as e:
                print(f"⚠️ Error releasing camera: {e}")
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

        # Explicitly destroy OpenCV windows and cleanup
        try:
            cv2.destroyAllWindows()
            cv2.waitKey(1)  # Process any remaining OpenCV events
        except:
            pass

        print("✅ Camera cleanup completed")
            
    def _mac_capture_loop(self):
        """Internal capture loop for Mac camera running in separate thread"""
        while self.is_running and self.cap:
            ret, frame = self.cap.read()
            if ret:
                with self.frame_lock:
                    self.current_frame = frame
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
                        self.current_frame = frame
                time.sleep(1/30)  # 30 FPS
        except Exception as e:
            print(f"DEBUG: Frame loop error: {e}")

    def _go2_webrtc_capture_loop(self):
        """Optimized capture loop for GO2 WebRTC camera from service with auto-reconnect"""
        video_url = f"{self.go2_service_url}/video_feed"
        frame_count = 0
        reconnect_delay = 3  # seconds between reconnect attempts

        print(f"[GO2 Capture] Starting capture from {video_url}")

        while self.is_running and self.go2_stream_active:
            consecutive_failures = 0
            max_consecutive_failures = 15
            bytes_buffer = bytearray()
            response = None
            try:
                # Open streaming connection with optimized chunk size
                response = requests.get(video_url, stream=True, timeout=(5, 15))
                print(f"[GO2 Capture] Connected, status code: {response.status_code}")

                if response.status_code != 200:
                    print(f"[GO2 Capture] Bad status code {response.status_code}, retrying in {reconnect_delay}s")
                    time.sleep(reconnect_delay)
                    continue

                # Parse MJPEG stream with larger chunks for better performance
                chunk_count = 0
                for chunk in response.iter_content(chunk_size=16384):  # 16KB chunks
                    if not self.is_running or not self.go2_stream_active:
                        print(f"[GO2 Capture] Stopping: is_running={self.is_running}, stream_active={self.go2_stream_active}")
                        return

                    bytes_buffer.extend(chunk)
                    chunk_count += 1

                    if chunk_count <= 5 or chunk_count % 100 == 0:
                        print(f"[GO2 Capture] Chunk {chunk_count}: size={len(chunk)}, buffer={len(bytes_buffer)} bytes")

                    # Look for JPEG boundaries
                    start = bytes_buffer.find(b'\xff\xd8')
                    end = bytes_buffer.find(b'\xff\xd9')

                    if chunk_count <= 5:
                        print(f"[GO2 Capture] JPEG markers: start={start}, end={end}")

                    if start != -1 and end != -1 and end > start:
                        jpg = bytes_buffer[start:end+2]
                        bytes_buffer = bytes_buffer[end+2:]

                        try:
                            # Decode JPEG directly to frame (no intermediate array)
                            frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)

                            if frame is not None:
                                with self.frame_lock:
                                    self.current_frame = frame  # No copy needed - frame is already new
                                consecutive_failures = 0
                                frame_count += 1
                                if frame_count == 1 or frame_count % 100 == 0:
                                    print(f"[GO2 Capture] Captured {frame_count} frames")
                            else:
                                consecutive_failures += 1
                                if consecutive_failures <= 5:
                                    print(f"[GO2 Capture] Frame decode returned None (failures: {consecutive_failures})")

                        except Exception as e:
                            consecutive_failures += 1
                            if consecutive_failures <= 5:
                                print(f"[GO2 Capture] Frame decode exception: {e}")

                        if consecutive_failures >= max_consecutive_failures:
                            print(f"[GO2 Capture] Too many consecutive failures ({consecutive_failures}), reconnecting...")
                            break

                    # Keep buffer size reasonable to avoid memory growth
                    if len(bytes_buffer) > 500000:  # 500KB max buffer
                        bytes_buffer = bytes_buffer[-250000:]  # Keep last 250KB

                # Stream ended normally (server closed) — reconnect
                print(f"[GO2 Capture] Stream ended, reconnecting in {reconnect_delay}s...")

            except Exception as e:
                print(f"[GO2 Capture] Connection error: {e}, reconnecting in {reconnect_delay}s...")
            finally:
                if response:
                    try:
                        response.close()
                    except Exception:
                        pass

            # Wait before reconnect attempt
            if self.is_running and self.go2_stream_active:
                time.sleep(reconnect_delay)

        print(f"[GO2 Capture] Exiting - captured {frame_count} total frames")
        self.go2_stream_active = False

    def _start_http_mjpeg_stream(self, video_url: str) -> bool:
        """Start a generic HTTP MJPEG stream (e.g., IR/depth proxies)."""
        try:
            print(f"Starting HTTP MJPEG stream from {video_url}...")

            try:
                response = requests.get(video_url, stream=True, timeout=5)
                status = response.status_code
            except requests.exceptions.RequestException as exc:
                print(f"Failed to connect to HTTP MJPEG stream: {exc}")
                return False
            finally:
                try:
                    response.close()
                except Exception:
                    pass

            if status != 200:
                print(f"HTTP MJPEG stream returned status {status}")
                return False

            self.is_running = True
            self.http_stream_active = True
            self.capture_thread = threading.Thread(
                target=self._http_mjpeg_capture_loop,
                args=(video_url,),
                daemon=True
            )
            self.capture_thread.start()
            print("HTTP MJPEG stream started successfully")
            return True
        except Exception as e:
            print(f"Failed to start HTTP MJPEG stream: {e}")
            self.http_stream_active = False
            return False

    def _http_mjpeg_capture_loop(self, video_url: str):
        """Capture loop for generic HTTP MJPEG sources."""
        consecutive_failures = 0
        max_consecutive_failures = 20
        buffer = bytearray()
        response = None

        try:
            response = requests.get(video_url, stream=True, timeout=(5, None))
            if response.status_code != 200:
                print(f"HTTP MJPEG stream returned status {response.status_code}")
                self.http_stream_active = False
                return

            for chunk in response.iter_content(chunk_size=8192):
                if not self.is_running or not self.http_stream_active:
                    break

                buffer.extend(chunk)
                start = buffer.find(b"\xff\xd8")
                end = buffer.find(b"\xff\xd9")

                if start != -1 and end != -1 and end > start:
                    jpg = buffer[start:end + 2]
                    buffer = buffer[end + 2:]
                    try:
                        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            with self.frame_lock:
                                self.current_frame = frame
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                    except Exception:
                        consecutive_failures += 1

                    if consecutive_failures >= max_consecutive_failures:
                        print("Too many MJPEG decode failures; stopping stream")
                        break

                if len(buffer) > 200000:
                    buffer = buffer[-100000:]

        except requests.exceptions.RequestException as e:
            print(f"HTTP MJPEG request error: {e}")
        finally:
            if response:
                try:
                    response.close()
                except Exception:
                    pass
            self.http_stream_active = False
            
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
                            self.current_frame = frame
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
        elif self.camera_source == "go2_webrtc":
            return self.go2_stream_active
        elif self.camera_source.startswith("rtsp"):
            if self.rtsp_url.startswith(("http://", "https://")):
                return self.http_stream_active
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
        elif self.camera_source == "go2_webrtc":
            status.update({
                "go2_service_url": self.go2_service_url,
                "stream_active": self.go2_stream_active,
                "connected": self.go2_stream_active
            })
        elif self.camera_source.startswith("rtsp"):
            connected = self.http_stream_active if self.rtsp_url.startswith(("http://", "https://")) else (self.cap is not None and self.cap.isOpened())
            status.update({
                "rtsp_url": self.rtsp_url,
                "rtsp_channel": self.camera_source,
                "opencv_available": self.cap is not None,
                "connected": connected
            })

        return status
