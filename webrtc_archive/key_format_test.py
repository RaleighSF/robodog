#!/usr/bin/env python3
"""
Test different RSA public key formats with the robot
Based on your specification: try one format at a time, single field per request
"""
import asyncio
import json
import base64
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from aiortc import RTCPeerConnection, RTCRtpSender

# Configuration
ROBOT_IP = "192.168.86.22"
ROBOT_SN = "B42D4000P6PC04GE"
TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4QjRDODIyM0JGREZENUJBIiwiaWF0IjoxNzI0MjkxNDkwLCJhcHBfaWQiOiJZRjNVSTJTOE44SjJHVUJNIiwicHJvZHVjdF9pZCI6Imdvb19zbjhqM2dtdWJtOWZzamYzaGF1ZG1kIiwib3Blbl9pZCI6IjE3MjQyOTE0OTAyNjcxNjA2NzMifQ.OJV8qJ7MX7yOFzLzOsckLLfHBIZ4XJ5YI0UHXzQP-M_yXjYJILw8f4d23VyJpxYHCzKw4wYOCiI6OxrFJrqp5zIEd2F2Z3aQWQ-Qs4M3vOw95O4FUJLzK8b7VR3ckZIxfXTYJ-QO5ZNJFzZkQ_J9O4XzZ-VQ5O2cKYZ8J_zQ"

def generate_test_keypair():
    """Generate RSA keypair for testing different formats"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    public_key = private_key.public_key()
    
    # A) PEM PKCS#1 format
    try:
        # PKCS#1 is RSA-specific format
        pkcs1_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.PKCS1
        ).decode('utf-8')
    except ValueError:
        # If PKCS#1 not directly available, construct it manually
        pkcs1_pem = "-----BEGIN RSA PUBLIC KEY-----\\nMIIBCgKCAQ...==\\n-----END RSA PUBLIC KEY-----\\n"
    
    # B) PEM PKCS#8 format (SubjectPublicKeyInfo)
    pkcs8_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')
    
    # C) DER base64 format
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    der_b64 = base64.b64encode(der_bytes).decode('utf-8')
    
    # D) JWK format
    # Extract n and e values for JWK
    public_numbers = public_key.public_numbers()
    n = public_numbers.n
    e = public_numbers.e
    
    # Convert to base64url (JWK format)
    import struct
    n_bytes = n.to_bytes((n.bit_length() + 7) // 8, byteorder='big')
    e_bytes = e.to_bytes((e.bit_length() + 7) // 8, byteorder='big')
    
    n_b64 = base64.urlsafe_b64encode(n_bytes).decode('utf-8').rstrip('=')
    e_b64 = base64.urlsafe_b64encode(e_bytes).decode('utf-8').rstrip('=')
    
    jwk = {
        "kty": "RSA",
        "n": n_b64,
        "e": e_b64
    }
    
    return {
        "private_key": private_key,
        "formats": {
            "pkcs1_pem": pkcs1_pem,
            "pkcs8_pem": pkcs8_pem, 
            "der_b64": der_b64,
            "jwk": jwk
        }
    }

def munge_sdp(s):
    """Clean SDP to remove unsupported extensions"""
    out = []
    for ln in s.splitlines():
        if ln.startswith("a=extmap-allow-mixed"): continue
        if ln.startswith("a=simulcast:"): continue
        if ln.startswith("a=rid:"): continue
        if "ulpfec" in ln or "red/90000" in ln: continue
        out.append(ln)
    return "\r\n".join(out) + "\r\n"

async def create_test_offer():
    """Create WebRTC offer for testing"""
    pc = RTCPeerConnection()
    v = pc.addTransceiver("video", direction="recvonly")
    
    # Set H.264 codec preferences
    caps = RTCRtpSender.getCapabilities("video")
    h264_codecs = [c for c in caps.codecs if "H264" in c.mimeType]
    v.setCodecPreferences(h264_codecs)
    
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    munged_sdp = munge_sdp(pc.localDescription.sdp)
    
    return pc, munged_sdp

async def test_key_format(format_name, key_field, key_value, munged_sdp):
    """Test a specific key format with the robot"""
    print(f"\n🔑 Testing {format_name}")
    print("=" * 50)
    
    # Build payload with ONLY the specified key field
    body = {
        "type": "offer",
        "sdp": munged_sdp,
        "codec": "h264",
        "protocol": "udp", 
        "client": "custom",
        "version": "1.1",
        key_field: key_value  # Single key field as specified
    }
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "User-Agent": "UnitreeGo/1.1",
        "X-Device-Id": ROBOT_SN
    }
    
    print(f"📤 Sending {key_field}: {str(key_value)[:100]}{'...' if len(str(key_value)) > 100 else ''}")
    
    try:
        # Send request
        resp = requests.post(
            f"http://{ROBOT_IP}:9991/con_notify",
            headers=headers,
            json=body,
            verify=False,
            timeout=10
        )
        
        print(f"📬 Response status: {resp.status_code}")
        
        if resp.status_code == 200:
            # Parse response
            try:
                # Try direct JSON first
                payload = resp.json()
            except:
                # Try nested base64 JSON
                response_data = base64.b64decode(resp.text).decode('utf-8')
                payload = json.loads(response_data)
            
            print(f"📋 Response keys: {list(payload.keys())}")
            
            # Analyze response
            if 'data1' in payload and 'data2' in payload:
                d1_len = len(payload['data1']) if isinstance(payload['data1'], str) else 'N/A'
                d2_val = payload['data2']
                print(f"📦 data1 length: {d1_len}, data2 value: {d2_val}")
                
                # Check if this format produced different response
                if isinstance(payload['data2'], int) and payload['data2'] != 2:
                    print(f"🎉 DIFFERENT RESPONSE! data2 = {payload['data2']} (not the usual 2)")
                    return True, payload
                elif not isinstance(payload['data1'], str):
                    print(f"🎉 DIFFERENT FORMAT! data1 type = {type(payload['data1'])}")
                    return True, payload
                else:
                    print("📝 Standard response format (data1=string, data2=2)")
                    return False, payload
            else:
                print(f"🎉 DIFFERENT STRUCTURE! Keys: {list(payload.keys())}")
                return True, payload
                
        else:
            print(f"❌ HTTP Error {resp.status_code}: {resp.text[:200]}")
            return False, None
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False, None

async def main():
    """Test all key formats systematically"""
    print("🔑 RSA Public Key Format Testing")
    print("=" * 50)
    
    # Generate test keypair
    key_data = generate_test_keypair()
    formats = key_data["formats"]
    
    # Create WebRTC offer
    pc, munged_sdp = await create_test_offer()
    
    print(f"📄 SDP offer ready ({len(munged_sdp)} chars)")
    
    # Test formats as specified in the image
    test_cases = [
        ("PEM PKCS#1", "pubkey_pem_pkcs1", formats["pkcs1_pem"]),
        ("PEM PKCS#8", "pubkey_pem", formats["pkcs8_pem"]),  
        ("DER base64", "pubkey_der_b64", formats["der_b64"]),
        ("JWK", "pubkey_jwk", formats["jwk"])
    ]
    
    results = []
    
    for format_name, key_field, key_value in test_cases:
        success, response = await test_key_format(format_name, key_field, key_value, munged_sdp)
        results.append((format_name, success, response))
        
        # Small delay between tests
        await asyncio.sleep(2)
    
    # Summary
    print("\n🎯 TEST RESULTS SUMMARY")
    print("=" * 50)
    
    successful_formats = []
    
    for format_name, success, response in results:
        status = "✅ Different response" if success else "📝 Standard response"
        print(f"{format_name:15} | {status}")
        
        if success:
            successful_formats.append((format_name, response))
    
    if successful_formats:
        print(f"\n🎉 Found {len(successful_formats)} format(s) with different responses!")
        for format_name, response in successful_formats:
            print(f"\n🔑 {format_name} response:")
            print(json.dumps(response, indent=2)[:500] + "...")
    else:
        print("\n📝 All formats returned standard response (data1=string, data2=2)")
        print("💡 This suggests the robot accepts any format but uses its own key for encryption")
    
    await pc.close()

if __name__ == "__main__":
    asyncio.run(main())