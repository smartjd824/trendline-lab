#!/bin/zsh
cd "$(dirname "$0")"
echo "TrendLine Quant Lab 시작 중... http://127.0.0.1:8000"
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
