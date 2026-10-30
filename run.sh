#!/usr/bin/env bash
# 启动本地学习平台：http://127.0.0.1:8780
cd "$(dirname "$0")"
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8780}" "$@"
