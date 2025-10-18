#!/usr/bin/env python3
"""
Debug and fix the path calculation for con_ing URL
"""
import requests
import base64
import json
import sys
import os

# Add the project directory to the path
sys.path.insert(0, '/Users/Raleigh/Development/watch_dog')

# Import our monkey patch
import webrtc_patch

def analyze_data1_endings():
    """Analyze multiple data1 responses to understand the pattern"""
    
    robot_ip = "192.168.86.22"
    token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4QjRDODIyM0JGREZENUJBIiwiaWF0IjoxNzI0MjkxNDkwLCJhcHBfaWQiOiJZRjNVSTJTOE44SjJHVUJNIiwicHJvZHVjdF9pZCI6Imdvb19zbjhqM2dtdWJtOWZzamYzaGF1ZG1kIiwib3Blbl9pZCI6IjE3MjQyOTE0OTAyNjcxNjA2NzMifQ.OJV8qJ7MX7yOFzLzOsckLLfHBIZ4XJ5YI0UHXzQP-M_yXjYJILw8f4d23VyJpxYHCzKw4wYOCiI6OxrFJrqp5zIEd2F2Z3aQWQ-Qs4M3vOw95O4FUJLzK8b7VR3ckZIxfXTYJ-QO5ZNJFzZkQ_J9O4XzZ-VQ5O2cKYZ8J_zQ"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "X-Device-Id": "B42D4000P6PC04GE",
        "User-Agent": "UnitreeGo/1.1"
    }
    
    print("🔍 Analyzing data1 endings from multiple requests...")
    
    data1_samples = []
    
    # Collect multiple samples
    for i in range(5):
        test_request = {
            "type": "offer",
            "sdp": f"v=0\r\no=- {12345 + i} 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=application 9 DTLS/SCTP 5000\r\n",
            "client": "custom",
            "version": "1.1",
            "codec": "h264",
            "protocol": "udp"
        }
        
        try:
            response = requests.post(
                f"http://{robot_ip}:9991/con_notify",
                headers=headers,
                json=test_request,
                timeout=5
            )
            
            if response.status_code == 200:
                decoded_response = base64.b64decode(response.text).decode('utf-8')
                response_json = json.loads(decoded_response)
                data1 = response_json['data1']
                data1_samples.append(data1)
                
                print(f"📦 Sample {i+1}: {len(data1)} chars, ends with '{data1[-10:]}'")
                
        except Exception as e:
            print(f"❌ Sample {i+1} failed: {e}")
    
    # Analyze patterns
    print(f"\n🔬 Analysis of {len(data1_samples)} samples:")
    
    for i, data1 in enumerate(data1_samples):
        last_10 = data1[-10:]
        print(f"Sample {i+1} last 10 chars: '{last_10}'")
        
        # Original algorithm
        strArr = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
        chunked = [last_10[j : j + 2] for j in range(0, len(last_10), 2)]
        
        print(f"  Chunked: {chunked}")
        
        indices = []
        for chunk in chunked:
            if len(chunk) > 1:
                second_char = chunk[1]
                if second_char in strArr:
                    indices.append(strArr.index(second_char))
                else:
                    print(f"  ❌ Character '{second_char}' not in strArr")
                    
        path_ending = "".join(map(str, indices))
        print(f"  Path ending (original): '{path_ending}'")
        
        # Alternative: Use hash or checksum approach
        import hashlib
        hash_based = hashlib.md5(last_10.encode()).hexdigest()[:6]
        print(f"  Alternative hash-based: '{hash_based}'")
        
        # Alternative: Use all characters and map them
        extended_map = {
            'A': '0', 'B': '1', 'C': '2', 'D': '3', 'E': '4', 'F': '5', 'G': '6', 'H': '7', 'I': '8', 'J': '9',
            'a': '0', 'b': '1', 'c': '2', 'd': '3', 'e': '4', 'f': '5', 'g': '6', 'h': '7', 'i': '8', 'j': '9',
            '0': '0', '1': '1', '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
            '+': '0', '/': '1', '=': '2'  # Base64 padding chars
        }
        
        extended_path = []
        for chunk in chunked:
            if len(chunk) > 1:
                second_char = chunk[1]
                if second_char in extended_map:
                    extended_path.append(extended_map[second_char])
                else:
                    # Default to position in ASCII table mod 10
                    extended_path.append(str(ord(second_char) % 10))
                    
        extended_ending = "".join(extended_path)
        print(f"  Extended mapping: '{extended_ending}'")
        print()

def test_path_endings():
    """Test different path ending approaches"""
    
    # Let's try the most common approaches for generating the path
    robot_ip = "192.168.86.22"
    test_paths = [
        "",  # Empty (current issue)
        "0", "1", "2", "3", "4", "5",  # Simple numbers
        "123", "456", "789",  # Common patterns
        "default", "test", "main"  # String fallbacks
    ]
    
    print("🧪 Testing different path endings...")
    
    for path in test_paths:
        url = f"http://{robot_ip}:9991/con_ing_{path}"
        print(f"🌐 Testing: {url}")
        
        try:
            # Just test connectivity, not full request
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((robot_ip, 9991))
            sock.close()
            
            if result == 0:
                print(f"  ✅ Port 9991 reachable for path '{path}'")
            else:
                print(f"  ❌ Port 9991 not reachable")
                
        except Exception as e:
            print(f"  ❌ Connection test failed: {e}")

if __name__ == "__main__":
    analyze_data1_endings()
    print("\n" + "="*50)
    test_path_endings()