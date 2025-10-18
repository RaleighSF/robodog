#!/usr/bin/env python3
"""
Deep analysis of the robot's custom RSA key format
"""
import base64
import json
import struct

# The actual response from the robot
robot_response = "eyJkYXRhMSI6IjNuUjBYazhIL1ZmMmRoN2VORXkrUG9HWXhKTDhIS0h0QTlUMU4zeFlHSkkrSjJCME1iSkFqVWorVGxHMmpVMTRxSU9FanZiUE44TGVvZnpOOWxCVnJYVUhWQ1h0Q1VIOXNnOUFNU1I1bGxJNnU0OURwOStsemJiREgwK25rRDFVemFaNTU3Wmpvc1h4QzVNVmVMUkh0Y05EdnFkZ0xLV1FtOStESTI4eXJKdTBDL3JlZlFyemxCZHF1REI0L1V2R0ZDQ2E5SGo1NkNrRUtMd0Njb2JBRnBYcHlJZkFQM2tQUmtiWjI3eFZzUFkzbEdGNjZBbzVLS0FFeVVvOTVHcytlN1F0REdwcmVldUVvR0NHOW5oVHUwNzNGRFRKZ3B4QjAwUHFYZ20walpZU3cxeHRkS3AranZZOXZyaVhlZnVGelBNc3FRWjcrc0tReTkwQWJhbTk2K09qL0htbnpkWDc4SklTNm9MVWlEZk5MeDB1NlhwYXM2ckdnWFoxUzVmNExxQWJOd1dMNVN4aFJaWGRpalAzMVhqdVdoTzhvMjVVakt1bTQ0Vk1kMlo0Q3JvYWhSTkRTYXRFRUJtZlZwUTZnaWhTNlZTK21VV3ZyMHlnWmcyUG44eUx2ZE96Q2tGWHowa1hLM0RzYjE0UEVHVllNT3hPUTBOUklkZ01TQTJFUE04Mld0MnowRUNIMmlFVk0wSGFsRkdnRVdlazZNOXRhVDRsVTFnVlZleVdlZE9icmloRTlobzJ2RUNSWkhhc2p0OHZhOGdoRXlBPSIsImRhdGEyIjoyfQ=="

print("🔍 Deep analysis of robot RSA key format...")

# Decode the JSON
decoded_json = json.loads(base64.b64decode(robot_response))
key_data = decoded_json['data1']
key_bytes = base64.b64decode(key_data)

print(f"📊 Key statistics:")
print(f"   - Total bytes: {len(key_bytes)}")
print(f"   - First 16 bytes (hex): {key_bytes[:16].hex()}")
print(f"   - Last 16 bytes (hex): {key_bytes[-16:].hex()}")

# Look for patterns that might indicate structure
print(f"\n🔍 Looking for structural patterns...")

# Common RSA key sizes are 1024, 2048, 3072, 4096 bits
# That's 128, 256, 384, 512 bytes respectively
if len(key_bytes) == 256:
    print("   - Length matches 2048-bit key (256 bytes)")
elif len(key_bytes) == 512:
    print("   - Length matches 4096-bit key (512 bytes)")
else:
    print(f"   - Unusual length: {len(key_bytes)} bytes")

# Check if it might be raw RSA modulus + exponent
print(f"\n🧪 Testing if it's raw modulus...")

# Try to interpret as big-endian integer (common for RSA modulus)
try:
    n = int.from_bytes(key_bytes, 'big')
    print(f"   - As big-endian int: {hex(n)[:50]}...")
    print(f"   - Bit length: {n.bit_length()} bits")
    
    # Check if it looks like a valid RSA modulus (should be odd, large)
    if n % 2 == 1 and n.bit_length() > 1000:
        print("   ✅ Could be RSA modulus (odd, large)")
    else:
        print("   ❌ Doesn't look like RSA modulus")
        
except Exception as e:
    print(f"   ❌ Error interpreting as integer: {e}")

# Check for embedded length fields or headers
print(f"\n🔍 Checking for embedded structure...")
for i in range(0, min(32, len(key_bytes)), 4):
    chunk = key_bytes[i:i+4]
    if len(chunk) == 4:
        val = struct.unpack('>I', chunk)[0]  # big-endian uint32
        print(f"   - Offset {i:2d}: {chunk.hex()} = {val:10d} = 0x{val:08x}")
        
        # Check if this could be a length field
        if val == len(key_bytes) - i - 4:
            print(f"     ^ Possible length field for remaining {len(key_bytes) - i - 4} bytes")
        if val == len(key_bytes):
            print(f"     ^ Possible total length field")

print(f"\n🔑 Key format hypothesis:")
print(f"   - This appears to be a custom/proprietary RSA key format")
print(f"   - Likely contains the modulus (n) and possibly exponent (e)")
print(f"   - May need reverse engineering of Unitree's key format")