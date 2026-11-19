#!/usr/bin/env python3
"""
Test structured SDP offer format
"""
import requests
import json
import sys
import os
from aiortc import RTCPeerConnection, RTCSessionDescription

# Add the project directory to the path
sys.path.insert(0, '/Users/Raleigh/Development/watch_dog')

# Import our monkey patch
import webrtc_patch

async def test_structured_sdp_offer():
    """Test the structured SDP offer format you suggested"""
    
    # Robot details
    robot_ip = "192.168.86.22"
    token = os.environ.get("UNITREE_TOKEN", "")
    
    print("🔍 Testing structured SDP offer format...")
    
    # Create a simple WebRTC peer connection to generate SDP offer
    pc = RTCPeerConnection()
    
    # Add a dummy data channel to create an offer
    dc = pc.createDataChannel("test")
    
    # Create the offer
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    print(f"✅ Generated SDP offer ({len(offer.sdp)} chars)")
    
    # Use your suggested structured format
    offer_body = {
        "type": "offer",
        "sdp": offer.sdp,
        "client": "custom",
        "version": "1.1",
        "codec": "h264",
        "protocol": "udp"
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "X-Device-Id": "8B4C8223BFDFED5BA",  # From your token
        "User-Agent": "UnitreeGo/1.1"
    }
    
    print("📡 Sending structured SDP offer to robot...")
    
    try:
        # Use HTTP instead of HTTPS (robot doesn't support HTTPS properly)
        response = requests.post(
            f"http://{robot_ip}:9991/con_notify",
            headers=headers,
            json=offer_body,
            timeout=10
        )
        
        print(f"📊 Response status: {response.status_code}")
        print(f"📦 Response headers: {dict(response.headers)}")
        print(f"📄 Response body: {response.text[:200]}...")
        
        if response.status_code == 200:
            print("✅ Structured SDP offer successful!")
            
            # Try to parse response
            try:
                if response.text.strip():
                    # Check if it's base64 encoded
                    import base64
                    decoded = base64.b64decode(response.text).decode('utf-8')
                    print(f"📋 Decoded response: {decoded[:200]}...")
                    
                    # Parse as JSON
                    json_response = json.loads(decoded)
                    if 'sdp' in str(json_response):
                        print("🎉 Got SDP answer from robot!")
                    else:
                        print("📝 Robot response (not SDP answer):")
                        print(json.dumps(json_response, indent=2)[:300])
                        
            except Exception as parse_error:
                print(f"📄 Raw response: {response.text[:200]}...")
                
        else:
            print(f"❌ Request failed: {response.status_code}")
            print(f"Error: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
    
    # Clean up
    await pc.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_structured_sdp_offer())