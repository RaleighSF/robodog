#!/usr/bin/env python3
"""
WebRTC Test Script for Project Watch Dog

This script demonstrates the WebRTC integration functionality
without requiring a real access token or robot connection.
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web_app import webrtc_manager

def test_webrtc_functionality():
    """Test WebRTC manager functionality"""
    print("🤖 Project Watch Dog - WebRTC Test")
    print("=" * 50)
    
    # Test 1: Check initial status
    print("\n1. Initial Status:")
    status = webrtc_manager.get_status()
    print(f"   Connected: {status['connected']}")
    print(f"   Robot IP: {status['robot_ip']}")
    print(f"   Has Token: {status['has_token']}")
    print(f"   Command History: {len(status['command_history'])} commands")
    
    # Test 2: Set access token
    print("\n2. Setting Access Token:")
    test_token = "test_token_12345_demo"
    webrtc_manager.set_access_token(test_token)
    status = webrtc_manager.get_status()
    print(f"   Token set successfully: {status['has_token']}")
    
    # Test 3: Test command simulation
    print("\n3. Simulating Commands:")
    commands = [
        ("StandUp", {}),
        ("Move", {"x": 0.5, "y": 0, "z": 0}),
        ("Sit", {}),
        ("Dance1", {}),
        ("Stretch", {})
    ]
    
    for command, params in commands:
        result = webrtc_manager.send_command(command, params)
        print(f"   {command}: {result['message']}")
    
    # Test 4: Check final status
    print("\n4. Final Status:")
    status = webrtc_manager.get_status()
    print(f"   Connected: {status['connected']}")
    print(f"   Total Commands: {len(webrtc_manager.command_history)}")
    print(f"   Recent Commands: {[cmd['command'] for cmd in status['command_history']]}")
    
    print("\n🎉 WebRTC Test Completed!")
    print("\nTo use with a real robot:")
    print("1. Get your access token from the Unitree app")
    print("2. Set your robot's IP address")
    print("3. Run the Flask app: python web_app.py")
    print("4. Visit: http://127.0.0.1:5000/webrtc")
    print("5. Enter your token and connect!")
    
    return True

if __name__ == "__main__":
    test_webrtc_functionality()