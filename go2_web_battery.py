#!/usr/bin/env python3
"""
GO2 Web Control with Battery Display
Uses persistent WebRTC connection + LOW_STATE subscription for battery info
"""
import asyncio
import sys
import threading
import queue
from flask import Flask, jsonify

sys.path.insert(0, "/home/unitree/.local/lib/python3.8/site-packages")
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection, WebRTCConnectionMethod  
from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD

app = Flask(__name__)

# Shared state
command_queue = queue.Queue()
result_queue = queue.Queue()
battery_state = {"soc": None, "voltage": None, "current": None}

HTML = """<!DOCTYPE html>
<html><head><title>GO2 Control</title><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:Arial;max-width:800px;margin:50px auto;padding:20px;background:#1a1a1a;color:#fff}
h1{text-align:center;color:#4CAF50}
.status{text-align:center;padding:15px;background:#2a2a2a;border-radius:8px;margin:20px 0;border-left:4px solid #4CAF50}
.battery{display:flex;justify-content:center;gap:20px;flex-wrap:wrap}
.battery-item{background:#333;padding:10px 20px;border-radius:5px}
.battery-value{font-size:24px;font-weight:bold;color:#4CAF50}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:15px;margin:20px 0}
button{padding:20px;font-size:16px;border:none;border-radius:8px;cursor:pointer;background:#4CAF50;color:white}
button:hover{background:#45a049;transform:translateY(-2px)}
.special{background:#FF9800}.special:hover{background:#e68900}
.danger{background:#f44336}.danger:hover{background:#da190b}
#msg{margin-top:20px;padding:15px;background:#2a2a2a;border-radius:8px}
</style></head><body>
<h1>🐕 GO2 Control</h1>
<div class="status">
  <div>Status: ✓ Connected (Persistent Connection)</div>
  <div class="battery">
    <div class="battery-item">
      🔋 Battery: <span class="battery-value" id="soc">--</span>%
    </div>
    <div class="battery-item">
      ⚡ Voltage: <span id="voltage">--</span>V
    </div>
    <div class="battery-item">
      🔌 Current: <span id="current">--</span>mA
    </div>
  </div>
</div>
<h3>Basic Controls</h3>
<div class="grid">
<button onclick="cmd('stand_up')">⬆️ Stand Up</button>
<button onclick="cmd('crouch')" class="special">⬇️ Crouch</button>
<button onclick="cmd('sit')" class="special">🪑 Sit</button>
<button onclick="cmd('damp')" class="danger">💤 Damp</button>
</div>
<h3>Gestures</h3>
<div class="grid">
<button onclick="cmd('hello')" class="special">👋 Hello</button>
<button onclick="cmd('stretch')" class="special">🤸 Stretch</button>
<button onclick="cmd('wiggle')" class="special">💃 Wiggle</button>
</div>
<div id="msg"></div>
<script>
function cmd(c){
  document.getElementById('msg').innerHTML='⏳ Sending '+c+'...';
  fetch('/cmd/'+c,{method:'POST'})
  .then(r=>r.json())
  .then(d=>document.getElementById('msg').innerHTML=d.success?'✓ '+c+' (in '+d.time+'s)':'✗ Failed: '+d.message)
  .catch(e=>document.getElementById('msg').innerHTML='✗ Error: '+e);
}
function updateBattery(){
  fetch('/battery')
  .then(r=>r.json())
  .then(d=>{
    if(d.soc!==null) document.getElementById('soc').textContent=d.soc;
    if(d.voltage!==null) document.getElementById('voltage').textContent=(d.voltage/1000).toFixed(1);
    if(d.current!==null) document.getElementById('current').textContent=d.current;
  });
}
setInterval(updateBattery,2000);
updateBattery();
</script>
</body></html>"""

async def robot_loop():
    """Background loop maintaining persistent connection"""
    global battery_state
    
    print("[ASYNC] Connecting to robot...")
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip="192.168.86.148")
    await conn.connect()
    print("[ASYNC] ✓ Connected!")
    
    # Subscribe to LOW_STATE for battery info
    def lowstate_callback(message):
        try:
            data = message['data']
            bms = data['bms_state']
            battery_state['soc'] = bms['soc']
            battery_state['voltage'] = data['power_v']
            battery_state['current'] = bms['current']
        except Exception as e:
            print(f"[ASYNC] Battery update error: {e}")
    
    conn.datachannel.pub_sub.subscribe(RTC_TOPIC['LOW_STATE'], lowstate_callback)
    print("[ASYNC] ✓ Subscribed to battery updates")
    
    # Command processing loop
    while True:
        try:
            try:
                cmd_info = command_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            
            cmd_id = cmd_info["cmd_id"]
            request_id = cmd_info["request_id"]
            
            print(f"[ASYNC] Processing command {cmd_id}")
            
            try:
                resp = await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"], {"api_id": cmd_id}
                )
                code = resp["data"]["header"]["status"]["code"]
                result_queue.put({"request_id": request_id, "success": code == 0})
            except Exception as e:
                print(f"[ASYNC] Command error: {e}")
                result_queue.put({"request_id": request_id, "success": False, "error": str(e)})
                
        except Exception as e:
            print(f"[ASYNC] Loop error: {e}")
            await asyncio.sleep(1)

def start_robot_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(robot_loop())

robot_thread = threading.Thread(target=start_robot_loop, daemon=True)
robot_thread.start()

@app.route("/")
def index():
    return HTML

@app.route("/battery")
def battery():
    return jsonify(battery_state)

@app.route("/cmd/<cmd>", methods=["POST"])
def command(cmd):
    import time
    start_time = time.time()
    
    try:
        cmd_map = {
            "stand_up": SPORT_CMD["StandUp"],
            "crouch": SPORT_CMD["StandDown"],
            "sit": SPORT_CMD["Damp"],
            "damp": SPORT_CMD["RecoveryStand"],
            "hello": SPORT_CMD["Hello"],
            "stretch": SPORT_CMD["Stretch"],
            "wiggle": SPORT_CMD["WiggleHips"]
        }
        
        if cmd not in cmd_map:
            return jsonify({"success": False, "message": "Unknown command"})
        
        request_id = id(cmd) + int(time.time() * 1000000)
        command_queue.put({"cmd_id": cmd_map[cmd], "request_id": request_id})
        
        timeout = 5.0
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                result = result_queue.get_nowait()
                if result["request_id"] == request_id:
                    elapsed = round(time.time() - start_time, 2)
                    return jsonify({
                        "success": result["success"],
                        "message": result.get("error", "OK"),
                        "time": elapsed
                    })
                else:
                    result_queue.put(result)
            except queue.Empty:
                time.sleep(0.05)
        
        return jsonify({"success": False, "message": "Timeout", "time": timeout})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

if __name__ == "__main__":
    import time
    print("="*60)
    print("🐕 GO2 Web Control with Battery Display")
    print("="*60)
    print("Waiting for robot connection...")
    time.sleep(5)
    print("✓ Ready!")
    print("Web interface: http://192.168.86.21:5000")
    print("="*60)
    app.run(host="0.0.0.0", port=5000, debug=False)
