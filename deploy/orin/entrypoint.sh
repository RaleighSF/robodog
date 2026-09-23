#!/bin/bash
set -e
source /opt/ros/humble/setup.bash
[ -f /opt/unitree_ws/install/setup.bash ] && source /opt/unitree_ws/install/setup.bash
exec python3 -u /opt/watchdog/go2_service.py
