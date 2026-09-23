# Watch Dog dashboard for Jetson AGX Thor (JetPack 7, CUDA 13).
#
# Built on NVIDIA's vLLM image because it already ships a Thor-native
# PyTorch/torchvision/OpenCV stack and is already on the box (Elastic-Vision
# serves Cosmos from it), so the build adds only Watch Dog's pure-Python deps.
# The app code is NOT baked in: docker-compose mounts the git checkout at /app.
FROM nvcr.io/nvidia/vllm:26.01-py3

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pin the CUDA-built packages to exactly what the base image ships so no
# dependency can swap them for a generic wheel.
RUN pip freeze | grep -iE '^(torch|torchvision|numpy|opencv[a-z-]*)==' > /tmp/base-pins.txt \
 && cat /tmp/base-pins.txt \
 && pip install -c /tmp/base-pins.txt \
        flask==3.0.3 janus paramiko psutil boto3 \
        matplotlib pandas py-cpuinfo tqdm scipy seaborn ultralytics-thop \
        "git+https://github.com/ultralytics/CLIP.git" \
 && pip install --no-deps -c /tmp/base-pins.txt "ultralytics>=8.3.100,<9" \
 && python3 -c "import torch, torchvision, cv2, ultralytics, flask, clip; \
print('torch', torch.__version__, 'cv2', cv2.__version__, 'ultralytics', ultralytics.__version__)"

COPY entrypoint.sh /usr/local/bin/watchdog-entrypoint
RUN chmod +x /usr/local/bin/watchdog-entrypoint

WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/watchdog-entrypoint"]
CMD ["python3", "web_app.py"]
