#!/usr/bin/env python3
"""
RTSP to MJPEG proxy for IR/Depth streams.

Run this on the Orin host to expose the RealSense IR and depth RTSP feeds
as simple MJPEG HTTP endpoints that the dashboard can consume easily:

    python3 rtsp_proxy.py

This will listen on port 8600 and provide:
    http://0.0.0.0:8600/ir.mjpg
    http://0.0.0.0:8600/depth.mjpg
"""
import cv2
import threading
import time
from flask import Flask, Response, jsonify

IR_RTSP = "rtsp://127.0.0.1:8554/ir"
DEPTH_RTSP = "rtsp://127.0.0.1:8554/depth"
HTTP_PORT = 8600

app = Flask(__name__)


class StreamBridge:
    def __init__(self, name: str, source: str):
        self.name = name
        self.source = source
        self.lock = threading.Lock()
        self.frame = None
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        self.thread = None

    def _capture_loop(self):
        """Continuously pull frames from the RTSP source and store latest."""
        retries = 0
        while self.running:
            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                if retries % 5 == 0:
                    print(f"[proxy:{self.name}] Unable to open RTSP stream, retrying...")
                retries += 1
                time.sleep(1)
                continue

            print(f"[proxy:{self.name}] RTSP stream opened")
            retries = 0
            while self.running:
                ret, frame = cap.read()
                if not ret or frame is None:
                    print(f"[proxy:{self.name}] RTSP frame read failed, reconnecting...")
                    break
                with self.lock:
                    self.frame = frame
            cap.release()
            time.sleep(0.5)  # brief pause before reconnect

    def mjpeg_generator(self):
        """Yield JPEG frames for MJPEG streaming."""
        while True:
            if not self.running:
                time.sleep(0.1)
                continue

            with self.lock:
                frame = None if self.frame is None else self.frame.copy()

            if frame is None:
                time.sleep(0.05)
                continue

            success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not success:
                time.sleep(0.05)
                continue

            jpg_bytes = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpg_bytes + b"\r\n"
            )


ir_bridge = StreamBridge("ir", IR_RTSP)
depth_bridge = StreamBridge("depth", DEPTH_RTSP)


@app.route("/ir.mjpg")
def ir_stream():
    return Response(ir_bridge.mjpeg_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/depth.mjpg")
def depth_stream():
    return Response(depth_bridge.mjpeg_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/health")
def health():
    status = {
        "ir_running": ir_bridge.running,
        "depth_running": depth_bridge.running,
    }
    return jsonify(status)


def main():
    ir_bridge.start()
    depth_bridge.start()
    try:
        app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True)
    finally:
        ir_bridge.stop()
        depth_bridge.stop()


if __name__ == "__main__":
    main()
