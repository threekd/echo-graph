#!/usr/bin/env bash
# Litnebula 更新部署(备份数据 → 拉代码 → 装依赖 → 构建前端 → 重启服务)
# 用法: sudo -u echograph bash deploy/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/echo-graph}"
cd "$APP_DIR"

# sudo -u echograph 会重置 PATH;uv 装在用户目录下,需显式加入,
# 否则非登录 shell 下执行会报 uv: command not found
export PATH="$HOME/.local/bin:$PATH"

echo "==> 备份本地数据(历史目录、SQLite 权威库)"
mkdir -p backups
BK_FILE="backups/data-$(date +%Y%m%d-%H%M%S).tgz"
BACKUP_DIRS=()
for d in data/versions; do
  if [[ -d "$d" ]]; then BACKUP_DIRS+=("$d"); fi
done
if [[ ${#BACKUP_DIRS[@]} -gt 0 ]]; then
  tar czf "$BK_FILE" "${BACKUP_DIRS[@]}" 2>/dev/null || echo "!! 数据目录打包失败(非致命,继续部署)"
fi
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
if ! git pull --ff-only; then
  echo "!! 拉取失败(通常为本地未推送提交或未提交改动)。" >&2
  echo "   如需回滚到拉取前数据: sudo -u echograph tar xzf '$BK_FILE'" >&2
  exit 1
fi

echo "==> 后端依赖"
uv sync --frozen

echo "==> SQLite 为权威库,schema 迁移由服务启动时自动执行"
echo "    备份/恢复一律走整库快照(backups/ 下 .db),不再有 CSV 导出层"

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
