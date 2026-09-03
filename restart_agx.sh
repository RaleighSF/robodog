#!/bin/bash
# Restart script for AGX web app

echo "🔍 Finding web_app processes..."
ps aux | grep web_app.py | grep -v grep

echo ""
echo "🛑 Killing all web_app processes..."
pkill -9 -f web_app.py

echo "⏳ Waiting for cleanup..."
sleep 3

echo "🚀 Starting web app on 0.0.0.0:8000..."
cd "$(dirname "$0")"
nohup python3 web_app.py > web_app.log 2>&1 &

echo "✅ Web app started! Check logs with: tail -f web_app.log"
echo "📊 Access at: http://192.168.50.208:8000"
