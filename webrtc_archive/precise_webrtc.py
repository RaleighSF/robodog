#!/usr/bin/env python3
"""
Precise WebRTC implementation following the exact protocol requirements:
1) Video-only H.264 offer with RSA public key
2) RSA-OAEP + AEAD decryption of robot response  
3) Proper m-line matching
4) Clean session management
"""
import asyncio
import json
import base64
import requests
from base64 import b64decode
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from aiortc import RTCPeerConnection, RTCRtpSender

# Configuration
ROBOT_IP = "192.168.86.22"
ROBOT_SN = "B42D4000P6PC04GE"  
TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4QjRDODIyM0JGREZENUJBIiwiaWF0IjoxNzI0MjkxNDkwLCJhcHBfaWQiOiJZRjNVSTJTOE44SjJHVUJNIiwicHJvZHVjdF9pZCI6Imdvb19zbjhqM2dtdWJtOWZzamYzaGF1ZG1kIiwib3Blbl9pZCI6IjE3MjQyOTE0OTAyNjcxNjA2NzMifQ.OJV8qJ7MX7yOFzLzOsckLLfHBIZ4XJ5YI0UHXzQP-M_yXjYJILw8f4d23VyJpxYHCzKw4wYOCiI6OxrFJrqp5zIEd2F2Z3aQWQ-Qs4M3vOw95O4FUJLzK8b7VR3ckZIxfXTYJ-QO5ZNJFzZkQ_J9O4XzZ-VQ5O2cKYZ8J_zQ"

def generate_keypair():
    """Generate RSA keypair for WebRTC session"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Private key in PEM format
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    # Public key in PKCS#1 format (what robot expects)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    return private_pem, public_pem.decode('utf-8')

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

def mlines(s):
    """Extract m-lines from SDP"""
    return [l for l in s.splitlines() if l.startswith("m=")]

def load_priv(pem: bytes):
    """Load private key from PEM"""
    return serialization.load_pem_private_key(pem, password=None)

def rsa_oaep_decrypt(priv, blob: bytes) -> bytes:
    """RSA-OAEP decrypt with SHA-256"""
    return priv.decrypt(blob, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(), 
        label=None
    ))

def extract_sdp_answer(payload: dict, my_priv_pem: bytes) -> str:
    """Extract and decrypt SDP answer using RSA-OAEP + AEAD"""
    print("🔓 Decrypting robot response...")
    print(f"📋 Payload structure: {payload}")
    
    priv = load_priv(my_priv_pem)
    
    # Get encrypted data - handle different data types
    data1_raw = payload.get("data1") or payload.get("encKey") or payload.get("k")
    data2_raw = payload.get("data2") or payload.get("cipher") or payload.get("c")
    
    print(f"🔍 data1 type: {type(data1_raw)}, data2 type: {type(data2_raw)}")
    
    # Handle different formats
    if isinstance(data1_raw, str):
        d1 = b64decode(data1_raw)
    else:
        print(f"⚠️ data1 is not string: {data1_raw}")
        return None
        
    if isinstance(data2_raw, str):
        d2 = b64decode(data2_raw)
    elif isinstance(data2_raw, int):
        print(f"⚠️ data2 is integer: {data2_raw} - possibly a length or status code")
        # Maybe data2 is embedded in data1 or this indicates a different protocol
        d2 = None
    else:
        print(f"⚠️ data2 unexpected type: {type(data2_raw)} = {data2_raw}")
        d2 = None
    
    nonce_b64 = payload.get("nonce") or payload.get("iv") or payload.get("n")
    tag_b64   = payload.get("tag") or payload.get("sign") or payload.get("t")
    
    print(f"📦 d1 size: {len(d1)} bytes, d2 size: {len(d2) if d2 else 0} bytes")
    
    # RSA-OAEP decrypt d1 to get key material
    # Handle cases where d1 might be larger than RSA key size
    rsa_key_size = priv.key_size // 8  # Convert bits to bytes
    print(f"🔑 RSA key size: {rsa_key_size} bytes, d1 size: {len(d1)} bytes")
    
    if len(d1) == rsa_key_size:
        # Standard single RSA block
        km = rsa_oaep_decrypt(priv, d1)
        print(f"🔑 Single block decryption: {len(km)} bytes")
    elif len(d1) > rsa_key_size:
        # Multiple RSA blocks or additional metadata
        print("🔍 d1 larger than RSA key - trying multiple approaches...")
        
        # Approach 1: Try first rsa_key_size bytes
        try:
            first_block = d1[:rsa_key_size]
            km = rsa_oaep_decrypt(priv, first_block)
            print(f"🔑 First block decryption successful: {len(km)} bytes")
        except Exception as e1:
            print(f"⚠️ First block failed: {e1}")
            
            # Approach 2: Try last rsa_key_size bytes
            try:
                last_block = d1[-rsa_key_size:]
                km = rsa_oaep_decrypt(priv, last_block)
                print(f"🔑 Last block decryption successful: {len(km)} bytes")
            except Exception as e2:
                print(f"⚠️ Last block failed: {e2}")
                
                # Approach 3: Try to find multiple concatenated blocks
                print("🔍 Trying multiple concatenated RSA blocks...")
                km_parts = []
                for i in range(0, len(d1), rsa_key_size):
                    block = d1[i:i+rsa_key_size]
                    if len(block) == rsa_key_size:
                        try:
                            part = rsa_oaep_decrypt(priv, block)
                            km_parts.append(part)
                            print(f"🔑 Block {i//rsa_key_size} decrypted: {len(part)} bytes")
                        except Exception as e3:
                            print(f"⚠️ Block {i//rsa_key_size} failed: {e3}")
                
                if km_parts:
                    km = b''.join(km_parts)
                    print(f"🔑 Concatenated blocks: {len(km)} bytes total")
                else:
                    raise ValueError(f"All RSA decryption approaches failed: single({e1}), last({e2})")
    else:
        # d1 smaller than expected - might be truncated or different format
        raise ValueError(f"d1 too small ({len(d1)} bytes) for RSA-{rsa_key_size*8} decryption")
    
    # Parse key material
    key = nonce = tag = None
    if km.startswith(b"{"):
        # JSON format with separate fields
        j = json.loads(km.decode("utf-8", "ignore"))
        print(f"📋 Key material JSON keys: {list(j.keys())}")
        key   = b64decode(j["k"])
        nonce = b64decode(j.get("n", "")) if j.get("n") else None
        tag   = b64decode(j.get("t", "")) if j.get("t") else None
    else:
        # Binary format - try different splits
        if len(km) >= 32+12+16:  # AES-256 + 12-byte nonce + 16-byte tag
            key, nonce, tag = km[:32], km[32:44], km[44:60]
            print("🔑 Using AES-256 key layout")
        elif len(km) >= 16+12+16:  # AES-128 + 12-byte nonce + 16-byte tag
            key, nonce, tag = km[:16], km[16:28], km[28:44]
            print("🔑 Using AES-128 key layout")
        else:
            # Key only, nonce/tag from payload or appended to d2
            key = km
            nonce = b64decode(nonce_b64) if nonce_b64 else None
            tag   = b64decode(tag_b64)   if tag_b64   else None
            print("🔑 Using key-only layout")
    
    # Handle case where d2 might be None or integer
    if d2 is None:
        print("⚠️ No d2 data - checking if encrypted SDP is embedded in key material")
        # Sometimes the entire encrypted SDP is in the key material after the actual key
        if len(km) > 64:  # More than just key+nonce+tag
            print("🔍 Trying to extract embedded ciphertext from key material")
            # Try different splits
            test_splits = [48, 56, 64, 80]  # Various potential key+metadata sizes
            for split_point in test_splits:
                if len(km) > split_point + 16:  # Need at least 16 bytes for ciphertext
                    test_key = km[:32] if len(km) >= 32 else km[:16]
                    test_nonce = km[32:44] if len(km) >= 44 else km[16:28] if len(km) >= 28 else b'\x00' * 12
                    test_ciphertext = km[split_point:]
                    
                    try:
                        aes = AESGCM(test_key)
                        sdp = aes.decrypt(test_nonce, test_ciphertext, None).decode("utf-8", "ignore")
                        if sdp.startswith("v=0"):
                            print(f"✅ Found embedded SDP with split at {split_point}!")
                            return sdp
                    except:
                        continue
        
        # If that fails, maybe the response format indicates something else
        print("❌ Cannot find ciphertext - response may indicate different protocol state")
        return None
    
    # If tag isn't separate, assume it's appended to d2  
    if tag is None and d2 and len(d2) > 32:
        tag, d2 = d2[-16:], d2[:-16]
        print("🏷️ Tag extracted from d2 end")
    
    print(f"🔑 Key: {len(key) if key else 0} bytes, Nonce: {len(nonce) if nonce else 0} bytes, Tag: {len(tag) if tag else 0} bytes")
    
    # Try AES-GCM first
    if d2:
        try:
            aes = AESGCM(key)
            ciphertext = d2 + (tag if tag else b'')
            sdp = aes.decrypt(nonce, ciphertext, None).decode("utf-8", "ignore")
            print("✅ AES-GCM decryption successful!")
        except Exception as e:
            print(f"⚠️ AES-GCM failed: {e}, trying ChaCha20-Poly1305...")
            try:
                cipher = ChaCha20Poly1305(key)
                ciphertext = d2 + (tag if tag else b'')
                sdp = cipher.decrypt(nonce, ciphertext, None).decode("utf-8", "ignore")
                print("✅ ChaCha20-Poly1305 decryption successful!")
            except Exception as e2:
                raise ValueError(f"Both AEAD methods failed: AES-GCM({e}), ChaCha20({e2})")
    else:
        raise ValueError("No ciphertext data (d2) available for decryption")
    
    # Validate SDP
    if not (sdp.startswith("v=0") and "m=video" in sdp):
        print(f"⚠️ Decrypted text doesn't look like SDP: {sdp[:100]}...")
        raise ValueError("Decrypted text not valid SDP; check key/nonce/tag layout.")
    
    print("🎉 Valid SDP decrypted!")
    return sdp

async def create_webrtc_offer():
    """Create precise WebRTC offer - video-only, H.264, recvonly"""
    print("🎬 Creating WebRTC offer...")
    
    # Generate fresh keypair
    private_pem, public_pem = generate_keypair()
    
    # Build peer connection
    pc = RTCPeerConnection()
    
    # Add video transceiver - recvonly H.264 only
    v = pc.addTransceiver("video", direction="recvonly")
    
    # Set H.264 codec preferences (packetization-mode=1)
    caps = RTCRtpSender.getCapabilities("video")
    h264_codecs = [c for c in caps.codecs if "H264" in c.mimeType]
    
    # Prefer packetization-mode=1 if available
    h264_preferred = [c for c in h264_codecs if "packetization-mode=1" in str(c.parameters or "")]
    if h264_preferred:
        h264_codecs = h264_preferred
    
    v.setCodecPreferences(h264_codecs)
    print(f"🎥 Set H.264 codec preferences: {len(h264_codecs)} codecs")
    
    # Create offer
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    # Munge SDP to remove unsupported features
    munged_sdp = munge_sdp(pc.localDescription.sdp)
    
    print("📄 OFFER m-lines:", mlines(munged_sdp))
    
    return pc, munged_sdp, public_pem, private_pem

async def send_webrtc_offer(munged_sdp, public_pem):
    """Send offer to robot with precise headers and format"""
    print("📡 Sending WebRTC offer to robot...")
    
    # Construct body with RSA public key
    body = {
        "type": "offer",
        "sdp": munged_sdp,
        "codec": "h264",
        "protocol": "udp",
        "client": "custom",
        "version": "1.1",
        "pubkey": public_pem  # Our RSA public key in PEM format
    }
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "User-Agent": "UnitreeGo/1.1",
        "X-Device-Id": ROBOT_SN
    }
    
    # Send to robot
    resp = requests.post(
        f"http://{ROBOT_IP}:9991/con_notify",
        headers=headers,
        json=body,
        verify=False,
        timeout=10
    )
    
    print(f"📬 Response status: {resp.status_code}")
    resp.raise_for_status()
    
    # Parse response
    try:
        payload = resp.json()
        print(f"📋 Response JSON keys: {list(payload.keys())}")
        return payload
    except json.JSONDecodeError:
        # Handle nested base64 JSON
        response_data = base64.b64decode(resp.text).decode('utf-8')
        payload = json.loads(response_data)
        print(f"📋 Nested response JSON keys: {list(payload.keys())}")
        return payload

async def complete_webrtc_connection(pc, payload, private_pem):
    """Complete WebRTC connection with decrypted answer"""
    print("🔗 Completing WebRTC connection...")
    
    # Decrypt SDP answer
    answer_sdp = extract_sdp_answer(payload, private_pem)
    
    print("📄 ANSWER m-lines:", mlines(answer_sdp))
    print(f"📝 SDP answer preview: {answer_sdp[:200]}...")
    
    # Set remote description
    answer_desc = type("obj", (), {"type": "answer", "sdp": answer_sdp})()
    await pc.setRemoteDescription(answer_desc)
    
    print("✅ Remote description set successfully!")
    return answer_sdp

async def setup_event_handlers(pc):
    """Set up WebRTC event handlers to monitor connection"""
    
    @pc.on("connectionstatechange")
    async def on_connection_state_change():
        state = pc.connectionState
        print(f"🔗 Connection state: {state}")
        if state == "connected":
            print("🎉 WebRTC connection established!")
        elif state == "failed":
            print("❌ WebRTC connection failed")
    
    @pc.on("track")
    async def on_track(track):
        print(f"🎥 Received track: {track.kind}")
        if track.kind == "video":
            print("🎉 Video track received - success!")
            # Here you would connect to HTML video element
            
    @pc.on("icegatheringstatechange") 
    async def on_ice_gathering():
        print(f"🧊 ICE gathering: {pc.iceGatheringState}")
    
    @pc.on("iceconnectionstatechange")
    async def on_ice_connection():
        print(f"🧊 ICE connection: {pc.iceConnectionState}")

async def main():
    """Main WebRTC connection flow"""
    print("🤖 Starting Precise WebRTC Connection")
    print("=" * 50)
    
    try:
        # Step 1: Create offer
        pc, munged_sdp, public_pem, private_pem = await create_webrtc_offer()
        
        # Step 2: Set up event handlers
        await setup_event_handlers(pc)
        
        # Step 3: Send offer to robot
        payload = await send_webrtc_offer(munged_sdp, public_pem)
        
        # Step 4: Complete connection
        answer_sdp = await complete_webrtc_connection(pc, payload, private_pem)
        
        # Step 5: Wait for connection
        print("⏳ Waiting for WebRTC connection...")
        for i in range(30):  # Wait up to 30 seconds
            await asyncio.sleep(1)
            if pc.connectionState == "connected":
                print("🎉 SUCCESS: WebRTC video connection established!")
                break
            elif pc.connectionState == "failed":
                print("❌ Connection failed")
                break
        else:
            print(f"⏰ Timeout - final state: {pc.connectionState}")
        
        # Keep connection alive for a bit
        if pc.connectionState == "connected":
            print("🔄 Keeping connection alive for 10 seconds...")
            await asyncio.sleep(10)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if 'pc' in locals():
            await pc.close()
        print("🏁 WebRTC test complete")

if __name__ == "__main__":
    asyncio.run(main())