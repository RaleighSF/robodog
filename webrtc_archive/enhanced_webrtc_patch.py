#!/usr/bin/env python3
"""
Enhanced WebRTC patch with structured SDP offer format
"""
import sys
import base64
import json
import requests
from monkey_key import load_robot_pubkey

def patch_structured_sdp_method():
    """Patch the SDP sending method to use structured format"""
    
    try:
        from go2_webrtc_driver import unitree_auth
        from Crypto.PublicKey import RSA
        
        # CRITICAL: Check if debug patch is enabled - if so, skip this patch
        try:
            from go2_webrtc_driver.webrtc_driver import Go2WebRTCConnection
            if hasattr(Go2WebRTCConnection, '_original_init_webrtc_debug'):
                print("🔧 Enhanced SDP patch DISABLED - debug patch has priority")
                return True
        except ImportError:
            pass
        
        print("🔧 Applying structured SDP format patch...")
        
        # Store original function
        if hasattr(unitree_auth, '_original_send_sdp_to_local_peer_new_method'):
            print("⚠️ Structured SDP patch already applied")
            return
            
        original_send_sdp = unitree_auth.send_sdp_to_local_peer_new_method
        
        def patched_structured_sdp(ip, sdp):
            """Patched SDP sender using structured format instead of encrypted"""
            print(f"🚀 Using enhanced structured SDP format for {ip}")
            
            try:
                # Your structured SDP format
                offer_body = {
                    "type": "offer",
                    "sdp": sdp,
                    "client": "custom",
                    "version": "1.1",
                    "codec": "h264",
                    "protocol": "udp"
                }
                
                # Enhanced headers
                headers = {
                    "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4QjRDODIyM0JGREZENUJBIiwiaWF0IjoxNzI0MjkxNDkwLCJhcHBfaWQiOiJZRjNVSTJTOE44SjJHVUJNIiwicHJvZHVjdF9pZCI6Imdvb19zbjhqM2dtdWJtOWZzamYzaGF1ZG1kIiwib3Blbl9pZCI6IjE3MjQyOTE0OTAyNjcxNjA2NzMifQ.OJV8qJ7MX7yOFzLzOsckLLfHBIZ4XJ5YI0UHXzQP-M_yXjYJILw8f4d23VyJpxYHCzKw4wYOCiI6OxrFJrqp5zIEd2F2Z3aQWQ-Qs4M3vOw95O4FUJLzK8b7VR3ckZIxfXTYJ-QO5ZNJFzZkQ_J9O4XzZ-VQ5O2cKYZ8J_zQ",
                    "Content-Type": "application/json",
                    "Connection": "keep-alive",
                    "X-Device-Id": "B42D4000P6PC04GE",  # Your actual robot serial
                    "User-Agent": "UnitreeGo/1.1"
                }
                
                print("📡 Sending structured SDP offer...")
                
                # Send structured SDP offer
                response = requests.post(
                    f"http://{ip}:9991/con_notify",
                    headers=headers,
                    json=offer_body,
                    timeout=10
                )
                
                if response.status_code == 200:
                    print("✅ Structured SDP offer successful!")
                    
                    # Parse robot response
                    try:
                        decoded_response = base64.b64decode(response.text).decode('utf-8')
                        response_json = json.loads(decoded_response)
                        
                        # Check if robot sent back an SDP answer
                        if 'sdp' in str(response_json).lower():
                            print("🎉 Got SDP answer from robot!")
                            return response_json
                        else:
                            print("📝 Robot sent key exchange response (normal)")
                            print("✅ Structured format accepted by robot!")
                            return response_json
                            
                    except Exception as parse_error:
                        print(f"📄 Raw response: {response.text[:100]}...")
                        return {"success": True, "raw_response": response.text}
                
                else:
                    print(f"❌ Structured SDP failed: {response.status_code}")
                    print(f"Error: {response.text}")
                    return None
                    
            except Exception as e:
                print(f"❌ Structured SDP error: {e}")
                # Fallback to original method
                print("🔄 Falling back to original SDP method...")
                return original_send_sdp(ip, sdp)
        
        # Apply the patch
        unitree_auth._original_send_sdp_to_local_peer_new_method = original_send_sdp
        unitree_auth.send_sdp_to_local_peer_new_method = patched_structured_sdp
        
        print("✅ Structured SDP format patch applied!")
        return True
        
    except Exception as e:
        print(f"❌ Structured SDP patch failed: {e}")
        return False

# Apply the patch when imported
patch_structured_sdp_method()