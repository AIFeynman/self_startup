#!/usr/bin/env bash
# 阿里云 GPU 实例初始化：Python venv + PyTorch(CUDA) + Jupyter Server（只听 127.0.0.1，经 SSH 隧道访问）。可重复执行。
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
PIP="-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com"
mkdir -p /root/work
if [ ! -x /root/venv/bin/python ]; then
  apt-get update -qq >/dev/null && apt-get install -y -qq python3-venv python3-pip >/dev/null
  python3 -m venv /root/venv
  /root/venv/bin/pip install -q -U pip $PIP
  /root/venv/bin/pip install -q $PIP torch==2.6.0 ipykernel jupyter_server numpy httpx
fi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
/root/venv/bin/python -c "import torch;print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
pkill -f "jupyter-server" 2>/dev/null || true
cd /root/work
SS_PLATFORM=http://127.0.0.1:18780 SS_RUNTIME=cloud SS_WORK=/root/work nohup /root/venv/bin/jupyter server --no-browser --allow-root --ip=127.0.0.1 --port=8888 \
  --IdentityProvider.token="$SS_TOKEN" --ServerApp.root_dir=/root/work > /root/jupyter.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "jupyter %{http_code}\n" -H "Authorization: token $SS_TOKEN" http://127.0.0.1:8888/api/status
