# RTSP Server Notice Feature

## Overview
Added a graceful UI component that automatically detects when a user tries to start an RTSP stream (IR, Depth, or Color) without the RTSP server running, and guides them to start it first.

## What Was Added

### 1. **RTSP Notice Modal**
- Clean, user-friendly modal with warning icon
- Shows the selected channel name (IR/Depth/Color)
- Provides step-by-step instructions
- Two action buttons: "Cancel" and "Go to Settings"

### 2. **Automatic RTSP Status Check**
- Before starting any RTSP stream, the dashboard automatically checks if the RTSP server is running
- If server is stopped, shows the notice modal instead of attempting to start
- If server is running, proceeds normally with stream start

### 3. **Direct Navigation to Settings**
- "Go to Settings" button opens Configure modal
- Automatically switches to the Settings tab
- Scrolls to and highlights the RTSP Server Control section
- Smooth animated transition for better UX

## User Flow

### Scenario: User tries to start IR channel without RTSP server

1. **User selects "IR Channel"** from camera dropdown
2. **User clicks "Start"** button
3. **Dashboard checks RTSP status** automatically
4. **Notice modal appears** showing:
   - Warning that RTSP server is not running
   - The channel they selected (IR Channel)
   - Step-by-step instructions
5. **User clicks "Go to Settings"**
6. **Dashboard opens Settings** and highlights RTSP control
7. **User clicks "Start RTSP Server"**
8. **Waits 2-3 seconds** for confirmation
9. **Returns to main view** and clicks "Start" again
10. **Stream starts successfully**

## Technical Implementation

### Files Modified
- **templates/index.html**:
  - Added RTSP notice modal HTML (lines 1472-1511)
  - Added modal control functions (lines 2027-2075)
  - Added RTSP status check in start button (lines 1689-1711)
  - Added outside-click close handler (lines 2666-2672)

### Key Functions
- `openRTSPNoticeModal(channelName)` - Opens the notice with selected channel
- `closeRTSPNoticeModal()` - Closes the notice modal
- `openRTSPSettings()` - Opens settings and navigates to RTSP controls

### API Endpoints Used
- `GET /rtsp/status` - Checks if RTSP server is running on Orin

## Testing

### Test Case 1: RTSP Server Stopped
1. Ensure RTSP server is stopped:
   ```bash
   curl http://192.168.50.208:8000/rtsp/stop -X POST
   ```
2. Open dashboard: http://192.168.50.208:8000
3. Select "IR Channel" from dropdown
4. Click "Start"
5. **Expected**: Notice modal appears with instructions

### Test Case 2: RTSP Server Running
1. Start RTSP server via Settings or:
   ```bash
   curl http://192.168.50.208:8000/rtsp/start -X POST
   ```
2. Open dashboard: http://192.168.50.208:8000
3. Select "Depth Channel" from dropdown
4. Click "Start"
5. **Expected**: Stream starts normally, no modal

### Test Case 3: Go to Settings Flow
1. Trigger notice modal (Test Case 1)
2. Click "Go to Settings →" button
3. **Expected**:
   - Notice modal closes
   - Config modal opens
   - Settings tab is active
   - RTSP Server Control section is highlighted
   - Smooth scroll animation

### Test Case 4: Native GO2 Camera (No Check)
1. Select "Native Go2 Camera"
2. Click "Start"
3. **Expected**: No RTSP check, starts immediately

## Current Status

✅ **Dashboard**: Running at http://192.168.50.208:8000
✅ **RTSP Server**: Stopped (ready for testing)
✅ **Feature**: Deployed and active

## Benefits

1. **Prevents Confusion**: Users no longer see mysterious "camera failed" errors
2. **Self-Service**: Clear instructions guide users to fix the issue themselves
3. **Smooth UX**: Direct navigation saves clicks and reduces frustration
4. **Visual Feedback**: Highlighted section makes it obvious where to click
5. **Fail-Safe**: If RTSP check fails, stream still attempts to start (handles network issues)

## User Experience Improvements

- Modal uses same styling as existing config modal for consistency
- Warning icon (⚠️) clearly indicates attention needed
- "Go to Settings" button is primary action (blue) for visual emphasis
- Cancel option available if user changes their mind
- Outside-click dismisses modal (standard behavior)
- Smooth animations and transitions throughout

## Maintenance Notes

- RTSP status check has 5-second implicit timeout (fetch default)
- If status check fails (network issue), stream start proceeds anyway
- Modal only appears for RTSP sources: `rtsp_color`, `rtsp_ir`, `rtsp_depth`
- Native GO2 camera bypasses RTSP check entirely
