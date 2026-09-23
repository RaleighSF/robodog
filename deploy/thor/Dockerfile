# Watch Dog dashboard for Jetson AGX Thor (JetPack 7, CUDA 13).
#
# Built on NVIDIA's vLLM image because it already ships a Thor-native
# PyTorch/torchvision/OpenCV stack and is already on the box (Elastic-Vision
# serves Cosmos from it), so the build adds only Watch Dog's pure-Python deps.
# The app code is NOT baked in: docker-compose mounts the git checkout at /app.
# nvcr.io/nvidia/vllm:26.01-py3, pinned to the digest Elastic-Vision runs.
FROM nvcr.io/nvidia/vllm@sha256:e497b1248ad3d916673a3003524c667640590a0c6d49f7f1c573102673d02792

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pin the CUDA-built packages to exactly what the base image ships so no
# dependency can swap them for a generic wheel.
COPY requirements-thor.txt /tmp/requirements-thor.txt
RUN pip freeze | grep -iE '^(torch|torchvision|numpy|opencv[a-z-]*)==' > /tmp/base-pins.txt \
 && cat /tmp/base-pins.txt \
 && pip install -c /tmp/base-pins.txt -r /tmp/requirements-thor.txt \
 && pip install --no-deps -c /tmp/base-pins.txt ultralytics==8.4.160 \
 && python3 -c "import torch, torchvision, cv2, ultralytics, flask, clip; \
print('torch', torch.__version__, 'cv2', cv2.__version__, 'ultralytics', ultralytics.__version__)"

# The vLLM base image's torch is compiled against cuDNN 9.18 but the image
# ships the 9.17.1 system library first on the path, so every convolution
# fails ("unable to find an engine"). vLLM never runs convs, YOLO always does:
# install the matching cuDNN wheel and put it ahead of the system copy.
RUN pip install -c /tmp/base-pins.txt \
        nvidia-cudnn-cu13==9.18.1.3 nvidia-cublas==13.8.0.4 nvidia-cuda-nvrtc==13.4.92 \
 && python3 -c "import nvidia.cudnn, os; print(os.path.join(list(nvidia.cudnn.__path__)[0], 'lib'))" > /etc/cudnn-lib-path
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/dist-packages/nvidia/cudnn/lib:${LD_LIBRARY_PATH}
RUN test "$(cat /etc/cudnn-lib-path)" = /usr/local/lib/python3.12/dist-packages/nvidia/cudnn/lib \
 && python3 -c "import torch; v = torch.backends.cudnn.version(); print('cudnn', v); assert v >= 91800"

COPY entrypoint.sh /usr/local/bin/watchdog-entrypoint
RUN chmod +x /usr/local/bin/watchdog-entrypoint

WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/watchdog-entrypoint"]
CMD ["python3", "web_app.py"]
