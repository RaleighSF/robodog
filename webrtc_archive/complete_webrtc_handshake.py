#!/usr/bin/env python3
"""
Complete WebRTC handshake with encrypted SDP step
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

def _calc_local_path_ending(data1):
    """Calculate path ending from data1 (from library)"""
    # Initialize an array of strings
    strArr = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]

    # Extract the last 10 characters of data1
    last_10_chars = data1[-10:]

    # Split the last 10 characters into chunks of size 2
    chunked = [last_10_chars[i : i + 2] for i in range(0, len(last_10_chars), 2)]

    # Initialize an empty list to store indices
    arrayList = []

    # Iterate over the chunks and find the index of the second character in strArr
    for chunk in chunked:
        if len(chunk) > 1:
            second_char = chunk[1]
            try:
                index = strArr.index(second_char)
                arrayList.append(index)
            except ValueError:
                # Handle case where the character is not found in strArr
                print(f"Character {second_char} not found in strArr.")

    # Convert arrayList to a string without separators
    joinToString = "".join(map(str, arrayList))

    return joinToString

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

async def complete_webrtc_handshake():
    """Complete the full WebRTC handshake with encrypted SDP"""
    
    robot_ip = "192.168.86.22"
    token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4QjRDODIyM0JGREZENUJBIiwiaWF0IjoxNzI0MjkxNDkwLCJhcHBfaWQiOiJZRjNVSTJTOE44SjJHVUJNIiwicHJvZHVjdF9pZCI6Imdvb19zbjhqM2dtdWJtOWZzamYzaGF1ZG1kIiwib3Blbl9pZCI6IjE3MjQyOTE0OTAyNjcxNjA2NzMifQ.OJV8qJ7MX7yOFzLzOsckLLfHBIZ4XJ5YI0UHXzQP-M_yXjYJILw8f4d23VyJpxYHCzKw4wYOCiI6OxrFJrqp5zIEd2F2Z3aQWQ-Qs4M3vOw95O4FUJLzK8b7VR3ckZIxfXTYJ-QO5ZNJFzZkQ_J9O4XzZ-VQ5O2cKYZ8J_zQ"
    
    print("🚀 Starting complete WebRTC handshake...")
    
    # Step 1: Create WebRTC peer connection and SDP offer
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
        print("✅ Data channel opened!")
        
    # Create SDP offer
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    print(f"📋 Created SDP offer ({len(offer.sdp)} chars)")
    
    # Step 2: Send initial request to get robot's public key
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
        
        # Step 3: Extract and decrypt robot's response
        decoded_response = base64.b64decode(response.text).decode('utf-8')
        response_json = json.loads(decoded_response)
        data1 = response_json['data1']
        
        print(f"🔑 Received data1: {len(data1)} chars")
        
        # Step 4: Extract public key using library's method
        public_key_pem = data1[10 : len(data1) - 10]  # Library extraction
        path_ending = _calc_local_path_ending(data1)
        
        print(f"🔢 Calculated path ending: {path_ending}")
        
        # Step 5: Load the robot's public key using our monkey patch
        crypto_key = load_robot_pubkey(public_key_pem)
        
        # Convert to PyCrypto format for encryption
        from Crypto.PublicKey import RSA
        public_numbers = crypto_key.public_numbers()
        n = public_numbers.n
        e = public_numbers.e
        pycrypto_key = RSA.construct((n, e))
        
        print(f"🔐 Loaded robot public key: {crypto_key.key_size} bits")
        
        # Step 6: Generate AES key and encrypt SDP
        aes_key = generate_aes_key()
        encrypted_sdp = aes_encrypt(offer.sdp, aes_key)
        encrypted_aes_key = rsa_encrypt(aes_key, pycrypto_key)
        
        print(f"🔒 Encrypted SDP: {len(encrypted_sdp)} chars")
        print(f"🔒 Encrypted AES key: {len(encrypted_aes_key)} chars")
        
        # Step 7: Send encrypted SDP to robot
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
            timeout=10
        )
        
        if encrypted_response.status_code == 200:
            print("✅ Encrypted SDP sent successfully!")
            print(f"📦 Response: {encrypted_response.text[:100]}...")
            
            # Step 8: Decrypt robot's SDP answer
            try:
                decrypted_answer = aes_decrypt(encrypted_response.text, aes_key)
                print(f"🎉 Decrypted SDP answer: {decrypted_answer[:200]}...")
                
                # Step 9: Set remote description
                if 'v=' in decrypted_answer and 'm=' in decrypted_answer:
                    answer = RTCSessionDescription(sdp=decrypted_answer, type="answer")
                    await pc.setRemoteDescription(answer)
                    print("✅ Set remote description!")
                    
                    # Step 10: Wait for connection
                    print("⏳ Waiting for WebRTC connection...")
                    for i in range(15):
                        await asyncio.sleep(1)
                        print(f"⏱️  Step {i+1}: Connection={pc.connectionState}, ICE={pc.iceConnectionState}")
                        
                        if pc.connectionState == "connected":
                            print("🎉 WEBRTC CONNECTION ESTABLISHED!")
                            await asyncio.sleep(5)  # Keep connection alive briefly
                            break
                        elif pc.connectionState in ["failed", "closed"]:
                            print(f"❌ Connection failed: {pc.connectionState}")
                            break
                else:
                    print("❌ Response doesn't look like valid SDP")
                    
            except Exception as decrypt_error:
                print(f"❌ Could not decrypt response: {decrypt_error}")
                
        else:
            print(f"❌ Encrypted SDP request failed: {encrypted_response.status_code}")
            print(f"Error: {encrypted_response.text}")
            
    except Exception as e:
        print(f"❌ Handshake failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await pc.close()
        print("🔚 Connection closed")

if __name__ == "__main__":
    asyncio.run(complete_webrtc_handshake())