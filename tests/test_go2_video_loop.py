"""The robot link's video loop must survive a WebRTC library call that never returns.

Seen on the booth dog 2026-11-11: at power-on the first video connection delivered no decodable frames, the loop
logged "retry in 5s", and aiortc's pc.close() (inside the library's disconnect()) never returned. The loop never
retried, so the dashboard had no camera until someone restarted the service by hand.

Run: PYTHONPATH=../go2dds venv_311/bin/python tests/test_go2_video_loop.py
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import go2_service as G  # noqa: E402


class FakeVideo:
    def switchVideoChannel(self, on): pass
    def add_track_callback(self, cb): pass


def _install(conn_cls):
    drv = types.ModuleType("unitree_webrtc_connect.webrtc_driver")
    drv.UnitreeWebRTCConnection = conn_cls
    drv.WebRTCConnectionMethod = types.SimpleNamespace(LocalSTA="sta")
    pkg = types.ModuleType("unitree_webrtc_connect")
    pkg.webrtc_driver = drv
    sys.modules["unitree_webrtc_connect"] = pkg
    sys.modules["unitree_webrtc_connect.webrtc_driver"] = drv


def _run(conn_cls, seconds):
    _install(conn_cls)
    G.VIDEO_RECONNECT_S = 0.2; G.VIDEO_CALL_TIMEOUT_S = 0.3; G.VIDEO_RETRY_BASE_S = 0.1
    G.last_frame_mono = 0.0

    async def main():
        task = asyncio.ensure_future(G.video_loop())
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.new_event_loop().run_until_complete(main())


def test_a_disconnect_that_never_returns_does_not_stop_the_retries():
    made = []

    class Conn:
        def __init__(self, method, **kw):
            made.append(self); self.video = FakeVideo(); self.isConnected = True
        async def connect(self): pass
        async def disconnect(self):                      # aiortc pc.close() hanging, and deaf to cancellation
            while True:
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    pass

    _run(Conn, 8.0)   # the loop checks for frames every 2 s
    assert len(made) >= 3, "the loop reconnected only %d time(s); a hung disconnect stalled it" % len(made)


def test_a_connect_that_never_returns_is_abandoned_and_retried():
    made = []

    class Conn:
        def __init__(self, method, **kw):
            made.append(self); self.video = FakeVideo(); self.isConnected = False
        async def connect(self):
            await asyncio.sleep(3600)
        async def disconnect(self): pass

    _run(Conn, 4.0)
    assert len(made) >= 3, "the loop tried to connect only %d time(s); a hung connect stalled it" % len(made)


def test_bounded_returns_the_result_and_passes_errors_through():
    async def ok(): return 7
    async def boom(): raise ValueError("x")
    loop = asyncio.new_event_loop()
    assert loop.run_until_complete(G.bounded(ok(), 1.0, "ok")) == 7
    try:
        loop.run_until_complete(G.bounded(boom(), 1.0, "boom")); raise AssertionError("no error")
    except ValueError:
        pass


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("  PASS ", name)
            except Exception as e:                       # noqa: BLE001
                failed += 1; print("  FAIL ", name, "-", repr(e))
    print("%d failed" % failed); sys.exit(1 if failed else 0)
