#!/usr/bin/env bash
# Litnebula 更新部署(备份数据 → 拉代码 → 装依赖 → 重建 SQLite → 构建前端 → 重启服务)
# 用法: sudo -u echograph bash deploy/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/echo-graph}"
cd "$APP_DIR"

echo "==> 备份本地数据(data/export、历史目录、SQLite 权威库)"
mkdir -p backups
BK_FILE="backups/data-$(date +%Y%m%d-%H%M%S).tgz"
tar czf "$BK_FILE" data/export data/versions data/snapshots 2>/dev/null || true
# SQLite 权威库用 sqlite3 .backup 一致性快照(WAL 模式不能直接拷贝)
if [[ -f data/echo-graph.db ]]; then
  DB_BK="backups/echo-graph-$(date +%Y%m%d-%H%M%S).db"
  uv run --frozen python -c "import sqlite3,sys; s=sqlite3.connect('data/echo-graph.db'); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close()" "$DB_BK"
  echo "==> SQLite 已备份: $DB_BK"
fi
# 只保留最近 14 份备份
ls -1t backups/data-*.tgz 2>/dev/null | tail -n +15 | xargs -r rm -f
ls -1t backups/echo-graph-*.db 2>/dev/null | tail -n +15 | xargs -r rm -f

echo "==> 拉取最新代码"
if [[ -n "$(git status --porcelain data/export)" ]]; then
  echo "!! 注意:data/export 存在本地修改。请先按 DEPLOY.md「数据回传」提交并推送," >&2
  echo "   否则 git pull 会因本地修改而失败。" >&2
fi
if ! git pull --ff-only; then
  echo "!! 拉取失败(通常为 data/export 本地修改或本地未推送提交)。" >&2
  echo "   如需回滚到拉取前数据: sudo -u echograph tar xzf '$BK_FILE'" >&2
  exit 1
fi

echo "==> 后端依赖"
uv sync --frozen

echo "==> 从仓库 CSV 重建 SQLite(贡献与审计表不受影响;数据回传请先按 DEPLOY.md 提交)"
uv run python scripts/migrate_csv_to_sqlite.py

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
