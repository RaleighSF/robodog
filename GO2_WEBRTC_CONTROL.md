# GO2 WebRTC Control Implementation

## Overview

Successfully implemented WebRTC control for Unitree GO2 robot using the `unitree_webrtc_connect` 2.x library. This implementation provides a web-based control interface with real-time battery monitoring.

## Key Achievement

Successfully resolved WebRTC command execution issues by implementing an optimized persistent connection architecture that follows the repository's best practices.

## Implementation Details

### Library Used
- **Repository**: [legion1581/unitree_webrtc_connect](https://github.com/legion1581/unitree_webrtc_connect)
- **Branch**: 2.x.x
- **Firmware Compatibility**: 1.1.9+
- **Installation Location**: `~/go2_webrtc_connect_2x/` on ORIN host (192.168.86.21)

### Architecture

**Optimized Version** ([go2_web_battery.py](go2_web_battery.py)):
- **Persistent WebRTC Connection**: Single connection maintained in background thread
- **Async Event Loop**: Dedicated asyncio loop running in daemon thread
- **Thread-Safe Queue**: Command queue for Flask-to-async communication
- **LOW_STATE Subscription**: Continuous battery monitoring stream
- **Fast Command Execution**: <1 second (no reconnection overhead)

### Key Technical Insights

1. **Event Loop Constraint**: WebRTC connection objects cannot cross asyncio event loop boundaries
2. **Flask Integration Challenge**: Flask is synchronous and creates separate contexts per request
3. **Solution**: Background thread maintains single event loop with persistent connection; Flask communicates via thread-safe queues

### Features

#### Web Interface
- **URL**: http://192.168.86.21:5000
- **Real-time Battery Display**:
  - State of Charge (SOC) percentage
  - Voltage (V)
  - Current (mA)
- **Auto-refresh**: Battery stats update every 2 seconds

#### Available Commands
- Stand Up (StandUp)
- Crouch (StandDown)
- Sit Down (Damp)
- Damp Mode (RecoveryStand)
- Hello Wave (Hello)
- Stretch (Stretch)
- Wiggle Hips (WiggleHips)

### Battery Information

Battery data is available through the LOW_STATE subscription:
- **Topic**: `RTC_TOPIC['LOW_STATE']`
- **Method**: Subscribe (continuous stream, not request/response)
- **Key Fields**:
  - `bms_state['soc']`: Battery percentage
  - `bms_state['current']`: Current in mA
  - `power_v`: Voltage in mV
  - `bms_state['bq_ntc']`: Battery temperature
  - `bms_state['cycle']`: Charge cycle count

## Installation on ORIN Host

```bash
# Clone the repository (2.x.x branch)
cd ~/
git clone --recurse-submodules -b 2.x.x https://github.com/legion1581/go2_webrtc_connect.git go2_webrtc_connect_2x

# Install the library
cd go2_webrtc_connect_2x
pip install --user -e .

# Install Flask for web interface
pip install --user Flask
```

## Usage

### Starting the Web Interface

```bash
# On ORIN host (192.168.86.21)
python3 ~/go2_web_battery.py
```

### Access the Interface
Open browser to: **http://192.168.86.21:5000**

### Configuration
- **Robot IP**: 192.168.86.148 (GO2 in LocalSTA WiFi mode)
- **ORIN Host IP**: 192.168.86.21
- **Connection Method**: `WebRTCConnectionMethod.LocalSTA`

## Implementation Evolution

### Version History

1. **go2_web_control.py** (Initial): Event loop issues when commands sent
2. **go2_web_control_fixed.py**: Attempted ThreadPoolExecutor fix (still had issues with cross-loop connection reuse)
3. **go2_web_final.py**: Creates fresh connection per command (works but slow ~2-3s per command)
4. **go2_web_optimized.py**: Persistent connection with background event loop (fast <1s)
5. **go2_web_battery.py** (Final): Adds LOW_STATE subscription for real-time battery monitoring

### Lessons Learned

1. **Reusing Connections**: The official examples show reusing connections is best practice, BUT only within the same event loop
2. **Flask Integration**: Requires special architecture (background thread + queues) to work with async WebRTC
3. **Connection Methods**: The library tries old method first (port 8081), then falls back to correct method - "Max retries" error is normal
4. **Command Timing**: Robot processes commands sequentially with internal delays

## Troubleshooting

### "Max retries exceeded" Error
- **Normal behavior**: Library tries old connection method first, then uses correct one
- Connection succeeds afterward with message "✓ Connected!"

### Commands Not Executing
- Check robot is in normal mode (not MCF mode)
- Ensure Unitree app is closed (can interfere with WebRTC)
- Verify robot IP is correct: `ping 192.168.86.148`

### WebRTC Service Saturated
- **Symptom**: "Could not get SDP from the peer"
- **Solution**: Restart robot to reset WebRTC service
- **Cause**: Too many simultaneous connection attempts

## Network Configuration

- **Robot IP**: 192.168.86.148 (LocalSTA WiFi mode)
- **ORIN Host**: 192.168.86.21
- **Connection**: WiFi (LocalSTA mode)
- **Firmware**: 1.1.9

## Future Enhancements

Possible additions:
- Movement commands (forward, backward, turn)
- Video stream integration
- Additional sensor data display (IMU, foot force, temperatures)
- Command history/logging
- Multiple robot support

## References

- [unitree_webrtc_connect 2.x Documentation](https://github.com/legion1581/unitree_webrtc_connect/tree/2.x.x)
- Official examples: `~/go2_webrtc_connect_2x/examples/`
- Sport mode example: `examples/go2/data_channel/sportmode/sportmode.py`
- Low state example: `examples/go2/data_channel/lowstate/lowstate.py`

## Credits

Implementation based on legion1581's unitree_webrtc_connect library which properly handles firmware 1.1.9+ RSA validation.
