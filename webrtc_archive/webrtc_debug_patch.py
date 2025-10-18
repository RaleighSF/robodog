#!/usr/bin/env python3
"""
WebRTC SDP Debug Patch for Go2 Pattern Detection
This patch implements the debugging solution to detect and match robot's SDP pattern
"""

def decrypt_robot_response(encrypted_data):
    """Decrypt robot SDP response data"""
    try:
        import base64
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        
        print(f"🔓 Decrypting robot response ({len(encrypted_data)} chars)...")
        
        # First try base64 decode
        try:
            decoded_data = base64.b64decode(encrypted_data)
            print(f"🔓 Base64 decoded ({len(decoded_data)} bytes)")
        except Exception as e:
            print(f"⚠️ Base64 decode failed: {e}")
            return None
            
        # Try to decrypt with AES (the structured method showed AES usage)
        # We'll try different approaches since we know it worked before
        
        # Method 1: Try with our known key patterns
        try:
            # The robot typically uses the first part as IV and the rest as encrypted data
            if len(decoded_data) > 16:
                iv = decoded_data[:16]  # First 16 bytes as IV
                encrypted = decoded_data[16:]  # Rest as encrypted data
                
                # Try with a default key (this was used in the enhanced patch)
                key = b'1234567890123456'  # 16-byte key
                cipher = AES.new(key, AES.MODE_CBC, iv)
                decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)
                
                # Check if it looks like SDP
                decrypted_text = decrypted.decode('utf-8', errors='ignore')
                if "v=" in decrypted_text or "m=" in decrypted_text:
                    print("🔓 AES decryption successful with method 1!")
                    return decrypted_text
                    
        except Exception as e:
            print(f"⚠️ AES method 1 failed: {e}")
        
        # Method 2: Try direct text decode (maybe it's not encrypted)
        try:
            text_decoded = decoded_data.decode('utf-8', errors='ignore')
            if "v=" in text_decoded or "m=" in text_decoded:
                print("🔓 Direct text decode successful!")
                return text_decoded
        except Exception as e:
            print(f"⚠️ Direct text decode failed: {e}")
            
        # Method 3: Try JSON parsing (maybe it's JSON wrapped)
        try:
            import json
            text_decoded = decoded_data.decode('utf-8', errors='ignore')
            json_data = json.loads(text_decoded)
            
            # Look for SDP content in JSON
            for key, value in json_data.items():
                if isinstance(value, str) and ("v=" in value or "m=" in value):
                    print(f"🔓 Found SDP in JSON key '{key}'!")
                    return value
                    
        except Exception as e:
            print(f"⚠️ JSON method failed: {e}")
            
        print(f"🔓 All decryption methods failed. Data preview: {decoded_data[:50]}...")
        return None
        
    except Exception as e:
        print(f"❌ Decrypt error: {e}")
        return None

def patch_webrtc_sdp_debugging():
    """Apply SDP debugging patch to detect robot's actual pattern"""
    
    try:
        from go2_webrtc_driver.webrtc_driver import Go2WebRTCConnection
        import asyncio
        
        print("🔍 Applying WebRTC SDP debugging patch...")
        
        # Store original init_webrtc method
        if hasattr(Go2WebRTCConnection, '_original_init_webrtc_debug'):
            print("⚠️ SDP debug patch already applied")
            return True
            
        original_init_webrtc = Go2WebRTCConnection.init_webrtc
        
        async def patched_init_webrtc_debug(self, turn_server_info=None, ip=None):
            """Patched init_webrtc with SDP pattern detection and matching"""
            
            try:
                configuration = self.create_webrtc_configuration(turn_server_info)
                from aiortc import RTCPeerConnection
                self.pc = RTCPeerConnection(configuration)
                
                # Import channel classes
                try:
                    from go2_webrtc_driver.webrtc_video import WebRTCVideoChannel
                    from go2_webrtc_driver.webrtc_audio import WebRTCAudioChannel
                    from go2_webrtc_driver.webrtc_datachannel import WebRTCDataChannel
                    
                    # Initialize channels but don't create transceivers yet
                    self.video = WebRTCVideoChannel(self.pc, None)
                    self.audio = None
                    self.datachannel = None
                    
                except ImportError:
                    print("⚠️ WebRTC channel classes not available")
                
                # Apply event handlers from original method
                @self.pc.on("icegatheringstatechange")
                async def on_ice_gathering_state_change():
                    from go2_webrtc_driver.util import print_status
                    state = self.pc.iceGatheringState
                    if state == "new":
                        print_status("ICE Gathering State", "🔵 new")
                    elif state == "gathering":
                        print_status("ICE Gathering State", "🟡 gathering")
                    elif state == "complete":
                        print_status("ICE Gathering State", "🟢 complete")

                @self.pc.on("iceconnectionstatechange")
                async def on_ice_connection_state_change():
                    from go2_webrtc_driver.util import print_status
                    state = self.pc.iceConnectionState
                    if state == "checking":
                        print_status("ICE Connection State", "🔵 checking")
                    elif state == "completed":
                        print_status("ICE Connection State", "🟢 completed")
                    elif state == "failed":
                        print_status("ICE Connection State", "🔴 failed")
                    elif state == "closed":
                        print_status("ICE Connection State", "⚫ closed")

                @self.pc.on("connectionstatechange")
                async def on_connection_state_change():
                    from go2_webrtc_driver.util import print_status
                    state = self.pc.connectionState
                    if state == "connecting":
                        print_status("Peer Connection State", "🔵 connecting")
                    elif state == "connected":
                        self.isConnected = True
                        print_status("Peer Connection State", "🟢 connected")
                    elif state == "closed":
                        self.isConnected = False
                        print_status("Peer Connection State", "⚫ closed")
                    elif state == "failed":
                        print_status("Peer Connection State", "🔴 failed")

                @self.pc.on("signalingstatechange")
                async def on_signaling_state_change():
                    from go2_webrtc_driver.util import print_status
                    state = self.pc.signalingState
                    if state == "stable":
                        print_status("Signaling State", "🟢 stable")
                    elif state == "have-local-offer":
                        print_status("Signaling State", "🟡 have-local-offer")
                    elif state == "have-remote-offer":
                        print_status("Signaling State", "🟡 have-remote-offer")
                    elif state == "closed":
                        print_status("Signaling State", "⚫ closed")

                @self.pc.on("track")
                async def on_track(track):
                    import logging
                    logging.info(f"Track received: {track.kind}")
                    if track.kind == "video":
                        frame = await track.recv()
                        if hasattr(self, 'video') and self.video:
                            await self.video.track_handler(track)

                # 🔍 STEP 1: Create initial minimal offer to probe robot's response
                print("🔍 Creating minimal probe offer to detect robot's pattern...")
                
                # Start with just video
                from aiortc import RTCRtpSender
                vtx = self.pc.addTransceiver("video", direction="recvonly")
                
                # Set H.264 preferences
                caps = RTCRtpSender.getCapabilities("video")
                h264_codecs = [c for c in caps.codecs if "H264" in c.mimeType]
                if h264_codecs:
                    vtx.setCodecPreferences(h264_codecs)
                    print(f"🔍 Set H.264 codec preferences: {len(h264_codecs)} codecs")
                
                # Create initial offer
                import logging
                logging.info("Creating probe offer...")
                offer = await self.pc.createOffer()
                await self.pc.setLocalDescription(offer)
                
                # Helper function for SDP m-line analysis
                def sdp_m_lines(s):
                    return [ln for ln in s.split('\n') if ln.startswith("m=")]
                
                print("🔍 OFFER m-lines:", sdp_m_lines(self.pc.localDescription.sdp))
                
                # Send the probe offer to get robot's response
                from go2_webrtc_driver.constants import WebRTCConnectionMethod
                if self.connectionMethod == WebRTCConnectionMethod.Remote:
                    peer_answer_json = await self.get_answer_from_remote_peer(
                        self.pc, turn_server_info
                    )
                elif (
                    self.connectionMethod == WebRTCConnectionMethod.LocalSTA
                    or self.connectionMethod == WebRTCConnectionMethod.LocalAP
                ):
                    peer_answer_json = await self.get_answer_from_local_peer(self.pc, ip)

                if peer_answer_json is not None:
                    import json
                    # Enhanced JSON parsing with error handling
                    if isinstance(peer_answer_json, dict):
                        peer_answer = peer_answer_json
                    else:
                        try:
                            peer_answer = json.loads(peer_answer_json)
                        except (TypeError, json.JSONDecodeError) as json_error:
                            print(f"🔧 JSON parsing fix: {json_error}")
                            if isinstance(peer_answer_json, str):
                                # Try to parse as string
                                peer_answer = {"data1": peer_answer_json}
                            else:
                                peer_answer = peer_answer_json
                else:
                    print("Could not get SDP from the peer. Check if the Go2 is switched on")
                    import sys
                    sys.exit(1)

                # Handle JSON format issues and extract SDP content
                if "sdp" not in peer_answer or "type" not in peer_answer:
                    print(f"🔧 Fixing peer_answer format: {list(peer_answer.keys())}")
                    
                    # SYSTEMATIC DEBUGGING: Show exactly what we have
                    sdp_content = None
                    for key, value in peer_answer.items():
                        print(f"🔍 Analyzing key '{key}': type={type(value)}, length={len(str(value)) if value else 'None'}")
                        
                        if isinstance(value, str):
                            # Check for direct SDP content patterns
                            if ("v=" in value or "m=" in value or "a=" in value or "c=" in value):
                                sdp_content = value
                                print(f"✅ Found direct SDP content in key '{key}'")
                                break
                            
                            print(f"🔍 Key '{key}' content preview: {value[:100]}...")
                            print(f"🔍 Checking if key '{key}' matches data1/data2: {key in ['data1', 'data2']}")
                            print(f"🔍 Checking length > 50: {len(value) > 50}")
                            
                            # Force attempt decryption on data1 and data2 regardless of other conditions
                            if key in ['data1', 'data2']:
                                print(f"🔓 FORCING decryption attempt on {key}...")
                                try:
                                    decrypted_sdp = decrypt_robot_response(value)
                                    if decrypted_sdp and ("v=" in decrypted_sdp or "m=" in decrypted_sdp):
                                        sdp_content = decrypted_sdp
                                        print(f"🔓 SUCCESS! Decrypted SDP from {key}!")
                                        print(f"🔍 Decrypted SDP preview: {decrypted_sdp[:100]}...")
                                        break
                                    else:
                                        print(f"🔓 Decryption returned: {decrypted_sdp}")
                                except Exception as decrypt_error:
                                    print(f"❌ Decryption completely failed for {key}: {decrypt_error}")
                                    import traceback
                                    traceback.print_exc()
                            
                            # Try base64 decode as fallback
                            elif len(value) > 100 and not value.startswith('{'):
                                try:
                                    import base64
                                    decoded = base64.b64decode(value).decode('utf-8')
                                    if "v=" in decoded or "m=" in decoded:
                                        sdp_content = decoded
                                        print(f"✅ Found base64-encoded SDP in key '{key}'")
                                        break
                                except Exception as e:
                                    print(f"⚠️ Base64 decode failed for {key}: {e}")
                    
                    if sdp_content:
                        peer_answer["sdp"] = sdp_content
                        peer_answer["type"] = "answer"
                        print(f"🔍 Extracted SDP content ({len(sdp_content)} chars)")
                    else:
                        print("❌ No SDP content found in robot response")
                        print(f"🔍 Available keys: {list(peer_answer.keys())}")
                        for key, value in peer_answer.items():
                            if isinstance(value, str):
                                print(f"🔍 {key}: {value[:100]}..." if len(str(value)) > 100 else f"🔍 {key}: {value}")
                        return None

                # 🔍 STEP 2: Analyze robot's answer pattern
                robot_sdp = peer_answer["sdp"]
                robot_m_lines = sdp_m_lines(robot_sdp)
                print("🔍 ROBOT ANSWER m-lines:", robot_m_lines)
                
                # Determine robot's pattern
                has_audio = any("m=audio" in line for line in robot_m_lines)
                has_application = any("m=application" in line for line in robot_m_lines)
                has_video = any("m=video" in line for line in robot_m_lines)
                
                print(f"🔍 Robot pattern detected - Video: {has_video}, Audio: {has_audio}, Application/DataChannel: {has_application}")
                
                if has_video and not has_audio and not has_application:
                    print("🎬 Robot uses Pattern A: video-only")
                    pattern = "A"
                elif has_video and (has_audio or has_application):
                    print("🎬 Robot uses Pattern B: video + audio/datachannel")
                    pattern = "B"
                else:
                    print("🤔 Unknown robot pattern, using Pattern B as fallback")
                    pattern = "B"
                
                # 🔍 STEP 3: Create matching offer based on detected pattern
                print(f"🔍 Creating Pattern {pattern} compatible offer...")
                
                # Close current peer connection to start fresh
                await self.pc.close()
                
                # Create new peer connection with matching pattern
                self.pc = RTCPeerConnection(configuration)
                
                # Re-apply event handlers (simplified for brevity)
                @self.pc.on("connectionstatechange")
                async def on_connection_state_change():
                    from go2_webrtc_driver.util import print_status
                    state = self.pc.connectionState
                    if state == "connected":
                        self.isConnected = True
                        print_status("Peer Connection State", "🟢 connected")
                    elif state == "failed":
                        print_status("Peer Connection State", "🔴 failed")
                
                # Create transceivers to match robot's pattern
                if pattern == "B" and has_application:
                    # Create datachannel BEFORE createOffer (Pattern B rule)
                    print("🔍 Creating datachannel for Pattern B")
                    dc = self.pc.createDataChannel("cmd")
                
                if pattern == "B" and has_audio:
                    # Add audio transceiver for Pattern B
                    print("🔍 Adding audio transceiver for Pattern B")
                    atx = self.pc.addTransceiver("audio", direction="recvonly")
                
                # Always add video (both patterns have video)
                vtx = self.pc.addTransceiver("video", direction="recvonly")
                
                # Set H.264 preferences
                caps = RTCRtpSender.getCapabilities("video")
                h264_codecs = [c for c in caps.codecs if "H264" in c.mimeType]
                if h264_codecs:
                    vtx.setCodecPreferences(h264_codecs)
                
                # Create the matching offer
                offer = await self.pc.createOffer()
                await self.pc.setLocalDescription(offer)
                
                print(f"🔍 FINAL OFFER m-lines:", sdp_m_lines(self.pc.localDescription.sdp))
                
                # Send the matching offer
                if self.connectionMethod == WebRTCConnectionMethod.Remote:
                    peer_answer_json = await self.get_answer_from_remote_peer(
                        self.pc, turn_server_info
                    )
                elif (
                    self.connectionMethod == WebRTCConnectionMethod.LocalSTA
                    or self.connectionMethod == WebRTCConnectionMethod.LocalAP
                ):
                    peer_answer_json = await self.get_answer_from_local_peer(self.pc, ip)

                if peer_answer_json is not None:
                    if isinstance(peer_answer_json, dict):
                        peer_answer = peer_answer_json
                    else:
                        peer_answer = json.loads(peer_answer_json)
                        
                    # Handle format issues
                    if "sdp" not in peer_answer or "type" not in peer_answer:
                        for key, value in peer_answer.items():
                            if isinstance(value, str) and ("v=" in value or "m=" in value):
                                peer_answer["sdp"] = value
                                peer_answer["type"] = "answer"
                                break
                else:
                    print("Failed to get robot response to matching offer")
                    return None

                # Set remote description
                from aiortc import RTCSessionDescription
                remote_sdp = RTCSessionDescription(
                    sdp=peer_answer["sdp"], type=peer_answer["type"]
                )
                await self.pc.setRemoteDescription(remote_sdp)
                
                print("🎉 Pattern-matched SDP exchange completed successfully!")
                
                # Wait for connection to establish
                print("🔍 Waiting for WebRTC connection to establish...")
                connection_timeout = 30
                start_time = asyncio.get_event_loop().time()
                
                while self.pc.connectionState not in ["connected", "failed", "closed"]:
                    await asyncio.sleep(0.5)
                    current_time = asyncio.get_event_loop().time()
                    if current_time - start_time > connection_timeout:
                        print("⏰ Connection timeout reached")
                        break
                        
                final_state = self.pc.connectionState
                print(f"🔍 Final connection state: {final_state}")
                
                if final_state == "connected":
                    print(f"🎉 WebRTC Pattern {pattern} connection fully established!")
                    self.isConnected = True
                else:
                    print(f"⚠️ Connection state: {final_state}")
                    self.isConnected = (final_state != "failed")
                
            except Exception as e:
                print(f"🔍 Debug patch error: {e}")
                import traceback
                traceback.print_exc()
                # Fall back to original method
                return await original_init_webrtc(self, turn_server_info, ip)
        
        # Apply the debug patch with absolute priority - override any other patches
        Go2WebRTCConnection._original_init_webrtc_debug = original_init_webrtc
        Go2WebRTCConnection.init_webrtc = patched_init_webrtc_debug
        
        # CRITICAL: Force override any enhanced patch methods that may interfere
        Go2WebRTCConnection._json_parsing_init_webrtc = patched_init_webrtc_debug
        
        print("✅ WebRTC SDP debugging patch applied successfully!")
        print("🔧 DEBUG PATCH PRIORITY: Overriding all other init_webrtc methods")
        print("🔍 Will now probe robot pattern and create matching offers")
        return True
        
    except ImportError as e:
        print(f"⚠️ Could not import WebRTC modules for debug patch: {e}")
        return False
    except Exception as e:
        print(f"❌ Debug patch failed: {e}")
        return False

# Auto-apply when imported
if __name__ != "__main__":
    patch_webrtc_sdp_debugging()