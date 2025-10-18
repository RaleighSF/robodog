# monkey_key.py
import base64, json, textwrap
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

def _try_load_pem(data: bytes):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    return load_pem_public_key(data)

def _try_load_der(data: bytes):
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    return load_der_public_key(data)

def _jwk_to_pubkey(jwk: dict):
    # JWK fields: n (modulus) and e (exponent), base64url-encoded
    def b64u(s): return base64.urlsafe_b64decode(s + "===")
    n = int.from_bytes(b64u(jwk["n"]), "big")
    e = int.from_bytes(b64u(jwk.get("e","AQAB")), "big")
    pub_nums = rsa.RSAPublicNumbers(e, n)
    return pub_nums.public_key()

def _try_parse_unitree_custom_key(key_bytes):
    """Attempt to parse Unitree's custom RSA key format"""
    from cryptography.hazmat.primitives.asymmetric import rsa
    
    # Based on analysis, this appears to be a custom format
    # We'll try different interpretations based on how the library extracts the key
    
    # The go2-webrtc library expects the key at data1[10:-10]
    # So we need to handle both the extracted portion and the full data
    
    print(f"🔧 Parsing Unitree custom key: {len(key_bytes)} bytes")
    
    # Hypothesis 1: It might contain modulus + exponent in specific layout
    # Common RSA public keys have modulus (n) and exponent (e, typically 65537)
    
    # Try to find patterns that could be the exponent (65537 = 0x10001)
    exponent_bytes = b'\x01\x00\x01'  # 65537 as 3 bytes
    exponent_bytes_4 = b'\x00\x01\x00\x01'  # 65537 as 4 bytes
    
    # Look for the exponent in the key data
    for exp_pattern in [exponent_bytes, exponent_bytes_4]:
        pos = key_bytes.find(exp_pattern)
        if pos != -1:
            print(f"🔍 Found potential exponent at offset {pos}")
            # Try to extract modulus from remaining bytes
            if pos > 200:  # Modulus should be substantial
                n_bytes = key_bytes[:pos]
                n = int.from_bytes(n_bytes, 'big')
                e = 65537
                
                if n % 2 == 1 and n.bit_length() >= 1024:  # Valid RSA modulus
                    print(f"✅ Extracted RSA key: {n.bit_length()} bits")
                    public_numbers = rsa.RSAPublicNumbers(e, n)
                    return public_numbers.public_key()
    
    # Hypothesis 2: The entire blob might be the modulus with standard exponent
    # Try interpreting the whole thing as modulus with e=65537
    try:
        n = int.from_bytes(key_bytes, 'big')
        if n % 2 == 1 and n.bit_length() >= 1024:
            print(f"🧪 Trying whole blob as modulus: {n.bit_length()} bits")
            e = 65537  # Standard RSA exponent
            public_numbers = rsa.RSAPublicNumbers(e, n)
            return public_numbers.public_key()
    except Exception as e:
        print(f"❌ Whole blob as modulus failed: {e}")
    
    # Hypothesis 3: Try different offsets and lengths for modulus
    # Prioritize 384 bytes (3072-bit) as found in library extraction
    for start_offset in [0, 4, 8, 16, 32]:
        for length in [384, 256, 512]:  # Prioritize 384 bytes for 3072-bit keys
            if start_offset + length <= len(key_bytes):
                try:
                    n_bytes = key_bytes[start_offset:start_offset + length]
                    n = int.from_bytes(n_bytes, 'big')
                    if n % 2 == 1 and n.bit_length() >= 1024:
                        print(f"🧪 Trying offset {start_offset}, length {length}: {n.bit_length()} bits")
                        e = 65537
                        public_numbers = rsa.RSAPublicNumbers(e, n)
                        return public_numbers.public_key()
                except Exception:
                    continue
    
    return None

def load_robot_pubkey(raw):
    """Accepts str/bytes from robot and returns a cryptography public key."""
    if isinstance(raw, str):
        raw = raw.strip()
        # 1) JWK JSON?
        if raw.startswith("{") and raw.endswith("}"):
            return _jwk_to_pubkey(json.loads(raw))
        # 2) PEM as text?
        if "BEGIN" in raw:
            try:
                return _try_load_pem(raw.encode())
            except Exception:
                # Convert PKCS#1 to PKCS#8 if needed
                if "BEGIN RSA PUBLIC KEY" in raw:
                    body = raw.split("-----")[2].strip().replace("\n","")
                    der = base64.b64decode(body)
                    # Rewrap as SubjectPublicKeyInfo (PKCS#8)
                    return _try_load_der(der)
                raise
        # 3) Base64-only? (This could be Unitree's custom format)
        try:
            der = base64.b64decode(raw, validate=True)
            
            # First try standard formats
            try:
                return _try_load_der(der)
            except Exception:
                pass
            
            # Try Unitree custom format
            custom_key = _try_parse_unitree_custom_key(der)
            if custom_key:
                return custom_key
            
            # Last resort: wrap as PEM
            try:
                pem = "-----BEGIN PUBLIC KEY-----\n" + \
                      "\n".join(textwrap.wrap(base64.b64encode(der).decode(), 64)) + \
                      "\n-----END PUBLIC KEY-----\n"
                return _try_load_pem(pem.encode())
            except Exception:
                pass
                
        except Exception:
            pass

    elif isinstance(raw, (bytes, bytearray)):
        # bytes: try DER then PEM then custom format
        try:
            return _try_load_der(bytes(raw))
        except Exception:
            pass
            
        try:
            return _try_load_pem(bytes(raw))
        except Exception:
            pass
            
        # Try Unitree custom format
        custom_key = _try_parse_unitree_custom_key(bytes(raw))
        if custom_key:
            return custom_key
            
        # last resort: b64→DER→PEM
        try:
            der = base64.b64decode(bytes(raw), validate=True)
            return _try_load_der(der)
        except Exception:
            pass

    raise ValueError("Unsupported robot RSA key format")