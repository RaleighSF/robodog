#!/usr/bin/env python3
"""
Complete WebRTC handshake with FIXED path calculation
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

# Import our monkey patch and utilities
import webrtc_patch
from monkey_key import load_robot_pubkey

def _calc_local_path_ending_fixed(data1):
    """FIXED path calculation that handles all base64 characters"""
    
    # Extended character mapping to handle all base64 chars
    char_map = {
        'A': '0', 'B': '1', 'C': '2', 'D': '3', 'E': '4', 'F': '5', 'G': '6', 'H': '7', 'I': '8', 'J': '9',
        'a': '0', 'b': '1', 'c': '2', 'd': '3', 'e': '4', 'f': '5', 'g': '6', 'h': '7', 'i': '8', 'j': '9',
        'K': '0', 'L': '1', 'M': '2', 'N': '3', 'O': '4', 'P': '5', 'Q': '6', 'R': '7', 'S': '8', 'T': '9',
        'U': '0', 'V': '1', 'W': '2', 'X': '3', 'Y': '4', 'Z': '5', 'k': '6', 'l': '7', 'm': '8', 'n': '9',
        'o': '0', 'p': '1', 'q': '2', 'r': '3', 's': '4', 't': '5', 'u': '6', 'v': '7', 'w': '8', 'x': '9',
        'y': '0', 'z': '1', '0': '0', '1': '1', '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
        '+': '0', '/': '1', '=': '2'  # Base64 special chars
    }
    
    # Extract the last 10 characters
    last_10_chars = data1[-10:]
    
    # Split into chunks of 2
    chunked = [last_10_chars[i : i + 2] for i in range(0, len(last_10_chars), 2)]
    
    # Build path ending
    path_digits = []
    for chunk in chunked:
        if len(chunk) > 1:
            second_char = chunk[1]
            if second_char in char_map:
                path_digits.append(char_map[second_char])
            else:
                # Fallback: use ASCII value mod 10
                path_digits.append(str(ord(second_char) % 10))
    
    path_ending = "".join(path_digits)
    print(f"🔢 FIXED path calculation: last_10='{last_10_chars}' → path='{path_ending}'")
    
    return path_ending

def generate_aes_key():
    """Generate a random AES key"""
    import os
    return os.urandom(32)  # 256-bit key

def aes_encrypt(plaintext, key):
    """Encrypt plaintext with AES"""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    import base64
    
    cipher = AES.new(key, AES.MODE_CBC)
    ciphertext = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return base64.b64encode(cipher.iv + ciphertext).decode()

def rsa_encrypt(data, public_key):
    """Encrypt data with RSA public key"""
    from Crypto.Cipher import PKCS1_v1_5
    import base64
    
    cipher = PKCS1_v1_5.new(public_key)
    encrypted = cipher.encrypt(data)
    return base64.b64encode(encrypted).decode()

def aes_decrypt(ciphertext, key):
    """Decrypt AES ciphertext"""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    import base64
    
    data = base64.b64decode(ciphertext)
    iv = data[:16]
    encrypted = data[16:]
    
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)
    return decrypted.decode()

async def complete_fixed_webrtc_handshake():
    """Complete WebRTC handshake with FIXED path calculation"""
    
    robot_ip = "192.168.86.22"
    token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4QjRDODIyM0JGREZENUJBIiwiaWF0IjoxNzI0MjkxNDkwLCJhcHBfaWQiOiJZRjNVSTJTOE44SjJHVUJNIiwicHJvZHVjdF9pZCI6Imdvb19zbjhqM2dtdWJtOWZzamYzaGF1ZG1kIiwib3Blbl9pZCI6IjE3MjQyOTE0OTAyNjcxNjA2NzMifQ.OJV8qJ7MX7yOFzLzOsckLLfHBIZ4XJ5YI0UHXzQP-M_yXjYJILw8f4d23VyJpxYHCzKw4wYOCiI6OxrFJrqp5zIEd2F2Z3aQWQ-Qs4M3vOw95O4FUJLzK8b7VR3ckZIxfXTYJ-QO5ZNJFzZkQ_J9O4XzZ-VQ5O2cKYZ8J_zQ"
    
    print("🚀 Starting FIXED WebRTC handshake...")
    
    # Step 1: Create WebRTC peer connection
    pc = RTCPeerConnection()
    
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"🔗 Connection state: {pc.connectionState}")
    
    @pc.on("iceconnectionstatechange")  
    async def on_iceconnectionstatechange():
        print(f"🧊 ICE connection state: {pc.iceConnectionState}")
    
    # Create data channel
    dc = pc.createDataChannel("unitree_control")
    
    @dc.on("open")
    def on_open():
        print("🎉 DATA CHANNEL OPENED - WEBRTC CONNECTED!")
        
    @dc.on("message") 
    def on_message(message):
        print(f"📥 Received message: {message}")
    
    # Create SDP offer
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    print(f"📋 Created SDP offer ({len(offer.sdp)} chars)")
    
    # Step 2: Get robot's public key
    print("🔑 Step 1: Getting robot's public key...")
    
    initial_request = {
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
    
    try:
        response = requests.post(
            f"http://{robot_ip}:9991/con_notify",
            headers=headers,
            json=initial_request,
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"❌ Initial request failed: {response.status_code}")
            return
            
        print("✅ Got robot response!")
        
        # Step 3: Extract robot's key and calculate path
        decoded_response = base64.b64decode(response.text).decode('utf-8')
        response_json = json.loads(decoded_response)
        data1 = response_json['data1']
        
        print(f"🔑 Received data1: {len(data1)} chars")
        
        # Extract public key
        public_key_pem = data1[10 : len(data1) - 10]
        
        # FIXED path calculation
        path_ending = _calc_local_path_ending_fixed(data1)
        
        if not path_ending:
            print("⚠️ Path ending is empty, using fallback '123'")
            path_ending = "123"
        
        # Load robot's public key
        crypto_key = load_robot_pubkey(public_key_pem)
        
        # Convert to PyCrypto format
        from Crypto.PublicKey import RSA
        public_numbers = crypto_key.public_numbers()
        pycrypto_key = RSA.construct((public_numbers.n, public_numbers.e))
        
        print(f"🔐 Loaded robot public key: {crypto_key.key_size} bits")
        
        # Step 4: Encrypt SDP
        aes_key = generate_aes_key()
        encrypted_sdp = aes_encrypt(offer.sdp, aes_key) 
        encrypted_aes_key = rsa_encrypt(aes_key, pycrypto_key)
        
        print(f"🔒 Encrypted SDP: {len(encrypted_sdp)} chars")
        print(f"🔒 Encrypted AES key: {len(encrypted_aes_key)} chars")
        
        # Step 5: Send encrypted SDP
        print("📡 Step 2: Sending encrypted SDP...")
        
        encrypted_body = {
            "data1": encrypted_sdp,
            "data2": encrypted_aes_key
        }
        
        encrypted_url = f"http://{robot_ip}:9991/con_ing_{path_ending}"
        encrypted_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        print(f"🌐 Sending to: {encrypted_url}")
        
        encrypted_response = requests.post(
            encrypted_url,
            data=json.dumps(encrypted_body),
            headers=encrypted_headers,
            timeout=15
        )
        
        if encrypted_response.status_code == 200:
            print("✅ ENCRYPTED SDP SENT SUCCESSFULLY!")
            print(f"📦 Response length: {len(encrypted_response.text)} bytes")
            
            # Step 6: Decrypt robot's SDP answer
            try:
                decrypted_answer = aes_decrypt(encrypted_response.text, aes_key)
                print(f"🎉 DECRYPTED SDP ANSWER!")
                print(f"📋 SDP Answer: {decrypted_answer[:200]}...")
                
                # Step 7: Set remote description
                if 'v=' in decrypted_answer and 'm=' in decrypted_answer:
                    answer = RTCSessionDescription(sdp=decrypted_answer, type="answer")
                    await pc.setRemoteDescription(answer)
                    print("✅ SET REMOTE DESCRIPTION!")
                    
                    # Step 8: Wait for connection
                    print("⏳ Waiting for WebRTC connection establishment...")
                    for i in range(20):
                        await asyncio.sleep(1)
                        print(f"⏱️  Step {i+1}: Connection={pc.connectionState}, ICE={pc.iceConnectionState}")
                        
                        if pc.connectionState == "connected":
                            print("🎉🎉🎉 WEBRTC CONNECTION FULLY ESTABLISHED! 🎉🎉🎉")
                            
                            # Test data channel
                            if dc.readyState == "open":
                                print("📡 Testing data channel...")
                                dc.send("Hello from Claude Code!")
                                
                            # Keep connection alive
                            await asyncio.sleep(10)
                            break
                        elif pc.connectionState in ["failed", "closed"]:
                            print(f"❌ Connection failed: {pc.connectionState}")
                            break
                else:
                    print("❌ Response doesn't contain valid SDP answer")
                    print(f"Response: {decrypted_answer[:300]}...")
                    
            except Exception as decrypt_error:
                print(f"❌ Could not decrypt response: {decrypt_error}")
                print(f"Raw response: {encrypted_response.text[:200]}...")
                
        else:
            print(f"❌ Encrypted SDP request failed: {encrypted_response.status_code}")
            print(f"Response: {encrypted_response.text[:200]}...")
            
    except Exception as e:
        print(f"❌ Handshake failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await pc.close()
        print("🔚 Connection closed")

if __name__ == "__main__":
    asyncio.run(complete_fixed_webrtc_handshake())