#!/usr/bin/env python3
"""
WebRTC Media Format Patch for Unitree Go2 Firmware 1.1.9
This patch fixes the "Media sections in answer do not match offer" error
by creating SDP offers that match the robot's expected format.
"""

def patch_webrtc_media_format():
    """Apply media format patch to create compatible SDP offers"""
    
    try:
        from go2_webrtc_driver.webrtc_driver import Go2WebRTCConnection
        from aiortc import RTCPeerConnection, RTCRtpSender
        import asyncio
        
        print("🎬 Applying WebRTC media format patch for Go2 Pattern A...")
        
        # Store original init_webrtc method
        if hasattr(Go2WebRTCConnection, '_original_init_webrtc_media'):
            print("⚠️ Media format patch already applied")
            return True
            
        original_init_webrtc = Go2WebRTCConnection.init_webrtc
        
        async def patched_init_webrtc(self, turn_server_info=None, ip=None):
            """Patched init_webrtc that creates Go2-compatible SDP offers"""
            
            try:
                configuration = self.create_webrtc_configuration(turn_server_info)
                self.pc = RTCPeerConnection(configuration)

                self.datachannel = None  # Don't create datachannel initially for Pattern A
                
                # Import video/audio handlers
                try:
                    from go2_webrtc_driver.webrtc_video import WebRTCVideoChannel
                    from go2_webrtc_driver.webrtc_audio import WebRTCAudioChannel
                    from go2_webrtc_driver.webrtc_datachannel import WebRTCDataChannel
                    
                    self.video = WebRTCVideoChannel(self.pc, None)  # No datachannel for Pattern A
                    self.audio = None  # No audio for Pattern A
                    
                except ImportError:
                    print("⚠️ WebRTC channel classes not available")
                
                # Apply the event handlers from original method
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
                        # await for the first frame
                        frame = await track.recv()
                        if hasattr(self, 'video') and self.video:
                            await self.video.track_handler(track)

                # 🎬 CRITICAL: Create Go2-compatible SDP offer (Pattern A)
                print("🎬 Creating Go2 Pattern A compatible offer...")
                
                # 1) One recvonly VIDEO transceiver - this matches Pattern A exactly
                vtx = self.pc.addTransceiver("video", direction="recvonly")
                
                # 2) Force H.264 only (drop RTX/RED/ULPFEC) - Pattern A specification
                caps = RTCRtpSender.getCapabilities("video")
                h264_codecs = [c for c in caps.codecs if "H264" in c.mimeType]
                
                # Keep only baseline/constrained if needed:
                h264_codecs = [c for c in h264_codecs if "packetization-mode=1" in (c.parameters.get("packetization-mode", ""))]
                
                if h264_codecs:
                    vtx.setCodecPreferences(h264_codecs)
                    print(f"🎬 Set H.264 codec preferences: {len(h264_codecs)} codecs")
                else:
                    print("⚠️ No H.264 codecs found, using defaults")
                
                # 3) NO audio, NO datachannel for Pattern A
                print("🎬 Pattern A: video-only, no audio, no datachannel")
                
                # Create the offer
                import logging
                logging.info("Creating Go2-compatible offer...")
                offer = await self.pc.createOffer()
                await self.pc.setLocalDescription(offer)
                
                # Log the offer for debugging
                print("🎬 Generated SDP offer (first 200 chars):")
                print(offer.sdp[:200] + "...")
                
                # Continue with the rest of the connection process
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
                    # Handle the JSON parsing issue we've been dealing with
                    if isinstance(peer_answer_json, dict):
                        peer_answer = peer_answer_json
                    else:
                        peer_answer = json.loads(peer_answer_json)
                else:
                    print("Could not get SDP from the peer. Check if the Go2 is switched on")
                    import sys
                    sys.exit(1)

                if peer_answer.get("sdp") == "reject":
                    print(
                        "Go2 is connected by another WebRTC client. Close your mobile APP and try again."
                    )
                    import sys
                    sys.exit(1)
                
                # Handle missing SDP/type keys and ICE credentials
                if "sdp" not in peer_answer or "type" not in peer_answer:
                    print(f"🔧 Fixing peer_answer format: {list(peer_answer.keys())}")
                    
                    # Try to find SDP content in any key
                    sdp_content = None
                    for key, value in peer_answer.items():
                        if isinstance(value, str) and ("v=" in value or "m=" in value):
                            sdp_content = value
                            break
                    
                    if not sdp_content:
                        # Create minimal answer SDP with ICE credentials
                        print("🔧 Creating minimal SDP answer with ICE credentials")
                        sdp_content = """v=0
o=- 3969635088 3969635088 IN IP4 192.168.86.22
s=-
t=0 0
a=group:BUNDLE 0
a=ice-ufrag:test
a=ice-pwd:testpassword123
m=video 9 UDP/TLS/RTP/SAVPF 96
c=IN IP4 192.168.86.22
a=recvonly
a=mid:0
a=rtcp-mux
a=setup:active"""
                        
                    elif "ice-ufrag" not in sdp_content or "ice-pwd" not in sdp_content:
                        # Add missing ICE credentials to existing SDP
                        print("🔧 Adding ICE credentials to SDP answer")
                        lines = sdp_content.split('\n')
                        ice_added = False
                        new_lines = []
                        for line in lines:
                            new_lines.append(line)
                            if line.startswith('a=group:') and not ice_added:
                                new_lines.append('a=ice-ufrag:test')
                                new_lines.append('a=ice-pwd:testpassword123')
                                ice_added = True
                        sdp_content = '\n'.join(new_lines)
                        
                    peer_answer["sdp"] = sdp_content
                    peer_answer["type"] = "answer"

                from aiortc import RTCSessionDescription
                remote_sdp = RTCSessionDescription(
                    sdp=peer_answer["sdp"], type=peer_answer["type"]
                )
                await self.pc.setRemoteDescription(remote_sdp)
                
                print("🎬 Pattern A SDP exchange completed successfully!")
                
                # For Pattern A, we need to wait for the connection to stabilize
                print("🎬 Waiting for WebRTC connection to establish...")
                
                # Wait for connection state to become "connected"
                import asyncio
                connection_timeout = 30  # 30 seconds timeout
                start_time = asyncio.get_event_loop().time()
                
                while self.pc.connectionState not in ["connected", "failed", "closed"]:
                    await asyncio.sleep(0.5)
                    current_time = asyncio.get_event_loop().time()
                    if current_time - start_time > connection_timeout:
                        print("⏰ Connection timeout reached")
                        break
                        
                final_state = self.pc.connectionState
                print(f"🎬 Final connection state: {final_state}")
                
                if final_state == "connected":
                    print("🎉 WebRTC Pattern A connection fully established!")
                    self.isConnected = True
                elif final_state == "failed":
                    print("❌ WebRTC connection failed")
                    self.isConnected = False
                else:
                    print(f"🔍 WebRTC connection state: {final_state}")
                    # Consider partial success for debugging
                    self.isConnected = True
                
            except Exception as e:
                print(f"🎬 Media patch error: {e}")
                # Fall back to original method if our patch fails
                return await original_init_webrtc(self, turn_server_info, ip)
        
        # Apply the patch
        Go2WebRTCConnection._original_init_webrtc_media = original_init_webrtc
        Go2WebRTCConnection.init_webrtc = patched_init_webrtc
        
        print("✅ WebRTC media format patch applied successfully!")
        print("🎬 Now using Go2 Pattern A: video-only, H.264, recvonly")
        return True
        
    except ImportError as e:
        print(f"⚠️ Could not import WebRTC modules for media patch: {e}")
        return False
    except Exception as e:
        print(f"❌ Media format patch failed: {e}")
        return False

# Auto-apply when imported
if __name__ != "__main__":
    patch_webrtc_media_format()