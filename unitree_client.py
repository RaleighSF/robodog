import asyncio
import cv2
import numpy as np
import threading
import time
import requests
from typing import Optional, Callable
import logging
import janus

try:
    from go2_webrtc_driver.webrtc_driver import Go2WebRTCConnection, WebRTCConnectionMethod
    GO2_AVAILABLE = True
except ImportError:
    GO2_AVAILABLE = False
    # WebRTC functionality disabled - using RTSP and direct camera feeds instead

class UnitreeGo2Client:
    def __init__(self, robot_ip: str = "192.168.87.25", serial_number: str = "B42D4000P6PC04GE"):
        self.robot_ip = robot_ip
        self.serial_number = serial_number  # Default to your robot's serial
        self.connection = None
        self.is_connected = False
        self.is_streaming = False
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.video_thread = None
        self.frame_callback = None
        
        # Connection parameters
        self.connection_method = WebRTCConnectionMethod.LocalAP if GO2_AVAILABLE else None
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # Thread-safe frame queue for async to sync bridging
        self.frame_queue = None
        self.video_consume_task = None
        self.async_loop = None
        
    def discover_robot(self) -> dict:
        """Attempt to discover robot information via HTTP"""
        try:
            # Try to get robot info from web interface
            response = requests.get(f"http://{self.robot_ip}", timeout=5)
            if response.status_code == 200:
                self.logger.info(f"Robot web interface accessible at {self.robot_ip}")
                return {"status": "accessible", "ip": self.robot_ip}
        except Exception as e:
            self.logger.error(f"Failed to connect to robot web interface: {e}")
            
        try:
            # Try to ping the robot
            import subprocess
            result = subprocess.run(['ping', '-c', '1', self.robot_ip], 
                                  capture_output=True, timeout=5)
            if result.returncode == 0:
                return {"status": "pingable", "ip": self.robot_ip}
        except Exception as e:
            self.logger.error(f"Failed to ping robot: {e}")
            
        return {"status": "unreachable", "ip": self.robot_ip}
        
    async def connect(self, serial_number: Optional[str] = None) -> bool:
        """Connect to Unitree Go2 robot via WebRTC with multiple connection methods"""
        if not GO2_AVAILABLE:
            self.logger.error("go2-webrtc-connect library not available")
            return False
            
        # Use provided serial number or default
        robot_serial = serial_number or self.serial_number
        self.logger.info(f"Connecting to robot with serial: {robot_serial}")
            
        # Try multiple connection methods in order of preference  
        # For WiFi mode (STA), prioritize IP-based connection
        connection_methods = [
            ("LocalSTA_IP", lambda: Go2WebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=self.robot_ip)),
            ("LocalSTA_Serial", lambda: Go2WebRTCConnection(WebRTCConnectionMethod.LocalSTA, serialNumber=robot_serial)),
            ("LocalAP", lambda: Go2WebRTCConnection(WebRTCConnectionMethod.LocalAP)),  # Fallback to AP mode
        ]
        
        # Add remote connection as fallback (requires credentials)
        if robot_serial:
            connection_methods.append(
                ("Remote_NoAuth", lambda: Go2WebRTCConnection(WebRTCConnectionMethod.Remote, serialNumber=robot_serial))
            )
        
        for method_name, connection_factory in connection_methods:
            try:
                self.logger.info(f"Attempting WebRTC connection using {method_name} method...")
                
                # Create the WebRTC connection
                self.connection = connection_factory()
                self.logger.info(f"WebRTC connection object created with {method_name}")
                
                # Try to establish the actual connection
                if hasattr(self.connection, 'connect'):
                    self.logger.info("Calling connection.connect()...")
                    result = await self.connection.connect()
                    self.logger.info(f"Connect result: {result}")
                
                # Give it time to establish
                self.logger.info("Waiting for connection establishment...")
                for i in range(10):  # 5 second timeout
                    await asyncio.sleep(0.5)
                    if hasattr(self.connection, 'isConnected') and self.connection.isConnected:
                        self.logger.info(f"WebRTC connected with {method_name} after {i*0.5:.1f}s!")
                        self.is_connected = True
                        return True
                    self.logger.debug(f"Connection attempt {i+1}/10...")
                
                # Check final connection state
                if hasattr(self.connection, 'isConnected') and self.connection.isConnected:
                    self.is_connected = True
                    self.logger.info(f"Final connection state: Connected via {method_name}")
                    return True
                else:
                    self.logger.warning(f"{method_name} connection failed, trying next method...")
                    
            except Exception as e:
                self.logger.error(f"WebRTC connection error with {method_name}: {e}")
                continue
        
        # All methods failed
        self.logger.error("All WebRTC connection methods failed")
        self.is_connected = False
        return False
            
    def start_video_stream(self, frame_callback: Optional[Callable] = None):
        """Start receiving video stream from robot"""
        self.frame_callback = frame_callback
        self.is_streaming = True
        
        # Update connection status before starting video
        if self.connection and hasattr(self.connection, 'isConnected'):
            self.is_connected = self.connection.isConnected
        elif self.connection:
            self.is_connected = True
        
        self.logger.info(f"Starting video stream - Connected: {self.is_connected}, Connection obj: {self.connection is not None}")
        
        if self.is_connected and self.connection and GO2_AVAILABLE:
            self.logger.info("Starting WebRTC video stream (connected)...")
            self.video_thread = threading.Thread(target=self._webrtc_stream_loop, daemon=True)
            self.video_thread.start()
            return True
        else:
            self.logger.info(f"WebRTC not connected - Connected: {self.is_connected}, Connection: {self.connection is not None}, GO2: {GO2_AVAILABLE}")
            # Fallback to test pattern
            self.video_thread = threading.Thread(target=self._generate_test_pattern, daemon=True)
            self.video_thread.start()
            return True
            
    def _webrtc_stream_loop(self):
        """WebRTC video streaming loop"""
        try:
            self.logger.info("Waiting for WebRTC connection to establish...")
            
            # Wait for the connection to establish and get peer connection
            max_wait = 10  # seconds
            wait_time = 0
            while wait_time < max_wait and (not self.connection.pc or not self.connection.isConnected):
                time.sleep(0.5)
                wait_time += 0.5
                
            if self.connection.pc and self.connection.isConnected:
                self.logger.info("WebRTC connection established, checking for video tracks...")
                
                # Check what's available in the peer connection
                self.logger.info(f"PeerConnection attributes: {[attr for attr in dir(self.connection.pc) if not attr.startswith('_')]}")
                
                # Try to get receivers (video tracks)
                try:
                    if hasattr(self.connection.pc, 'getReceivers'):
                        receivers = self.connection.pc.getReceivers()
                        self.logger.info(f"Found {len(receivers)} receivers")
                        for i, receiver in enumerate(receivers):
                            if receiver.track:
                                self.logger.info(f"Receiver {i}: track={receiver.track.kind}, id={receiver.track.id}")
                    
                    # Check for transceivers
                    if hasattr(self.connection.pc, 'getTransceivers'):
                        transceivers = self.connection.pc.getTransceivers()
                        self.logger.info(f"Found {len(transceivers)} transceivers")
                        for i, transceiver in enumerate(transceivers):
                            if transceiver.receiver and transceiver.receiver.track:
                                track = transceiver.receiver.track
                                self.logger.info(f"Transceiver {i}: {track.kind} track, id={track.id}")
                
                except Exception as e:
                    self.logger.error(f"Error checking video tracks: {e}")
                
                # We found video transceivers! Let's try to register a frame callback
                video_track = None
                for i, transceiver in enumerate(transceivers):
                    if (transceiver.receiver and transceiver.receiver.track 
                        and transceiver.receiver.track.kind == 'video'):
                        video_track = transceiver.receiver.track
                        self.logger.info(f"Found video track {i} for frame callback registration")
                        break
                
                if video_track:
                    self.logger.info("Attempting alternative video frame access methods...")
                    try:
                        # Try to access video frames through the connection object instead of track
                        self._try_connection_based_video_access()
                    except Exception as e:
                        self.logger.error(f"Failed to start video access: {e}")
                        self._generate_enhanced_test_pattern_with_track_info(video_track)
                else:
                    # Check for data channel video access as fallback
                    if hasattr(self.connection, 'dataChannel'):
                        data_channel = self.connection.dataChannel
                        self.logger.info(f"Found data channel: {type(data_channel)}")
                        
                        if hasattr(data_channel, 'switchVideoChannel'):
                            self.logger.info("Data channel supports video switching")
                            try:
                                data_channel.switchVideoChannel()
                                self.logger.info("Switched to video channel")
                            except Exception as e:
                                self.logger.error(f"Error switching video channel: {e}")
                    
                    self.logger.info("Showing enhanced test pattern with video track info")
                    self._generate_enhanced_test_pattern()
                
            else:
                self.logger.warning("WebRTC connection not established, using test pattern")
                self._generate_test_pattern()
                
        except Exception as e:
            self.logger.error(f"WebRTC video stream error: {e}")
            self._generate_test_pattern()
            
    def _http_stream_loop(self):
        """Fallback HTTP stream attempt"""
        try:
            # Try common HTTP streaming endpoints
            stream_urls = [
                f"http://{self.robot_ip}:8080/video",
                f"http://{self.robot_ip}:8080/stream",
                f"http://{self.robot_ip}/video",
                f"http://{self.robot_ip}/stream",
            ]
            
            for url in stream_urls:
                try:
                    self.logger.info(f"Attempting HTTP stream: {url}")
                    cap = cv2.VideoCapture(url)
                    
                    if cap.isOpened():
                        self.logger.info(f"HTTP stream connected: {url}")
                        
                        while self.is_streaming:
                            ret, frame = cap.read()
                            if ret:
                                with self.frame_lock:
                                    self.current_frame = frame.copy()
                                
                                if self.frame_callback:
                                    self.frame_callback(frame)
                            else:
                                time.sleep(0.1)
                                
                        cap.release()
                        return
                        
                except Exception as e:
                    self.logger.warning(f"HTTP stream {url} failed: {e}")
                    continue
                    
            # If no HTTP streams work, generate test pattern
            self._generate_test_pattern()
            
        except Exception as e:
            self.logger.error(f"HTTP stream error: {e}")
            
    def _generate_test_pattern(self):
        """Generate a test pattern when no real video is available"""
        self.logger.info("Generating test pattern - no WebRTC connection")
        
        frame_count = 0
        while self.is_streaming:
            # Create test pattern
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            
            # Add some animation
            color = int((frame_count % 60) * 255 / 60)
            cv2.rectangle(frame, (50, 50), (590, 430), (color, 100, 200), 2)
            cv2.putText(frame, f"Unitree Go2 - No Connection", (120, 240), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.putText(frame, f"Frame: {frame_count}", (150, 280), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            with self.frame_lock:
                self.current_frame = frame.copy()
                
            if self.frame_callback:
                self.frame_callback(frame)
                
            frame_count += 1
            time.sleep(1/15)  # 15 FPS for test pattern

    def _generate_robot_test_pattern(self):
        """Generate test pattern when WebRTC is connected but video not working"""
        self.logger.info("Generating test pattern - WebRTC connected, working on video extraction")
        
        frame_count = 0
        while self.is_streaming:
            # Create test pattern showing WebRTC connection status
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            
            # Add green elements to show connection is working
            color = int(abs(np.sin(frame_count * 0.1)) * 255)
            cv2.rectangle(frame, (50, 50), (590, 430), (0, color, 0), 3)
            cv2.putText(frame, f"Unitree Go2 - WebRTC Connected", (80, 220), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(frame, f"Working on video stream...", (130, 260), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"Frame: {frame_count}", (150, 300), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            with self.frame_lock:
                self.current_frame = frame.copy()
                
            if self.frame_callback:
                self.frame_callback(frame)
                
            frame_count += 1
            time.sleep(1/15)  # 15 FPS for test pattern

    def _process_video_data(self, frame_data):
        """Process video data from WebRTC callback"""
        try:
            self.logger.info(f"Processing video data: {type(frame_data)}")
            
            # Try to convert the frame data to numpy array
            if hasattr(frame_data, 'to_ndarray'):
                img = frame_data.to_ndarray(format='bgr24')
                self.logger.info(f"SUCCESS! Video callback frame converted: {img.shape}")
                
                with self.frame_lock:
                    self.current_frame = img.copy()
                
                if self.frame_callback:
                    self.frame_callback(img)
            else:
                self.logger.info(f"Frame data type {type(frame_data)} - checking for other formats")
                # Log attributes to understand the data format
                if hasattr(frame_data, '__dict__'):
                    self.logger.info(f"Frame data attributes: {list(frame_data.__dict__.keys())}")
                
        except Exception as e:
            self.logger.error(f"Error processing video data: {e}")

    def _try_connection_based_video_access(self):
        """Try to access video frames through the Go2WebRTCConnection object"""
        try:
            self.logger.info("Exploring Go2WebRTCConnection for built-in video methods...")
            
            # Log all available methods and attributes
            connection_attrs = [attr for attr in dir(self.connection) if not attr.startswith('_')]
            self.logger.info(f"Go2WebRTCConnection attributes: {connection_attrs}")
            
            # Check for video-related methods
            video_methods = [attr for attr in connection_attrs if 'video' in attr.lower()]
            if video_methods:
                self.logger.info(f"Found video-related methods: {video_methods}")
            
            frame_methods = [attr for attr in connection_attrs if 'frame' in attr.lower()]
            if frame_methods:
                self.logger.info(f"Found frame-related methods: {frame_methods}")
                
            stream_methods = [attr for attr in connection_attrs if 'stream' in attr.lower()]
            if stream_methods:
                self.logger.info(f"Found stream-related methods: {stream_methods}")
            
            # Try the discovered video attribute first
            if hasattr(self.connection, 'video'):
                self.logger.info("Found 'video' attribute - exploring video object")
                video_obj = self.connection.video
                self.logger.info(f"Video object type: {type(video_obj)}")
                
                if video_obj:
                    video_attrs = [attr for attr in dir(video_obj) if not attr.startswith('_')]
                    self.logger.info(f"Video object attributes: {video_attrs}")
                    
                    # Try the discovered WebRTCVideoChannel methods
                    if hasattr(video_obj, 'add_track_callback'):
                        self.logger.info("Found add_track_callback - setting up video track callback")
                        self._setup_webrtc_video_callback(video_obj)
                        return
                    elif hasattr(video_obj, 'track_handler'):
                        self.logger.info("Found track_handler - exploring track handler")
                        self._try_track_handler_access(video_obj)
                        return
                    elif hasattr(video_obj, 'switchVideoChannel'):
                        self.logger.info("Found switchVideoChannel - trying to switch video channel")
                        try:
                            video_obj.switchVideoChannel()
                            self.logger.info("Video channel switched successfully")
                            # Try callbacks after switching
                            if hasattr(video_obj, 'add_track_callback'):
                                self._setup_webrtc_video_callback(video_obj)
                                return
                        except Exception as e:
                            self.logger.error(f"Error switching video channel: {e}")
                    
                    # Try common video object methods
                    if hasattr(video_obj, 'get_frame') or hasattr(video_obj, 'getFrame'):
                        self.logger.info("Found frame getter on video object - starting video capture")
                        self._start_video_object_capture(video_obj)
                        return
                    elif hasattr(video_obj, 'frames') or hasattr(video_obj, 'frame_buffer'):
                        self.logger.info("Found frame buffer on video object")
                        self._start_video_buffer_monitoring(video_obj)
                        return
                    elif hasattr(video_obj, 'callback') or hasattr(video_obj, 'on_frame'):
                        self.logger.info("Found callback mechanism on video object")
                        self._setup_video_object_callback(video_obj)
                        return
                    elif hasattr(video_obj, 'track'):
                        self.logger.info("Found track on video object")
                        track = video_obj.track
                        self._try_track_properties_access(track)
                        return
                    else:
                        self.logger.info("Video object found but no obvious frame access method")
                        self._try_video_object_exploration(video_obj)
                        return
                
            # Try some other common video access patterns
            if hasattr(self.connection, 'addVideoCallback'):
                self.logger.info("Found addVideoCallback - setting up video callback")
                self.connection.addVideoCallback(self._on_connection_video_frame)
                self._start_simple_frame_monitoring()
                return
                
            # Try accessing the peer connection's video handling
            if hasattr(self.connection, 'pc') and self.connection.pc:
                self._try_peer_connection_video_access()
                return
                
            self.logger.warning("No suitable video access method found in connection")
            self._generate_enhanced_test_pattern()
            
        except Exception as e:
            self.logger.error(f"Error in connection-based video access: {e}")
            import traceback
            traceback.print_exc()
            self._generate_enhanced_test_pattern()

    def _try_receiver_access(self, video_receiver):
        """Try to access video through receiver object"""
        try:
            self.logger.info(f"Video receiver attributes: {[attr for attr in dir(video_receiver) if not attr.startswith('_')]}")
            
            # Try to set up callback on receiver
            if hasattr(video_receiver, 'setCallback'):
                video_receiver.setCallback(self._on_connection_video_frame)
                self.logger.info("Set callback on video receiver")
                self._start_simple_frame_monitoring()
            elif hasattr(video_receiver, 'on_frame'):
                video_receiver.on_frame = self._on_connection_video_frame
                self.logger.info("Set on_frame handler on video receiver")
                self._start_simple_frame_monitoring()
            else:
                self.logger.info("No callback mechanism found on video receiver")
                self._generate_enhanced_test_pattern()
                
        except Exception as e:
            self.logger.error(f"Error accessing video receiver: {e}")
            self._generate_enhanced_test_pattern()

    def _try_peer_connection_video_access(self):
        """Try to access video through peer connection"""
        try:
            pc = self.connection.pc
            self.logger.info(f"Peer connection attributes: {[attr for attr in dir(pc) if not attr.startswith('_')]}")
            
            # Try to set up track event handlers
            if hasattr(pc, 'on'):
                self.logger.info("Setting up peer connection track event handler")
                def on_track(track):
                    self.logger.info(f"Track event: {track.kind}")
                    if track.kind == 'video':
                        self.logger.info("Setting up video track handler")
                        # Try to access track without recv()
                        self._try_track_properties_access(track)
                
                pc.on('track', on_track)
                self._start_simple_frame_monitoring()
            else:
                self.logger.info("No track event handler available")
                self._generate_enhanced_test_pattern()
                
        except Exception as e:
            self.logger.error(f"Error accessing peer connection: {e}")
            self._generate_enhanced_test_pattern()

    def _try_track_properties_access(self, track):
        """Try to access track data without using recv()"""
        try:
            self.logger.info(f"Track properties: {[attr for attr in dir(track) if not attr.startswith('_')]}")
            
            # Look for any frame buffer or data properties
            if hasattr(track, 'frame_buffer'):
                self.logger.info("Found frame_buffer property")
            if hasattr(track, 'latest_frame'):
                self.logger.info("Found latest_frame property")
            if hasattr(track, 'current_frame'):
                self.logger.info("Found current_frame property")
                
        except Exception as e:
            self.logger.error(f"Error accessing track properties: {e}")

    def _start_direct_connection_frame_access(self):
        """Start accessing frames directly from connection"""
        def frame_access_loop():
            self.logger.info("Starting direct connection frame access loop")
            frame_count = 0
            
            while self.is_streaming:
                try:
                    frame = None
                    if hasattr(self.connection, 'getFrame'):
                        frame = self.connection.getFrame()
                    elif hasattr(self.connection, 'get_frame'):
                        frame = self.connection.get_frame()
                    
                    if frame:
                        self.logger.info(f"Got frame {frame_count} from connection")
                        self._process_video_data(frame)
                        frame_count += 1
                    
                    time.sleep(1/30)  # 30 FPS
                    
                except Exception as e:
                    self.logger.error(f"Error in direct frame access: {e}")
                    time.sleep(0.1)
                    
        threading.Thread(target=frame_access_loop, daemon=True).start()

    def _start_simple_frame_monitoring(self):
        """Start simple monitoring for frames"""
        def monitor():
            self.logger.info("Starting simple frame monitoring...")
            while self.is_streaming:
                time.sleep(1)
                self.logger.info("Monitoring for video frames...")
                
        threading.Thread(target=monitor, daemon=True).start()
        # Show enhanced pattern while monitoring
        self._generate_enhanced_test_pattern()

    def _start_video_object_capture(self, video_obj):
        """Start capturing frames from video object"""
        def capture_loop():
            self.logger.info("Starting video object capture loop")
            frame_count = 0
            
            while self.is_streaming:
                try:
                    frame = None
                    if hasattr(video_obj, 'get_frame'):
                        frame = video_obj.get_frame()
                    elif hasattr(video_obj, 'getFrame'):
                        frame = video_obj.getFrame()
                    
                    if frame:
                        self.logger.info(f"Got frame {frame_count} from video object")
                        self._process_video_data(frame)
                        frame_count += 1
                        
                        if frame_count == 1:
                            self.logger.info("SUCCESS! First real video frame captured from video object!")
                    
                    time.sleep(1/30)  # 30 FPS
                    
                except Exception as e:
                    self.logger.error(f"Error in video object capture: {e}")
                    time.sleep(0.1)
                    
        threading.Thread(target=capture_loop, daemon=True).start()

    def _start_video_buffer_monitoring(self, video_obj):
        """Monitor video buffer for frames"""
        def monitor_loop():
            self.logger.info("Starting video buffer monitoring")
            frame_count = 0
            
            while self.is_streaming:
                try:
                    frames = None
                    if hasattr(video_obj, 'frames'):
                        frames = video_obj.frames
                    elif hasattr(video_obj, 'frame_buffer'):
                        frames = video_obj.frame_buffer
                    
                    if frames and len(frames) > 0:
                        frame = frames[-1]  # Get latest frame
                        self.logger.info(f"Got frame {frame_count} from video buffer")
                        self._process_video_data(frame)
                        frame_count += 1
                        
                        if frame_count == 1:
                            self.logger.info("SUCCESS! First real video frame from buffer!")
                    
                    time.sleep(1/30)  # 30 FPS
                    
                except Exception as e:
                    self.logger.error(f"Error in video buffer monitoring: {e}")
                    time.sleep(0.1)
                    
        threading.Thread(target=monitor_loop, daemon=True).start()

    def _setup_video_object_callback(self, video_obj):
        """Set up callback on video object"""
        try:
            if hasattr(video_obj, 'callback'):
                video_obj.callback = self._on_connection_video_frame
                self.logger.info("Set callback on video object")
            elif hasattr(video_obj, 'on_frame'):
                video_obj.on_frame = self._on_connection_video_frame
                self.logger.info("Set on_frame handler on video object")
            
            self._start_simple_frame_monitoring()
            
        except Exception as e:
            self.logger.error(f"Error setting up video object callback: {e}")
            self._generate_enhanced_test_pattern()

    def _try_video_object_exploration(self, video_obj):
        """Explore video object for any usable methods"""
        try:
            self.logger.info("Exploring video object methods...")
            
            # Try to find any methods that might return frames
            callable_methods = [attr for attr in dir(video_obj) 
                              if not attr.startswith('_') and callable(getattr(video_obj, attr, None))]
            self.logger.info(f"Video object callable methods: {callable_methods}")
            
            # Try some common method names
            frame_getters = ['get', 'read', 'capture', 'recv', 'next', 'current']
            for method_name in frame_getters:
                if method_name in callable_methods:
                    self.logger.info(f"Found potential frame getter: {method_name}")
                    try:
                        method = getattr(video_obj, method_name)
                        # Test call the method
                        result = method()
                        if result:
                            self.logger.info(f"SUCCESS! Method {method_name} returned data: {type(result)}")
                            self._start_generic_video_capture(video_obj, method_name)
                            return
                    except Exception as e:
                        self.logger.debug(f"Method {method_name} failed: {e}")
            
            # If no working methods found, fall back to test pattern
            self.logger.info("No working video methods found, showing enhanced test pattern")
            self._generate_enhanced_test_pattern()
            
        except Exception as e:
            self.logger.error(f"Error exploring video object: {e}")
            self._generate_enhanced_test_pattern()

    def _start_generic_video_capture(self, video_obj, method_name):
        """Start capturing using a generic method"""
        def capture_loop():
            self.logger.info(f"Starting generic video capture using {method_name}")
            frame_count = 0
            method = getattr(video_obj, method_name)
            
            while self.is_streaming:
                try:
                    frame = method()
                    if frame:
                        self.logger.info(f"Got frame {frame_count} from {method_name}")
                        self._process_video_data(frame)
                        frame_count += 1
                        
                        if frame_count == 1:
                            self.logger.info(f"SUCCESS! First real video frame via {method_name}!")
                    
                    time.sleep(1/30)  # 30 FPS
                    
                except Exception as e:
                    self.logger.error(f"Error in generic capture {method_name}: {e}")
                    time.sleep(0.1)
                    
        threading.Thread(target=capture_loop, daemon=True).start()

    def _setup_webrtc_video_callback(self, video_obj):
        """Set up callback for WebRTCVideoChannel"""
        try:
            self.logger.info("Setting up WebRTCVideoChannel callback...")
            
            # Set up the video track callback
            video_obj.add_track_callback(self._on_webrtc_video_frame)
            self.logger.info("WebRTC video callback registered successfully!")
            
            # Also try to switch video channel to ensure it's active
            if hasattr(video_obj, 'switchVideoChannel'):
                try:
                    # Try different parameter values to activate video channel
                    for switch_param in [True, 1, "on", "video"]:
                        try:
                            video_obj.switchVideoChannel(switch_param)
                            self.logger.info(f"Video channel activated with parameter: {switch_param}")
                            break
                        except Exception as param_error:
                            self.logger.debug(f"Switch parameter {switch_param} failed: {param_error}")
                            continue
                    else:
                        self.logger.warning("Could not find working parameter for switchVideoChannel")
                except Exception as e:
                    self.logger.warning(f"Could not switch video channel: {e}")
            
            # Start monitoring for incoming frames
            self._start_webrtc_frame_monitoring()
            
        except Exception as e:
            self.logger.error(f"Error setting up WebRTC video callback: {e}")
            import traceback
            traceback.print_exc()
            self._generate_enhanced_test_pattern()

    def _try_track_handler_access(self, video_obj):
        """Try to access video through track handler"""
        try:
            self.logger.info("Exploring track_handler...")
            track_handler = video_obj.track_handler
            self.logger.info(f"Track handler type: {type(track_handler)}")
            
            if track_handler:
                handler_attrs = [attr for attr in dir(track_handler) if not attr.startswith('_')]
                self.logger.info(f"Track handler attributes: {handler_attrs}")
                
                # Try to use track handler for frame access
                if hasattr(track_handler, 'add_callback'):
                    track_handler.add_callback(self._on_webrtc_video_frame)
                    self.logger.info("Callback set on track handler")
                    self._start_webrtc_frame_monitoring()
                elif hasattr(track_handler, 'on_frame'):
                    track_handler.on_frame = self._on_webrtc_video_frame
                    self.logger.info("Frame handler set on track handler")
                    self._start_webrtc_frame_monitoring()
                else:
                    self.logger.info("No callback mechanism found on track handler")
                    self._generate_enhanced_test_pattern()
            else:
                self.logger.info("Track handler is None")
                self._generate_enhanced_test_pattern()
                
        except Exception as e:
            self.logger.error(f"Error accessing track handler: {e}")
            self._generate_enhanced_test_pattern()

    def _start_webrtc_frame_monitoring(self):
        """Start monitoring for WebRTC frames"""
        def monitor():
            self.logger.info("Starting WebRTC frame monitoring...")
            last_frame_count = getattr(self, '_frame_count', 0)
            wait_count = 0
            last_test_pattern_time = 0
            
            while self.is_streaming:
                current_frame_count = getattr(self, '_frame_count', 0)
                current_time = time.time()
                
                if current_frame_count > last_frame_count:
                    self.logger.info(f"SUCCESS! Receiving video frames! Total: {current_frame_count}")
                    last_frame_count = current_frame_count
                    wait_count = 0
                    # Stop generating test patterns when real frames are coming
                else:
                    wait_count += 1
                    if wait_count % 5 == 0:  # Every 10 seconds
                        self.logger.info(f"Still waiting for video frames... (waited {wait_count * 2}s)")
                    
                    # Only generate test pattern if no real frames for a while and not too frequently
                    if wait_count > 2 and (current_time - last_test_pattern_time) > 3:
                        self._generate_enhanced_test_pattern()
                        last_test_pattern_time = current_time
                    
                time.sleep(2)  # Check every 2 seconds
                
        threading.Thread(target=monitor, daemon=True).start()

    def _on_webrtc_video_frame(self, track):
        """Callback for WebRTC video tracks - track is a RemoteStreamTrack object"""
        try:
            # Increment frame counter
            self._frame_count = getattr(self, '_frame_count', 0) + 1
            
            if self._frame_count == 1:
                self.logger.info(f"SUCCESS! First WebRTC video frame received: {type(track)}")
                self.logger.info(f"Track kind: {track.kind}, Track ID: {track.id if hasattr(track, 'id') else 'N/A'}")
            elif self._frame_count % 30 == 0:  # Log every 30 frames
                self.logger.info(f"Processed {self._frame_count} WebRTC video frames")
            
            # Start video consumption for this track if not already started
            if not hasattr(self, '_video_consumption_started'):
                self._video_consumption_started = True
                self.logger.info("Starting video frame consumption from track...")
                self._start_video_consumption(track)
            
        except Exception as e:
            self.logger.error(f"Error processing WebRTC video track: {e}")
            import traceback
            traceback.print_exc()

    def _on_connection_video_frame(self, frame):
        """Callback for video frames from connection"""
        try:
            self.logger.info(f"Received video frame from connection: {type(frame)}")
            self._process_video_data(frame)
        except Exception as e:
            self.logger.error(f"Error processing connection video frame: {e}")

    def _start_video_consumption(self, video_track):
        """Start async video frame consumption using track.recv()"""
        try:
            self.logger.info("Setting up async video frame consumption...")
            self.logger.info(f"Video track: {video_track.kind}, id={video_track.id}")
            
            # Direct frame storage - no queue needed
            
            # Start async frame consumption in a new thread with its own event loop
            def async_thread_runner():
                try:
                    # Create new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    self.logger.info("Starting async video consumption in dedicated thread...")
                    loop.run_until_complete(self._consume_video_frames(video_track))
                    
                except Exception as e:
                    self.logger.error(f"Error in async thread: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    loop.close()
            
            # Start the async thread
            async_thread = threading.Thread(target=async_thread_runner, daemon=True)
            async_thread.start()
            self.logger.info("Async video consumption thread started")
            
        except Exception as e:
            self.logger.error(f"Error starting video consumption: {e}")
            import traceback
            traceback.print_exc()
            self._generate_enhanced_test_pattern_with_track_info(video_track)

    async def _consume_video_frames(self, video_track):
        """Async task to continuously consume video frames using track.recv()"""
        try:
            self.logger.info("Starting async video frame consumption loop...")
            frame_count = 0
            
            while self.is_streaming and not video_track.readyState == 'ended':
                try:
                    # Continuously pull frames from the WebRTC track
                    frame = await video_track.recv()
                    
                    if frame and hasattr(frame, 'to_ndarray'):
                        # Convert to numpy array in BGR format
                        np_bgr = frame.to_ndarray(format="bgr24")
                        
                        # Directly store frame - no queue needed
                        with self.frame_lock:
                            self.current_frame = np_bgr.copy()
                        
                        # Call frame callback if set
                        if self.frame_callback:
                            self.frame_callback(np_bgr)
                        
                        frame_count += 1
                        if frame_count == 1:
                            self.logger.info(f"SUCCESS! First real video frame received: {np_bgr.shape}")
                        elif frame_count % 30 == 0:  # Log every 30 frames
                            self.logger.info(f"Processed {frame_count} real video frames from robot")
                    
                except Exception as e:
                    if "event loop" not in str(e):  # Don't spam event loop errors
                        self.logger.error(f"Error receiving video frame: {e}")
                    await asyncio.sleep(0.01)
                
            self.logger.info(f"Video consumption ended. Total frames: {frame_count}")
            
        except Exception as e:
            self.logger.error(f"Error in video consumption loop: {e}")
            import traceback
            traceback.print_exc()

    def _start_frame_processing_thread(self):
        """Start thread to process frames from janus queue"""
        def process_frames():
            try:
                self.logger.info("Starting frame processing thread...")
                
                while self.is_streaming:
                    try:
                        # Get frame from sync side of janus queue with timeout
                        frame = self.frame_queue.sync_q.get(timeout=1.0)
                        
                        # Update current frame for Flask
                        with self.frame_lock:
                            self.current_frame = frame.copy()
                        
                        # Call frame callback if set
                        if self.frame_callback:
                            self.frame_callback(frame)
                            
                    except:
                        # Timeout or queue empty - continue loop
                        continue
                        
                self.logger.info("Frame processing thread ended")
                
            except Exception as e:
                self.logger.error(f"Error in frame processing thread: {e}")
        
        processing_thread = threading.Thread(target=process_frames, daemon=True)
        processing_thread.start()

    def _try_direct_frame_access(self, video_track):
        """Try to access frames directly from the video track"""
        try:
            self.logger.info("Attempting direct frame access...")
            
            # Check if the Go2 library has specific methods for frame access
            if hasattr(self.connection, 'getVideoFrame'):
                self.logger.info("Found getVideoFrame method on connection")
                self._start_direct_frame_capture()
            elif hasattr(self.connection, 'video_frames'):
                self.logger.info("Found video_frames property on connection")
                self._start_frame_monitoring()
            else:
                self.logger.info("No direct frame access methods found, showing enhanced test pattern")
                self._generate_enhanced_test_pattern_with_track_info(video_track)
            
        except Exception as e:
            self.logger.error(f"Error in direct frame access: {e}")
            self._generate_enhanced_test_pattern()

    def _start_direct_frame_capture(self):
        """Start capturing frames using direct connection methods"""
        def capture_frames():
            frame_count = 0
            while self.is_streaming:
                try:
                    if hasattr(self.connection, 'getVideoFrame'):
                        frame = self.connection.getVideoFrame()
                        if frame:
                            self.logger.info(f"Got frame {frame_count} from getVideoFrame")
                            self._process_video_data(frame)
                            frame_count += 1
                    time.sleep(1/30)  # 30 FPS
                except Exception as e:
                    self.logger.error(f"Error in direct frame capture: {e}")
                    time.sleep(0.1)
        
        capture_thread = threading.Thread(target=capture_frames, daemon=True)
        capture_thread.start()

    def _start_frame_monitoring(self):
        """Monitor video frames property"""
        def monitor_frames():
            frame_count = 0
            while self.is_streaming:
                try:
                    if hasattr(self.connection, 'video_frames') and len(self.connection.video_frames) > 0:
                        frame = self.connection.video_frames[-1]  # Get latest frame
                        self.logger.info(f"Got frame {frame_count} from video_frames")
                        self._process_video_data(frame)
                        frame_count += 1
                    time.sleep(1/30)  # 30 FPS
                except Exception as e:
                    self.logger.error(f"Error monitoring frames: {e}")
                    time.sleep(0.1)
        
        monitor_thread = threading.Thread(target=monitor_frames, daemon=True)
        monitor_thread.start()

    def _generate_enhanced_test_pattern_with_track_info(self, video_track):
        """Generate enhanced test pattern with video track information"""
        self.logger.info("Generating enhanced test pattern with video track info")
        
        frame_count = 0
        while self.is_streaming:
            # Create test pattern with track information
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            
            # Animated green border showing active connection
            color = int(abs(np.sin(frame_count * 0.1)) * 255)
            cv2.rectangle(frame, (30, 30), (610, 450), (0, color, 0), 4)
            
            # Connection status text
            cv2.putText(frame, f"Unitree Go2 - WebRTC Connected", (80, 180), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(frame, f"Video Track Detected: {video_track.kind}", (90, 220), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"Track ID: {video_track.id[:20]}...", (90, 250), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            cv2.putText(frame, f"Attempting frame extraction...", (110, 280), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.putText(frame, f"Frame: {frame_count}", (250, 320), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            with self.frame_lock:
                self.current_frame = frame.copy()
                
            if self.frame_callback:
                self.frame_callback(frame)
                
            frame_count += 1
            time.sleep(1/15)  # 15 FPS for test pattern

    def _generate_enhanced_test_pattern(self):
        """Generate enhanced test pattern showing WebRTC status - DISABLED when real frames flowing"""
        # Check if we have received real frames recently  
        current_frame_count = getattr(self, '_frame_count', 0)
        if current_frame_count > 0:
            # Real frames are flowing - don't generate test pattern
            self.logger.info("Skipping test pattern - real frames are flowing")
            return
            
        self.logger.info("Generating enhanced test pattern - WebRTC connected with detailed info")
        
        frame_count = 0
        while self.is_streaming:
            # Check again in loop in case real frames start
            current_frame_count = getattr(self, '_frame_count', 0)
            if current_frame_count > 0:
                self.logger.info("Stopping test pattern - real frames started")
                break
            # Create test pattern with more info
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            
            # Animated green border showing active connection
            color = int(abs(np.sin(frame_count * 0.1)) * 255)
            cv2.rectangle(frame, (30, 30), (610, 450), (0, color, 0), 4)
            
            # Connection status text
            cv2.putText(frame, f"Unitree Go2 - WebRTC Active", (90, 200), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(frame, f"Video Channel: Working on frame extraction", (60, 240), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(frame, f"Heartbeat: Active", (200, 280), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(frame, f"Frame: {frame_count}", (250, 320), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            with self.frame_lock:
                self.current_frame = frame.copy()
                
            if self.frame_callback:
                self.frame_callback(frame)
                
            frame_count += 1
            time.sleep(1/15)  # 15 FPS for test pattern

    def _capture_webrtc_frames(self, video_receiver):
        """Capture frames from WebRTC video receiver"""
        try:
            self.logger.info("Starting async WebRTC video frame capture...")
            
            # Run the async frame capture in the existing event loop
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                loop.run_until_complete(self._async_capture_frames(video_receiver))
            finally:
                loop.close()
                
        except Exception as e:
            self.logger.error(f"Error in video frame capture setup: {e}")
            import traceback
            traceback.print_exc()
            self._generate_robot_test_pattern()
            
    async def _async_capture_frames(self, video_receiver):
        """Async method to capture video frames"""
        try:
            video_track = video_receiver.track
            self.logger.info(f"Starting async capture from video track: {video_track}")
            
            frame_count = 0
            while self.is_streaming:
                try:
                    if hasattr(video_track, 'recv'):
                        # Await the frame directly in the async context
                        frame = await video_track.recv()
                        
                        if frame and hasattr(frame, 'to_ndarray'):
                            img = frame.to_ndarray(format='bgr24')
                            
                            if frame_count == 0:  # First frame
                                self.logger.info(f"SUCCESS! First WebRTC frame converted: {img.shape}")
                            
                            with self.frame_lock:
                                self.current_frame = img.copy()
                            
                            if self.frame_callback:
                                self.frame_callback(img)
                                
                            frame_count += 1
                            if frame_count % 30 == 0:  # Log every 30 frames
                                self.logger.info(f"Processed {frame_count} real video frames from robot!")
                                
                        elif frame:
                            self.logger.warning(f"Frame type {type(frame)} doesn't support to_ndarray")
                        else:
                            # No frame received, small delay
                            await asyncio.sleep(0.01)
                            
                    else:
                        self.logger.warning("Video track doesn't support recv()")
                        break
                        
                    # Small delay to prevent overwhelming the system
                    await asyncio.sleep(1/60)  # 60 FPS max
                    
                except Exception as e:
                    self.logger.error(f"Error in async frame capture: {e}")
                    await asyncio.sleep(0.1)
                    
            self.logger.info(f"Async frame capture ended. Total frames: {frame_count}")
            
            # If no frames were captured, fall back to test pattern
            if frame_count == 0:
                self.logger.warning("No frames captured, showing test pattern")
                self._generate_robot_test_pattern()
                
        except Exception as e:
            self.logger.error(f"Error in async frame capture: {e}")
            import traceback
            traceback.print_exc()
            self._generate_robot_test_pattern()
            
    def _on_video_frame(self, frame):
        """Callback for WebRTC video frames"""
        with self.frame_lock:
            self.current_frame = frame.copy()
            
        if self.frame_callback:
            self.frame_callback(frame)
            
    def get_frame(self) -> Optional[np.ndarray]:
        """Get the most recent frame"""
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
        return None
        
    def stop_video_stream(self):
        """Stop video streaming"""
        self.is_streaming = False
        if self.video_thread:
            self.video_thread.join(timeout=2.0)
            
    def disconnect(self):
        """Disconnect from robot"""
        self.stop_video_stream()
        
        # Clean up async video consumption task
        if self.video_consume_task and not self.video_consume_task.done():
            self.video_consume_task.cancel()
            
        # Clean up janus queue
        if self.frame_queue:
            try:
                self.frame_queue.close()
            except:
                pass
        
        if self.connection:
            try:
                # Close WebRTC connection
                if hasattr(self.connection, 'close'):
                    self.connection.close()
            except Exception as e:
                self.logger.error(f"Error closing connection: {e}")
            finally:
                self.connection = None
                
        self.is_connected = False
        
    def send_command(self, command: str, params: dict = None) -> dict:
        """Send command to robot via WebRTC"""
        try:
            if command == "status":
                # Test WebRTC connection capability
                if self.connection and self.is_connected:
                    return {"status": "success", "message": "Robot connected via WebRTC"}
                else:
                    # Try to establish WebRTC connection for testing
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        success = loop.run_until_complete(self.connect())
                        if success:
                            return {"status": "success", "message": "WebRTC connection test successful"}
                        else:
                            return {"status": "error", "message": "WebRTC connection failed - robot may not be in AP mode or library issues"}
                    finally:
                        loop.close()
            else:
                # For actual robot commands, we need to use the WebRTC connection
                if self.connection and self.is_connected:
                    # Real commands would go through the WebRTC connection
                    return {"status": "success", "message": f"WebRTC command '{command}' would be sent to robot"}
                else:
                    return {"status": "error", "message": "Robot not connected via WebRTC"}
                
        except Exception as e:
            self.logger.error(f"WebRTC command error: {e}")
            return {"status": "error", "message": f"WebRTC error: {str(e)}"}
            
    def get_robot_status(self) -> dict:
        """Get robot status information"""
        try:
            # Check if WebRTC connection is actually established
            webrtc_connected = False
            if self.connection and hasattr(self.connection, 'isConnected'):
                webrtc_connected = self.connection.isConnected
            elif self.connection:
                webrtc_connected = True  # Connection object exists
                
            # Update our internal status based on WebRTC state
            self.is_connected = webrtc_connected
            
            status = {
                "connected": self.is_connected,
                "streaming": self.is_streaming,
                "ip": self.robot_ip,
                "serial_number": self.serial_number,
                "go2_library": GO2_AVAILABLE,
                "webrtc_connected": webrtc_connected,
                "connection_object": self.connection is not None
            }
            
            return status
            
        except Exception as e:
            return {"error": str(e)}