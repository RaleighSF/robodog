#!/usr/bin/env python3
"""
Standalone test to verify robot communication and decryption
This bypasses all the complex patching to directly test the core functionality
"""
import os
import requests
import json
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

# Robot details
ROBOT_IP = "192.168.86.22"
TOKEN = os.environ.get("UNITREE_TOKEN", "")

def decrypt_robot_data(encrypted_data):
    """Decrypt robot response data using various methods"""
    print(f"🔓 Attempting to decrypt {len(encrypted_data)} characters...")
    
    try:
        # First decode base64
        decoded_data = base64.b64decode(encrypted_data)
        print(f"✅ Base64 decoded: {len(decoded_data)} bytes")
        
        # Method 1: Try direct text decode (maybe not encrypted)
        try:
            text = decoded_data.decode('utf-8', errors='ignore')
            if "v=" in text or "m=" in text or "answer" in text.lower():
                print("🎉 Found plaintext SDP!")
                return text
            else:
                print(f"📄 Plaintext: {text[:100]}...")
        except Exception as e:
            print(f"⚠️ Plaintext decode failed: {e}")
        
        # Method 2: Try JSON parsing
        try:
            text = decoded_data.decode('utf-8', errors='ignore') 
            json_data = json.loads(text)
            print(f"📋 JSON data keys: {list(json_data.keys())}")
            
            # Look for SDP in JSON
            for key, value in json_data.items():
                if isinstance(value, str) and ("v=" in value or "m=" in value):
                    print(f"🎉 Found SDP in JSON key '{key}'!")
                    return value
        except Exception as e:
            print(f"⚠️ JSON parsing failed: {e}")
        
        # Method 3: Try AES decryption with various approaches
        try:
            if len(decoded_data) > 16:
                # Try different key possibilities with proper lengths
                keys_to_try = [
                    b'1234567890123456',  # 16-byte test key
                    b'unitreego2robot',   # 16-byte robot key  
                    b'webrtc1234567890',  # 16-byte WebRTC key
                    b'go2webrtc12345678', # 16-byte go2 key
                ]
                
                for key in keys_to_try:
                    try:
                        # Try different IV/data splits
                        splits_to_try = [
                            (decoded_data[:16], decoded_data[16:]),  # Standard IV + data
                            (decoded_data[:12], decoded_data[12:]),  # 12-byte IV
                            (b'\x00' * 16, decoded_data),           # Zero IV
                        ]
                        
                        for iv, encrypted in splits_to_try:
                            try:
                                if len(iv) < 16:
                                    iv = iv + b'\x00' * (16 - len(iv))  # Pad IV to 16 bytes
                                
                                cipher = AES.new(key, AES.MODE_CBC, iv[:16])
                                decrypted = cipher.decrypt(encrypted)
                                
                                # Try with and without padding removal
                                for remove_padding in [True, False]:
                                    try:
                                        if remove_padding:
                                            final_data = unpad(decrypted, AES.block_size)
                                        else:
                                            final_data = decrypted
                                        
                                        decrypted_text = final_data.decode('utf-8', errors='ignore')
                                        
                                        if "v=" in decrypted_text or "m=" in decrypted_text or "answer" in decrypted_text.lower():
                                            print(f"🎉 AES decryption successful with key: {key}, IV: {len(iv)} bytes, padding: {remove_padding}")
                                            return decrypted_text
                                        elif len(decrypted_text) > 10 and decrypted_text.isprintable():
                                            print(f"📄 AES result ({key}): {decrypted_text[:50]}...")
                                    except Exception:
                                        pass
                            except Exception as se:
                                pass
                    except Exception as ke:
                        print(f"⚠️ Key {key} failed: {ke}")
        except Exception as e:
            print(f"⚠️ AES decryption failed: {e}")
        
        # Method 4: Try simple XOR or shift decoding 
        try:
            # Sometimes encryption is just base64 + simple shift
            for shift in range(1, 256):
                try:
                    shifted = bytes([(b - shift) % 256 for b in decoded_data])
                    text = shifted.decode('utf-8', errors='ignore')
                    
                    # Check for meaningful content
                    if ("v=" in text or "m=" in text or "answer" in text.lower() or 
                        "sdp" in text.lower() or "type" in text.lower()):
                        print(f"🎉 XOR/Shift decryption successful with shift: {shift}")
                        print(f"📝 First 200 chars: {text[:200]}...")
                        return text
                    
                    # Also try double-decode for nested encoding
                    if text.startswith('{"') or text.startswith('eyJ'):
                        try:
                            # Try JSON parsing the shifted result
                            if text.startswith('{"'):
                                inner_json = json.loads(text)
                                print(f"🔍 Shift {shift} gives JSON: {list(inner_json.keys())}")
                                # Look for SDP in inner JSON
                                for k, v in inner_json.items():
                                    if isinstance(v, str) and ("v=" in v or "m=" in v):
                                        print(f"🎉 Found SDP in nested JSON key '{k}' with shift {shift}!")
                                        return v
                                    elif isinstance(v, str) and len(v) > 50:
                                        # Try decoding the inner value
                                        try:
                                            inner_decoded = base64.b64decode(v).decode('utf-8', errors='ignore')
                                            if "v=" in inner_decoded or "m=" in inner_decoded:
                                                print(f"🎉 Found nested base64 SDP with shift {shift}!")
                                                return inner_decoded
                                        except:
                                            pass
                        except:
                            pass
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ XOR decryption failed: {e}")
        
        # Method 5: Try looking at the actual data1 value from JSON
        try:
            text = decoded_data.decode('utf-8', errors='ignore')
            if text.startswith('{"data1"'):
                json_data = json.loads(text)
                if 'data1' in json_data:
                    data1_value = json_data['data1']
                    print(f"🔍 Trying to decrypt data1 value directly: {len(data1_value)} chars")
                    
                    # Try decoding data1 as base64
                    try:
                        data1_decoded = base64.b64decode(data1_value)
                        print(f"✅ data1 base64 decoded: {len(data1_decoded)} bytes")
                        
                        # Try XOR/shift on data1
                        for shift in range(1, 256):
                            try:
                                shifted = bytes([(b - shift) % 256 for b in data1_decoded])
                                text_result = shifted.decode('utf-8', errors='ignore')
                                if ("v=" in text_result or "m=" in text_result or 
                                    "answer" in text_result.lower() or "sdp" in text_result.lower()):
                                    print(f"🎉 data1 XOR decryption successful with shift: {shift}")
                                    print(f"📝 Result: {text_result[:200]}...")
                                    return text_result
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"⚠️ data1 base64 decode failed: {e}")
        except Exception as e:
            print(f"⚠️ data1 extraction failed: {e}")
        
        print("❌ All decryption methods failed")
        return None
        
    except Exception as e:
        print(f"❌ Base64 decode failed: {e}")
        return None

def test_robot_communication():
    """Test direct communication with robot"""
    print("🤖 Testing direct robot communication...")
    
    # Simple SDP offer for testing
    test_sdp = """v=0
o=- 123456789 123456789 IN IP4 192.168.86.23
s=-
t=0 0
m=video 9 UDP/TLS/RTP/SAVPF 99
c=IN IP4 192.168.86.23
a=rtcp:9 IN IP4 192.168.86.23
a=ice-ufrag:test
a=ice-pwd:testpassword
a=fingerprint:sha-256 AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99
a=setup:actpass
a=mid:0
a=sendrecv
a=rtcp-mux
a=rtpmap:99 H264/90000
"""

    # Structured payload like we've been using
    payload = {
        "type": "offer",
        "sdp": test_sdp,
        "client": "custom",
        "version": "1.1",
        "codec": "h264",
        "protocol": "udp"
    }
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "X-Device-Id": "B42D4000P6PC04GE",
        "User-Agent": "UnitreeGo/1.1"
    }
    
    try:
        print("📡 Sending test SDP to robot...")
        response = requests.post(
            f"http://{ROBOT_IP}:9991/con_notify",
            headers=headers,
            json=payload,
            timeout=10
        )
        
        print(f"📬 Response status: {response.status_code}")
        print(f"📄 Response text length: {len(response.text)}")
        print(f"📄 Response preview: {response.text[:200]}...")
        
        if response.status_code == 200:
            # Try to parse as JSON first
            try:
                response_json = json.loads(response.text)
                print(f"📋 Response JSON keys: {list(response_json.keys())}")
                
                # Look for encrypted data
                for key, value in response_json.items():
                    if isinstance(value, str) and len(value) > 50:
                        print(f"🔍 Key '{key}': {len(value)} chars, testing decryption...")
                        decrypted = decrypt_robot_data(value)
                        if decrypted:
                            print(f"🎉 Successfully decrypted {key}!")
                            print(f"📝 Decrypted content: {decrypted[:200]}...")
                            return True
            except json.JSONDecodeError:
                print("📄 Response is not JSON, trying direct decryption...")
                decrypted = decrypt_robot_data(response.text)
                if decrypted:
                    print("🎉 Successfully decrypted direct response!")
                    print(f"📝 Decrypted content: {decrypted[:200]}...")
                    return True
        
        print("❌ No decryption success")
        return False
        
    except Exception as e:
        print(f"❌ Communication error: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Standalone Robot Decryption Test")
    print("=" * 50)
    
    success = test_robot_communication()
    
    if success:
        print("\n🎉 SUCCESS: Robot communication and decryption working!")
    else:
        print("\n❌ FAILED: Could not decrypt robot response")
    
    print("\n" + "=" * 50)
    print("Test complete.")