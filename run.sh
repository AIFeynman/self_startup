#!/usr/bin/env bash
# 启动本地学习平台：http://127.0.0.1:8780
#   ./run.sh      前台运行
#   ./run.sh -d   后台常驻（日志 data/logs/server.log），关掉终端 / 会话也不会停，后台任务不会被杀
cd "$(dirname "$0")"
if [ "$1" = "-d" ]; then
  shift
  if lsof -nP -iTCP:"${PORT:-8780}" -sTCP:LISTEN >/dev/null 2>&1; then echo "已在运行：http://127.0.0.1:${PORT:-8780}"; exit 0; fi
  mkdir -p data/logs
  nohup uv run uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8780}" "$@" >> data/logs/server.log 2>&1 < /dev/null &
  echo "后台启动：http://127.0.0.1:${PORT:-8780}（日志 data/logs/server.log）"
  exit 0
fi
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8780}" "$@"
