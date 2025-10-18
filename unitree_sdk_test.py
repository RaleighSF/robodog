#!/usr/bin/env python3
"""
Test script for Unitree Go2 EDU Plus camera using official SDK
"""

import sys
import os
import time

# Add the unitree SDK to the path
sys.path.append('./unitree_sdk2_python')

try:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.go2.video.video_client import VideoClient
    import cv2
    import numpy as np
    print("✓ Official Unitree SDK imported successfully")
    SDK_AVAILABLE = True
except ImportError as e:
    print(f"✗ Official Unitree SDK not available: {e}")
    SDK_AVAILABLE = False

def test_official_sdk():
    """Test the official SDK connection to Go2 EDU Plus"""
    if not SDK_AVAILABLE:
        print("SDK not available, cannot test")
        return False
    
    try:
        print("Initializing DDS channel factory...")
        # Try to initialize without network interface first
        ChannelFactoryInitialize(0)
        
        print("Creating video client...")
        client = VideoClient()
        client.SetTimeout(3.0)
        
        print("Initializing video client...")
        client.Init()
        
        print("Attempting to get image sample...")
        code, data = client.GetImageSample()
        
        if code == 0:
            print("✓ Successfully received image data!")
            print(f"Image data size: {len(data)} bytes")
            
            # Try to decode the image
            image_data = np.frombuffer(bytes(data), dtype=np.uint8)
            image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
            
            if image is not None:
                print(f"✓ Image decoded successfully: {image.shape}")
                # Save test image
                cv2.imwrite("/Users/Raleigh/Development/watch_dog/official_sdk_test.jpg", image)
                print("✓ Test image saved as official_sdk_test.jpg")
                return True
            else:
                print("✗ Failed to decode image data")
                return False
        else:
            print(f"✗ Failed to get image sample, error code: {code}")
            return False
            
    except Exception as e:
        print(f"✗ Official SDK test failed: {e}")
        return False

def test_with_network_interface():
    """Test with network interface specification"""
    if not SDK_AVAILABLE:
        return False
        
    # Common macOS network interfaces
    interfaces = ['en0', 'en1', 'wifi0']
    
    for interface in interfaces:
        try:
            print(f"\nTesting with network interface: {interface}")
            ChannelFactoryInitialize(0, interface)
            
            client = VideoClient()
            client.SetTimeout(3.0)
            client.Init()
            
            code, data = client.GetImageSample()
            
            if code == 0:
                print(f"✓ Success with interface {interface}!")
                return True
            else:
                print(f"✗ Failed with interface {interface}, code: {code}")
                
        except Exception as e:
            print(f"✗ Error with interface {interface}: {e}")
            continue
    
    return False

if __name__ == "__main__":
    print("=== Testing Official Unitree SDK ===")
    print("Robot IP: 192.168.87.25")
    print("Serial: B42D4000P6PC04GE")
    print()
    
    # Test 1: Basic connection
    print("Test 1: Basic DDS connection...")
    success = test_official_sdk()
    
    if not success:
        print("\nTest 2: Trying with network interfaces...")
        success = test_with_network_interface()
    
    if success:
        print("\n🎉 Official SDK is working! We can integrate this into Watch Dog.")
    else:
        print("\n❌ Official SDK connection failed. We'll stick with WebRTC approach.")