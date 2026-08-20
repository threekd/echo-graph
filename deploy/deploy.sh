#!/usr/bin/env bash
# Echo Graph 更新部署(备份数据 → 拉代码 → 装依赖 → 生成兜底种子 → 构建前端 → 重启服务)
# 用法: sudo -u echograph bash deploy/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/echo-graph}"
cd "$APP_DIR"

echo "==> 备份本地数据(data/real、版本快照、投稿库)"
mkdir -p backups
BK_FILE="backups/data-$(date +%Y%m%d-%H%M%S).tgz"
tar czf "$BK_FILE" data/real data/versions data/snapshots data/contributions.db 2>/dev/null || true
# 只保留最近 14 份备份
ls -1t backups/data-*.tgz 2>/dev/null | tail -n +15 | xargs -r rm -f

echo "==> 拉取最新代码"
if [[ -n "$(git status --porcelain data/real)" ]]; then
  echo "!! 注意:data/real 存在本地修改。请先按 DEPLOY.md「数据回传」提交并推送," >&2
  echo "   否则 git pull 会因本地修改而失败。" >&2
fi
if ! git pull --ff-only; then
  echo "!! 拉取失败(通常为 data/real 本地修改或本地未推送提交)。" >&2
  echo "   如需回滚到拉取前数据: sudo -u echograph tar xzf '$BK_FILE'" >&2
  exit 1
fi

echo "==> 后端依赖"
uv sync --frozen

echo "==> 生成 JSON 兜底种子(Neo4j 不可用时使用)"
uv run python scripts/export_seed.py

echo "==> 构建前端"
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..

echo "==> 重启服务"
sudo systemctl restart echo-graph

echo "==> 等待健康检查"
for i in 1 2 3 4 5 6; do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "==> 完成: $(date '+%F %T')(健康检查通过)"
    exit 0
  fi
  sleep 2
done
echo "!! 健康检查失败,请查看: journalctl -u echo-graph -e"
exit 1
