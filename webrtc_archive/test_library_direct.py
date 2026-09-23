#!/usr/bin/env python3
"""
Test direct connection using go2-webrtc-connect library
"""
import asyncio
import sys
import os

# Add the project directory to the path
sys.path.insert(0, '/Users/Raleigh/Development/watch_dog')

# Import our monkey patch
import webrtc_patch

async def test_library_connection():
    """Test connection using go2-webrtc-connect library directly"""
    
    try:
        from go2_webrtc_driver.webrtc_driver import Go2WebRTCConnection
        from go2_webrtc_driver.constants import WebRTCConnectionMethod
        
        print("🚀 Testing direct library connection...")
        
        # Create connection using LocalSTA method
        connection = Go2WebRTCConnection(
            connectionMethod=WebRTCConnectionMethod.LocalSTA,
            ip="192.168.86.22",
            username=os.environ.get("UNITREE_USER", ""),
            password=os.environ.get("UNITREE_PASS", "")
        )
        
        # Set token
        connection.token = os.environ.get("UNITREE_TOKEN", "")
        
        print("🔗 Attempting connection...")
        await connection.connect()
        
        print("✅ Library connection successful!")
        print(f"🔍 Connected: {getattr(connection, 'isConnected', 'Unknown')}")
        
        # Keep connection alive for a bit
        for i in range(10):
            await asyncio.sleep(1)
            status = getattr(connection, 'isConnected', False)
            print(f"⏱️  Step {i+1}: Connection status = {status}")
            if not status:
                print("❌ Connection lost")
                break
                
    except Exception as e:
        print(f"❌ Library connection failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_library_connection())