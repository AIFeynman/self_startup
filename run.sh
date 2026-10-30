#!/usr/bin/env bash
# 启动本地学习平台：http://127.0.0.1:8780
#   ./run.sh        前台运行
#   ./run.sh -d     后台常驻（日志 data/logs/server.log），关掉终端 / 会话也不会停
#   ./run.sh stop   停止后台服务
# 改动自动生效：web/ 改了页面自动刷新；app/ 改了等后台任务和对话都结束后自动重启（不会杀任务）。
cd "$(dirname "$0")"
PORT="${PORT:-8780}"
running() { lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; }
case "$1" in
  stop)
    pkill -f "app.supervisor" && echo "已停止" || echo "没有在运行的 supervisor"
    sleep 1; running && kill $(lsof -tiTCP:"${PORT}" -sTCP:LISTEN) 2>/dev/null
    exit 0 ;;
  -d)
    shift
    if running; then echo "已在运行：http://127.0.0.1:${PORT}"; exit 0; fi
    mkdir -p data/logs
    nohup uv run python -m app.supervisor "$@" >> data/logs/server.log 2>&1 < /dev/null &
    echo "后台启动：http://127.0.0.1:${PORT}（日志 data/logs/server.log）"
    exit 0 ;;
esac
exec uv run python -m app.supervisor "$@"
