#!/usr/bin/env python3
"""
Analyze robot's response to see if it contains SDP answer
"""
import requests
import base64
import json
import sys
import os

# Add the project directory to the path
sys.path.insert(0, '/Users/Raleigh/Development/watch_dog')

# Import our monkey patch
import webrtc_patch
from monkey_key import load_robot_pubkey

def analyze_robot_sdp_response():
    """Analyze what the robot sends back after our SDP offer"""
    
    robot_ip = "192.168.86.22"
    token = os.environ.get("UNITREE_TOKEN", "")
    
    # Test different SDP offer formats to see robot responses
    test_sdps = [
        # Minimal test SDP
        "v=0\r\no=- 123 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=application 9 DTLS/SCTP 5000\r\na=sctpmap:5000 webrtc-datachannel 256\r\n",
        
        # More complete SDP  
        "v=0\r\no=unitree 123456789 2 IN IP4 192.168.86.23\r\ns=UnitreeWebRTC\r\nt=0 0\r\na=group:BUNDLE 0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\nc=IN IP4 192.168.86.23\r\na=ice-ufrag:test\r\na=ice-pwd:testpassword\r\na=setup:actpass\r\na=mid:0\r\na=sctp-port:5000\r\na=max-message-size:262144\r\n"
    ]
    
    for i, test_sdp in enumerate(test_sdps):
        print(f"\n🧪 Testing SDP format {i+1}:")
        
        offer_body = {
            "type": "offer",
            "sdp": test_sdp,
            "client": "custom",
            "version": "1.1",
            "codec": "h264", 
            "protocol": "udp"
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "X-Device-Id": "B42D4000P6PC04GE",
            "User-Agent": "UnitreeGo/1.1"
        }
        
        try:
            response = requests.post(
                f"http://{robot_ip}:9991/con_notify",
                headers=headers,
                json=offer_body,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"✅ Response {i+1} successful")
                
                # Decode and analyze response
                try:
                    decoded_response = base64.b64decode(response.text).decode('utf-8')
                    response_json = json.loads(decoded_response)
                    
                    print(f"📋 Response structure:")
                    for key, value in response_json.items():
                        if isinstance(value, str) and len(value) > 100:
                            print(f"   {key}: {len(value)} chars - {value[:50]}...")
                        else:
                            print(f"   {key}: {value}")
                    
                    # Look for SDP-like content
                    full_response_str = str(response_json)
                    if any(sdp_indicator in full_response_str.lower() for sdp_indicator in ['v=0', 'm=', 'a=', 'o=']):
                        print("🎉 Found SDP-like content in response!")
                    else:
                        print("🔑 Response appears to be key exchange data")
                        
                        # Try to decode data1 further if it contains SDP
                        if 'data1' in response_json:
                            data1 = response_json['data1']
                            print(f"🔍 Analyzing data1 ({len(data1)} chars)...")
                            
                            # Try different decoding approaches
                            try:
                                # Maybe it's double-encoded
                                inner_decoded = base64.b64decode(data1).decode('utf-8', errors='ignore')
                                if any(sdp_indicator in inner_decoded.lower() for sdp_indicator in ['v=0', 'm=', 'a=', 'o=']):
                                    print("🎉 Found SDP content in data1!")
                                    print(f"📋 SDP Answer: {inner_decoded[:200]}...")
                                else:
                                    print("🔑 data1 contains non-SDP data (likely encrypted)")
                            except:
                                print("🔑 data1 is not text-decodable (likely binary/encrypted)")
                    
                except Exception as parse_error:
                    print(f"❌ Could not parse response: {parse_error}")
                    print(f"Raw response: {response.text[:100]}...")
                    
            else:
                print(f"❌ Response {i+1} failed: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Request {i+1} failed: {e}")

if __name__ == "__main__":
    analyze_robot_sdp_response()