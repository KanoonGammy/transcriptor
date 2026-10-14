#!/bin/bash
set -e

echo "==================================================="
echo "    Transcriptor Pro - Speech to Text Webapp"
echo "==================================================="

if [ ! -d ".venv" ]; then
    echo "[INFO] Creating Python virtual environment..."
    python3 -m venv .venv
fi

echo "[INFO] Activating virtual environment..."
source .venv/bin/activate

echo "[INFO] Installing requirements..."
pip install -r requirements.txt

echo ""
echo "[INFO] Starting Transcriptor Pro server..."
echo "[INFO] Open your browser at: http://localhost:8000"
echo ""
python main.py
