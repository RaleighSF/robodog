# Go2 Command Loop — the pattern that actually works

How to make a Unitree Go2 perform an action (`stand`, `crouch`, `sit`, `shake`) over the
WebRTC datachannel. Distilled from a working production service (`go2_service.py`).

## The one thing that breaks naive implementations

**A WebRTC connection object cannot cross an asyncio event loop boundary.** You cannot
`asyncio.run()` a command from a Flask/FastAPI request handler — the connection was created on
a different loop and will throw, or hang, or half-work and then die.

So sending a command is **not a function call**. It is a queue hand-off to a long-lived worker:

```
HTTP request (sync thread)          Robot thread (one asyncio loop, forever)
        |                                       |
        |-- queue.put((cmd, api_id, id)) -->    |
        |                                       |-- drain queue (non-blocking)
        |   poll results dict every 50ms        |-- await publish_request_new(...)
        |                                       |-- results[id] = {...}
        |<------ result appears ---------|
```

## 1. Own the connection in exactly one thread

```python
async def robot_loop():
    while True:                                  # reconnect forever
        try:
            conn = UnitreeWebRTCConnection(
                WebRTCConnectionMethod.LocalSTA, ip='192.168.123.161')
            await conn.connect()                 # persistent — never per-command
            conn.datachannel.pub_sub.subscribe(RTC_TOPIC['LOW_STATE'], on_lowstate)

            while True:                          # command pump
                drain_and_execute(conn)
                await asyncio.sleep(0.03)        # ~30 Hz tick

        except Exception as e:
            await asyncio.sleep(5)               # then reconnect

def start_robot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(robot_loop())

threading.Thread(target=start_robot_thread, daemon=True).start()
```

Connect **once** and hold it. A fresh connection per command costs 2–3 s; a persistent one
costs under 1 s.

## 2. The command sequence (order matters)

```python
COMMAND_MAP = {
    'stand':  SPORT_CMD['StandUp'],    # 1004
    'crouch': SPORT_CMD['StandDown'],  # 1005
    'sit':    SPORT_CMD['Sit'],        # 1009
    'shake':  SPORT_CMD['Hello'],      # 1016
}

# inside the async loop, for one dequeued command:

# a) Select the motion controller — BUT NOT IF STANDING (see gotcha #1)
if posture != 'standing':
    await conn.datachannel.pub_sub.publish_request_new(
        RTC_TOPIC['MOTION_SWITCHER'],
        {'api_id': 1002, 'parameter': {'name': 'normal'}})

# b) Let the mode settle. Skipping this makes commands intermittently fail.
await asyncio.sleep(0.1)

# c) Send the sport command
resp = await conn.datachannel.pub_sub.publish_request_new(
    RTC_TOPIC['SPORT_MOD'], {'api_id': COMMAND_MAP[cmd]})

# d) Success is code == 0, nested four levels deep
status = resp.get('data', {}).get('header', {}).get('status', {})
code   = status.get('code', 1)
ok     = (code == 0) or (code in LENIENT.get(cmd, set()))

# e) Publish the result for the waiting HTTP thread
results[result_id] = {'success': ok, 'message': status.get('message', '')}
```

`LENIENT = {'sit': {-1}, 'shake': {-1}}` — these two legitimately return `-1` when the sport
controller has timed out. Treat as success or you will report false failures.

If a command fails with an *unexpected* code, send `RecoveryStand` (1006) automatically.

## 3. The HTTP side never touches the robot

```python
@app.route('/command', methods=['POST'])
def handle_command():
    cmd = request.get_json().get('command')

    if _robot_busy:                                   # one command in flight at a time
        return jsonify({'message': 'Robot busy'}), 429
    if time.time() - _last_cmd_ts < 2.0:              # min 2s between sport commands
        return jsonify({'message': 'Cooldown'}), 429

    result_id = f'{cmd}_{time.time()}'
    command_queue.put((cmd, COMMAND_MAP[cmd], result_id))

    start = time.time()
    while time.time() - start < 8.0:                  # 8s timeout
        with result_lock:
            if result_id in results:
                return jsonify(results.pop(result_id))
        time.sleep(0.05)
    return jsonify({'message': 'timeout'}), 504
```

## 4. Three gotchas that will drop the robot

**1. Never send `MOTION_SWITCHER` mode-select or `BalanceStand` (1002) while standing.**
Both are firmware safety faults that make the robot collapse. Track posture in a variable and
guard on it. This is why step (a) above is conditional.

**2. A standing robot needs sport traffic every ~10 minutes or the firmware faults.**
Re-send `StandUp` on **SPORT_MOD** every 300 s while standing. Do *not* use the motion-switcher
keepalive for this — that is gotcha #1. The 2-second transport heartbeat does not satisfy it.

**3. Movement is blocked while standing, by design.** `Move` (1008) requires `BalanceStand`
first, which faults a standing robot — so crouch before driving. Reject move commands with 409
while posture is `standing`.

## 5. Minimum viable version

If you only need "make the dog shake" and nothing else:

```python
await conn.connect()
await conn.datachannel.pub_sub.publish_request_new(
    RTC_TOPIC['MOTION_SWITCHER'], {'api_id': 1002, 'parameter': {'name': 'normal'}})
await asyncio.sleep(0.1)
resp = await conn.datachannel.pub_sub.publish_request_new(
    RTC_TOPIC['SPORT_MOD'], {'api_id': 1016})     # Hello
print(resp['data']['header']['status']['code'])   # 0 == success
```

Everything else in this document exists to make that safe to call repeatedly from a web app.

## Reference

Library: `legion1581/unitree_webrtc_connect`, branch `2.x.x`, firmware 1.1.9+.
Target IP is the robot's **internal wired** address (`192.168.123.161`), reachable from the
on-robot compute over RJ45 — not the WiFi address.
`"Max retries exceeded"` followed by `✓ Connected!` in the logs is normal (the library probes a
legacy endpoint first). Close the Unitree phone app — it holds the WebRTC slot and your
commands will be silently ignored.
