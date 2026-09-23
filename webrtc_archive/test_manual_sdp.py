#!/usr/bin/env python3
"""
Test manual SDP exchange to debug the exact failure point
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

def test_manual_sdp_exchange():
    """Manually test the SDP exchange process"""
    
    # Robot details
    robot_ip = "192.168.86.22"
    url = f"http://{robot_ip}:9991/con_notify"
    
    # Your token
    token = os.environ.get("UNITREE_TOKEN", "")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print("🔍 Testing manual SDP exchange...")
    
    # Step 1: Initial request (like curl test)
    print("1️⃣ Sending initial connection request...")
    try:
        response = requests.post(url, json={"test": "sdp_test"}, headers=headers, timeout=5)
        if response.status_code == 200:
            print(f"✅ Initial request successful: {response.status_code}")
            
            # Decode response
            decoded_response = base64.b64decode(response.text).decode('utf-8')
            print(f"📦 Decoded response: {decoded_response[:100]}...")
            
            # Parse JSON
            decoded_json = json.loads(decoded_response)
            data1 = decoded_json.get('data1')
            
            if data1:
                print(f"🔑 Got data1: {len(data1)} chars")
                
                # Test RSA key extraction
                public_key_pem = data1[10 : len(data1) - 10]  # Library extraction
                print(f"🔧 Extracted key length: {len(public_key_pem)} chars")
                
                try:
                    crypto_key = load_robot_pubkey(public_key_pem)
                    print(f"✅ RSA key loaded successfully: {crypto_key.key_size} bits")
                    
                    # This is where the library would encrypt the SDP offer
                    print("🔐 This is where SDP encryption would happen...")
                    print("📡 Robot is ready for SDP exchange!")
                    
                except Exception as e:
                    print(f"❌ RSA key loading failed: {e}")
            
        else:
            print(f"❌ Initial request failed: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection error: {e}")
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_manual_sdp_exchange()