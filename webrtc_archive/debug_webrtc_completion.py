#!/usr/bin/env python3
"""
Debug WebRTC connection completion after successful SDP exchange
"""
import time
import requests

def monitor_webrtc_progress():
    """Monitor the WebRTC connection progress"""
    
    print("🔍 Monitoring WebRTC connection progress...")
    
    for i in range(30):  # Monitor for 30 seconds
        try:
            response = requests.get("http://127.0.0.1:5000/webrtc/status", timeout=2)
            if response.status_code == 200:
                status = response.json()
                
                print(f"⏱️  Step {i+1}: Connected={status.get('connected', 'unknown')}, "
                      f"Initialized={status.get('connection_initialized', 'unknown')}")
                
                if status.get('connected'):
                    print("🎉 WebRTC connection completed successfully!")
                    return True
                    
        except Exception as e:
            print(f"❌ Status check failed: {e}")
        
        time.sleep(1)
    
    print("⏰ Monitoring timeout - WebRTC may still be negotiating")
    return False

if __name__ == "__main__":
    monitor_webrtc_progress()