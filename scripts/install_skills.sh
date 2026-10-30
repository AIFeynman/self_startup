#!/usr/bin/env bash
# 把 skills/<板块> 软链到 Claude Code 与 Codex 的全局 skills 目录（前缀 ss-），
# 这样在任意 Claude Code / Codex 会话里也能直接用这些 skill（需平台在 8780 端口运行才能读写数据）。
# 用法：scripts/install_skills.sh [--uninstall]
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}/skills"
for d in skills/*/; do
  name="$(basename "$d")"; [[ "$name" == _* ]] && continue
  for target in "$CLAUDE_DIR" "$CODEX_DIR"; do
    link="$target/ss-$name"
    if [[ "${1:-}" == "--uninstall" ]]; then
      [[ -L "$link" ]] && rm "$link" && echo "removed $link"
    else
      mkdir -p "$target"
      if [[ -e "$link" && ! -L "$link" ]]; then echo "skip $link (exists, not a symlink)"; continue; fi
      ln -sfn "$ROOT/skills/$name" "$link" && echo "linked $link"
    fi
  done
done
