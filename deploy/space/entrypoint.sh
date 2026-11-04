#!/bin/sh
# 7860 is the Space's app_port; an UptimeRobot ping on /health keeps the free Space awake.
exec python -m backend.worker --loop --health-port 7860
