#!/usr/bin/env bash
# Echo Graph 更新部署(拉代码 → 装依赖 → 构建前端 → 重启服务)
# 用法: sudo -u echograph bash deploy/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/echo-graph}"
cd "$APP_DIR"

echo "==> 拉取最新代码"
git pull --ff-only

echo "==> 后端依赖"
uv sync --frozen

echo "==> 构建前端"
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..

echo "==> 重启服务"
sudo systemctl restart echo-graph

echo "==> 完成: $(date '+%F %T')"
curl -fsS http://127.0.0.1:8000/api/health || echo "!! 健康检查失败,请查看: journalctl -u echo-graph -e"
