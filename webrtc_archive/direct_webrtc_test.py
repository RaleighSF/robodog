#!/usr/bin/env python3
"""
Direct WebRTC connection test to complete the handshake
"""
import asyncio
import json
import requests
import base64
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel
import sys
import os

# Add the project directory to the path
sys.path.insert(0, '/Users/Raleigh/Development/watch_dog')

# Import our monkey patch
import webrtc_patch
from monkey_key import load_robot_pubkey

async def direct_webrtc_connection():
    """Attempt a direct WebRTC connection with complete handshake"""
    
    robot_ip = "192.168.86.22"
    token = os.environ.get("UNITREE_TOKEN", "")
    
    print("🚀 Starting direct WebRTC connection test...")
    
    # Create peer connection
    pc = RTCPeerConnection()
    
    # Set up event handlers
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"🔗 Connection state changed: {pc.connectionState}")
    
    @pc.on("iceconnectionstatechange")  
    async def on_iceconnectionstatechange():
        print(f"🧊 ICE connection state changed: {pc.iceConnectionState}")
    
    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        print(f"📡 ICE gathering state changed: {pc.iceGatheringState}")
    
    # Create data channel
    print("📺 Creating data channel...")
    dc = pc.createDataChannel("unitree_control")
    
    @dc.on("open")
    def on_open():
        print("✅ Data channel opened!")
        
    @dc.on("message")
    def on_message(message):
        print(f"📥 Received message: {message}")
    
    # Create offer
    print("📋 Creating SDP offer...")
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    print(f"✅ SDP offer created ({len(offer.sdp)} chars)")
    
    # Send structured SDP offer to robot
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
        "X-Device-Id": "B42D4000P6PC04GE",
        "User-Agent": "UnitreeGo/1.1"
    }
    
    print("📡 Sending structured SDP offer to robot...")
    
    try:
        response = requests.post(
            f"http://{robot_ip}:9991/con_notify",
            headers=headers,
            json=offer_body,
            timeout=15
        )
        
        if response.status_code == 200:
            print("✅ SDP offer sent successfully!")
            print(f"📦 Response length: {len(response.text)} bytes")
            
            # Parse robot response
            try:
                decoded_response = base64.b64decode(response.text).decode('utf-8')
                response_json = json.loads(decoded_response)
                
                print("📋 Robot response received:")
                print(json.dumps(response_json, indent=2)[:200])
                
                # Check if robot sent back an SDP answer
                if 'sdp' in str(response_json).lower():
                    print("🎉 Robot provided SDP answer!")
                    # TODO: Set remote description with robot's answer
                else:
                    print("🔑 Robot provided key exchange (normal first step)")
                
            except Exception as parse_error:
                print(f"📄 Could not parse robot response: {parse_error}")
                print(f"Raw response: {response.text[:100]}...")
                
        else:
            print(f"❌ SDP offer failed: {response.status_code}")
            print(f"Error: {response.text}")
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        await pc.close()
        return
    
    # Wait for ICE gathering to complete
    print("⏳ Waiting for ICE gathering...")
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)
    
    print(f"✅ ICE gathering complete")
    print(f"🔗 Connection state: {pc.connectionState}")
    print(f"🧊 ICE connection state: {pc.iceConnectionState}")
    
    # Wait a bit to see if connection establishes
    print("⏳ Waiting for connection to establish...")
    for i in range(30):
        await asyncio.sleep(1)
        print(f"⏱️  Step {i+1}: Connection={pc.connectionState}, ICE={pc.iceConnectionState}")
        
        if pc.connectionState == "connected":
            print("🎉 WebRTC connection established!")
            break
        elif pc.connectionState in ["failed", "closed"]:
            print(f"❌ Connection failed: {pc.connectionState}")
            break
    
    # Clean up
    await pc.close()
    print("🔚 Connection closed")

if __name__ == "__main__":
    asyncio.run(direct_webrtc_connection())