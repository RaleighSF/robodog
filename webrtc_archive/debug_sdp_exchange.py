#!/usr/bin/env python3
"""
Debug the SDP exchange process step by step
"""
import base64
import json
import sys
import os

# Add the project directory to the path
sys.path.insert(0, '/Users/Raleigh/Development/watch_dog')

# Import our monkey patch
import webrtc_patch
from monkey_key import load_robot_pubkey

# Get the robot response we captured earlier
robot_response = "eyJkYXRhMSI6InFMVUU1aXNlN2V5M2FLWjh0NGFldjJTbVNJcHlSRkJ3TVpEUzJvZFZzU1FvMHB4V3BIUnZzU1FIV3U3MmVCbjBNUEZRUlEyMHdaWjVYQ3pkU2JEaytTS2VIOFBIN1Z5V2JrZy9DY1NDMTRsVnVEU0xvMnd4Z0p2VytCbWs5d3Yxc1doMkk0eVllM2d4VnBQbUVZNkZsT1FvNG84REk3eFJlc0lkTGhlb09rWk1lcmJ1akVodnVMT2hjazhRcUNJVFZoM1Y3WkVscnh6TVBOWVUrTE9VS0xTRmN4N3VYR25zTHRHUlNadU8wVlRKYVlXM05PYjloUTF5UFU3OWtQK0RjaFdvdTdZZWVQRlBjZXN1WXpPdlFLZDJaRjFKWHFEa0JMVFNDQnd0RXRHNHdCRG1PMEExSXNITjVUT3FZRzRkcjFHakV1alpiTTJxNGpWSE5nOXFBajhVQmk2U1B1dHBwQ1lVU3B2ajFqVWw0bFBGdEI3ajNjQU1NaFUzNUlFNEMrZmo4OGNuU05pWHhDZndRMWsrTWZGSmVtTXRjcEZyTG4xMnlUYzNjVFFVcndYV2RMQ0g4ZjNMRUZrMkhHZ3NpNXBUUXdsOUJERW9ydjJneTdtdlF0VVE3dk5UWGlsc1FFMGljU1NrRERJbFlNZ2dBaW0zV3NhRi9hS3pNQjdzZHRkMitOR1FsRDdyaXBlNm1GOUV1WUlmZVdaeGNxNGhHY2F4RWJKb0p4WDhHcGQwQUlnY3pUYld4QzdWb2F3cDlLOVo0NjdUTklVPSIsImRhdGEyIjoyfQ=="

print("🔍 Debugging SDP exchange process...")

# Step 1: Decode the robot response
decoded_json = json.loads(base64.b64decode(robot_response))
data1 = decoded_json['data1']
print(f"📦 Full data1 length: {len(data1)} chars")

# Step 2: Extract the key the way the library does it
public_key_pem = data1[10 : len(data1) - 10]  # Library's extraction method
print(f"🔑 Extracted key length: {len(public_key_pem)} chars")
print(f"🔑 Extracted key preview: {public_key_pem[:50]}...")

# Step 3: Try to load the key using our monkey patch
print("\n🧪 Testing extracted key with our RSA parser...")
try:
    crypto_key = load_robot_pubkey(public_key_pem)
    print(f"✅ Successfully loaded extracted key: {crypto_key.key_size} bits")
    
    # Test the full data1 as well
    print("\n🧪 Testing full data1 with our RSA parser...")
    try:
        crypto_key_full = load_robot_pubkey(data1)
        print(f"✅ Successfully loaded full key: {crypto_key_full.key_size} bits")
        
        # Compare the keys
        if crypto_key.public_numbers().n == crypto_key_full.public_numbers().n:
            print("✅ Both methods produce identical keys")
        else:
            print("❌ Keys are different!")
            
    except Exception as e:
        print(f"❌ Full data1 failed: {e}")
        
except Exception as e:
    print(f"❌ Extracted key failed: {e}")
    
    # Try with full data1
    print("\n🧪 Fallback: Testing full data1...")
    try:
        crypto_key_full = load_robot_pubkey(data1)
        print(f"✅ Full data1 works: {crypto_key_full.key_size} bits")
        print("⚠️ Library extraction method is wrong for this robot!")
    except Exception as e2:
        print(f"❌ Both methods failed: {e2}")

print(f"\n📊 Analysis:")
print(f"   - Library expects key at data1[10:-10]")
print(f"   - Robot sends different format")
print(f"   - Our monkey patch handles both cases")