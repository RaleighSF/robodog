#!/usr/bin/env python3
"""
Debug the decryption process step by step
"""
import json
import base64
from Crypto.Cipher import AES

# Sample robot response from our tests
sample_response = "eyJkYXRhMSI6IndIVlBtblVaWTd6UHZMSGNoM01PdG1NRXp4U0lDWFExWDZsN0RiMjBwZmV2NVlXbTA3dnNna3ZvYnJ5Zm5pSXZZMWJ6SmtVQ1ZwOXkzaHQvSFRjbzBZRjdWSlZQK2N6WDdEOUdjMk4yZk5lcDNoK0U2ZjVRRzlIM1QzUURRanNFeVZnVHRrNHlZdWNGaG04MFR2ald4SU5jM1p3UGJPZmtmcCtkS1k2V3JvaXhzRUJUdnE4ZVlNOVVNZGdPSG1GcS9wcGlWWkEvS2doVXM5N1V5cGx3aXc9PSIsImRhdGEyIjoiOVRLYVFGOVJUZGdlSnNFOC9zRExNV3Z6L2ZONmU1d3VGZTRSR2pGaGRrSUNGeVRkbmhqV0V2VU4reDZybTY4Ry9GQndtRXBLZTlkNFZ5cWNqelY4VzNPRW5qQnVSSi9pUzZGdnFGUlVpWXdtMWFGWHpOdHdscGI5azZJdStBOWdMdkwyR1pRR3kwQkJNa2k5Mmt1MUNJZjQxR1JZc1FVWER0NzJRSXpucnNJUWpnK2pZbW0wdU1NVDllSjJnZC9tRXo2RjBLdWRQTE9QVUFwRGFFTllMNzJPTHBOVWx6UT09In0="

print("🧪 Debug Decryption Process")
print("=" * 50)

# Step 1: Base64 decode the response
print("Step 1: Base64 decode response...")
try:
    decoded = base64.b64decode(sample_response)
    print(f"✅ Decoded: {len(decoded)} bytes")
    
    # Try to parse as JSON
    response_text = decoded.decode('utf-8')
    print(f"📄 Response text: {response_text[:100]}...")
    
    response_json = json.loads(response_text)
    print(f"📋 JSON keys: {list(response_json.keys())}")
    
    # Extract data1
    data1 = response_json['data1']
    print(f"🔍 data1 length: {len(data1)} characters")
    print(f"🔍 data1 preview: {data1[:100]}...")
    
    # Step 2: Base64 decode data1
    print("\nStep 2: Base64 decode data1...")
    try:
        data1_decoded = base64.b64decode(data1)
        print(f"✅ data1 decoded: {len(data1_decoded)} bytes")
        print(f"📄 Raw bytes: {data1_decoded[:50]}")
        
        # Step 3: Try different decryption methods on data1
        print("\nStep 3: Try decryption methods on data1...")
        
        # Method A: Direct UTF-8 decode
        try:
            direct_text = data1_decoded.decode('utf-8', errors='ignore')
            print(f"📝 Direct decode: {direct_text[:100]}...")
            if "v=" in direct_text or "m=" in direct_text:
                print("🎉 Found SDP in direct decode!")
        except Exception as e:
            print(f"⚠️ Direct decode failed: {e}")
        
        # Method B: XOR/Shift cipher
        print("\n🔍 Trying XOR/shift on data1...")
        for shift in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]:
            try:
                shifted = bytes([(b - shift) % 256 for b in data1_decoded])
                text = shifted.decode('utf-8', errors='ignore')
                
                # Check if this looks like SDP
                if "v=" in text and ("m=video" in text or "m=audio" in text):
                    print(f"🎉 XOR shift {shift} SUCCESS!")
                    print(f"📝 SDP content: {text[:200]}...")
                    break
                elif "v=" in text or "m=" in text:
                    print(f"🔍 XOR shift {shift} partial match: {text[:50]}...")
                elif len([c for c in text[:50] if c.isprintable()]) > 40:
                    print(f"📄 XOR shift {shift} readable: {text[:50]}...")
                    
            except Exception:
                pass
        
        # Method C: AES decryption attempts with comprehensive approach
        print("\n🔐 Trying comprehensive AES decryption on data1...")
        if len(data1_decoded) >= 32:  # Need at least 16 bytes IV + 16 bytes data
            # Try different ways to derive the key
            potential_keys = [
                b'1234567890123456',  # Simple test key
                b'unitreego2robot0',  # Robot name based
                b'webrtcgo2unitree',  # WebRTC + robot
                b'go2webrtc1234567',  # Library name based
                b'B42D4000P6PC04GE',  # Device ID (truncated to 16)
                b'192.168.86.22****',  # IP based (padded)
            ]
            
            # Also try deriving key from our JWT token or other sources
            jwt_key = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"[:16]
            potential_keys.append(jwt_key.encode())
            
            for key in potential_keys:
                if len(key) != 16:
                    # Pad or truncate to 16 bytes
                    if len(key) < 16:
                        key = key + b'0' * (16 - len(key))
                    else:
                        key = key[:16]
                
                for iv_method in ['first16', 'zero', 'last16']:
                    try:
                        if iv_method == 'first16':
                            iv = data1_decoded[:16]
                            encrypted_data = data1_decoded[16:]
                        elif iv_method == 'zero':
                            iv = b'\x00' * 16
                            encrypted_data = data1_decoded
                        else:  # last16
                            iv = data1_decoded[-16:]
                            encrypted_data = data1_decoded[:-16]
                        
                        # Skip if not enough data
                        if len(encrypted_data) < 16:
                            continue
                            
                        # Make sure encrypted_data is multiple of 16 bytes
                        if len(encrypted_data) % 16 != 0:
                            encrypted_data = encrypted_data[:-(len(encrypted_data) % 16)]
                        
                        cipher = AES.new(key, AES.MODE_CBC, iv)
                        decrypted = cipher.decrypt(encrypted_data)
                        
                        # Try with and without padding removal
                        for try_unpad in [True, False]:
                            try:
                                if try_unpad:
                                    from Crypto.Util.Padding import unpad
                                    final_data = unpad(decrypted, AES.block_size)
                                else:
                                    final_data = decrypted
                                
                                text = final_data.decode('utf-8', errors='ignore')
                                
                                # Check for SDP content
                                if "v=" in text and ("m=" in text or "o=" in text):
                                    print(f"🎉 AES SUCCESS! Key: {key}, IV: {iv_method}, Unpad: {try_unpad}")
                                    print(f"📝 SDP: {text[:300]}...")
                                    exit(0)  # Found it!
                                    
                                # Check for any meaningful content
                                elif len([c for c in text[:50] if c.isprintable()]) > 30:
                                    print(f"📄 AES partial ({key[:8]}, {iv_method}): {text[:50]}...")
                                    
                            except Exception:
                                pass
                                
                    except Exception as e:
                        if "key" not in str(e).lower():  # Don't spam key length errors
                            print(f"⚠️ AES error with key {key[:8]}: {e}")
        
        # Method D: Try other symmetric ciphers
        print("\n🔓 Trying other decryption methods...")
        try:
            from Crypto.Cipher import DES, Blowfish
            
            # Try simple Caesar cipher with various shifts
            for shift in range(1, 26):
                try:
                    shifted = bytes([(b + shift) % 256 for b in data1_decoded])
                    text = shifted.decode('utf-8', errors='ignore')
                    if "v=" in text and "m=" in text:
                        print(f"🎉 Caesar cipher SUCCESS with shift +{shift}!")
                        print(f"📝 Result: {text[:200]}...")
                        break
                except:
                    pass
            
            # Try reverse Caesar cipher  
            for shift in range(1, 26):
                try:
                    shifted = bytes([(b - shift) % 256 for b in data1_decoded])
                    text = shifted.decode('utf-8', errors='ignore')
                    if "v=" in text and "m=" in text:
                        print(f"🎉 Reverse Caesar cipher SUCCESS with shift -{shift}!")
                        print(f"📝 Result: {text[:200]}...")
                        break
                except:
                    pass
        
        except ImportError:
            print("⚠️ Additional crypto libraries not available")
        
    except Exception as e:
        print(f"❌ data1 base64 decode failed: {e}")
        print(f"🔍 Trying direct XOR on data1 string...")
        
        # Try XOR on the base64 string itself
        for shift in range(1, 10):
            try:
                shifted_b64 = ''.join([chr((ord(c) - shift) % 256) for c in data1])
                # Try to decode the shifted base64
                try:
                    decoded_shifted = base64.b64decode(shifted_b64)
                    text = decoded_shifted.decode('utf-8', errors='ignore')
                    if "v=" in text or "m=" in text:
                        print(f"🎉 Base64 string shift {shift} SUCCESS!")
                        print(f"📝 Result: {text[:200]}...")
                        break
                except:
                    pass
            except:
                pass

except Exception as e:
    print(f"❌ Initial base64 decode failed: {e}")

print("\n" + "=" * 50)
print("Debug complete.")