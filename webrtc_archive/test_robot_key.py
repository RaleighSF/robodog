#!/usr/bin/env python3
"""
Test script to analyze the robot's actual RSA key format
"""
import base64
import json
from monkey_key import load_robot_pubkey

# The actual response from the robot
robot_response = "eyJkYXRhMSI6IjNuUjBYazhIL1ZmMmRoN2VORXkrUG9HWXhKTDhIS0h0QTlUMU4zeFlHSkkrSjJCME1iSkFqVWorVGxHMmpVMTRxSU9FanZiUE44TGVvZnpOOWxCVnJYVUhWQ1h0Q1VIOXNnOUFNU1I1bGxJNnU0OURwOStsemJiREgwK25rRDFVemFaNTU3Wmpvc1h4QzVNVmVMUkh0Y05EdnFkZ0xLV1FtOStESTI4eXJKdTBDL3JlZlFyemxCZHF1REI0L1V2R0ZDQ2E5SGo1NkNrRUtMd0Njb2JBRnBYcHlJZkFQM2tQUmtiWjI3eFZzUFkzbEdGNjZBbzVLS0FFeVVvOTVHcytlN1F0REdwcmVldUVvR0NHOW5oVHUwNzNGRFRKZ3B4QjAwUHFYZ20walpZU3cxeHRkS3AranZZOXZyaVhlZnVGelBNc3FRWjcrc0tReTkwQWJhbTk2K09qL0htbnpkWDc4SklTNm9MVWlEZk5MeDB1NlhwYXM2ckdnWFoxUzVmNExxQWJOd1dMNVN4aFJaWGRpalAzMVhqdVdoTzhvMjVVakt1bTQ0Vk1kMlo0Q3JvYWhSTkRTYXRFRUJtZlZwUTZnaWhTNlZTK21VV3ZyMHlnWmcyUG44eUx2ZE96Q2tGWHowa1hLM0RzYjE0UEVHVllNT3hPUTBOUklkZ01TQTJFUE04Mld0MnowRUNIMmlFVk0wSGFsRkdnRVdlazZNOXRhVDRsVTFnVlZleVdlZE9icmloRTlobzJ2RUNSWkhhc2p0OHZhOGdoRXlBPSIsImRhdGEyIjoyfQ=="

print("🔍 Analyzing robot RSA key format...")

# Decode the outer base64 JSON
decoded_json = json.loads(base64.b64decode(robot_response))
print(f"📦 Decoded JSON keys: {list(decoded_json.keys())}")

# Extract the key data
key_data = decoded_json['data1']
print(f"🔑 Key data length: {len(key_data)} base64 chars")

# Try our flexible key loader
try:
    print("🧪 Testing with monkey_key.load_robot_pubkey()...")
    crypto_key = load_robot_pubkey(key_data)
    print("✅ Successfully loaded key!")
    
    # Get key details
    public_numbers = crypto_key.public_numbers()
    print(f"📊 Key details:")
    print(f"   - Modulus (n): {hex(public_numbers.n)[:50]}...")
    print(f"   - Exponent (e): {public_numbers.e}")
    print(f"   - Key size: {crypto_key.key_size} bits")
    
except Exception as e:
    print(f"❌ Failed to load key: {e}")

# Also test raw bytes
print("\n🧪 Testing with raw bytes...")
try:
    key_bytes = base64.b64decode(key_data)
    crypto_key = load_robot_pubkey(key_bytes)
    print("✅ Raw bytes also work!")
except Exception as e:
    print(f"❌ Raw bytes failed: {e}")

print("\n🔍 Key data preview (first 100 chars):")
print(f"{key_data[:100]}...")