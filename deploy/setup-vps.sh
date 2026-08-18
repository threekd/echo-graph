#!/usr/bin/env bash
# Echo Graph VPS 一键初始化(Ubuntu 22.04 / 24.04+)
# 用法: sudo bash setup-vps.sh <域名> [certbot邮箱]
# 示例: sudo bash setup-vps.sh graph.example.com admin@example.com
set -euo pipefail

DOMAIN="${1:-}"
CERTBOT_EMAIL="${2:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "用法: sudo bash setup-vps.sh <域名> [certbot邮箱]" >&2
  exit 1
fi

APP_USER="echograph"
APP_DIR="/opt/echo-graph"
REPO_URL="<你的仓库地址,例如 git@github.com:user/echo-graph.git>"

echo "==> 1/9 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git curl ca-certificates nginx certbot python3-certbot-nginx

echo "==> 2/9 安装 Node.js 24 + pnpm"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
  apt-get install -y nodejs
fi
npm install -g pnpm@11

echo "==> 3/9 创建应用用户 $APP_USER"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$APP_USER"
fi

echo "==> 4/9 安装 uv(Python 3.14 由 uv 托管下载)"
sudo -u "$APP_USER" bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "==> 5/9 拉取代码"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
  chown -R "$APP_USER:$APP_USER" "$APP_DIR"
else
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
fi

echo "==> 6/9 安装后端依赖(自动下载 Python 3.14)"
sudo -u "$APP_USER" bash -lc "cd '$APP_DIR' && ~/.local/bin/uv sync --frozen"

echo "==> 7/9 配置 .env"
if [[ ! -f "$APP_DIR/.env" ]]; then
  sudo -u "$APP_USER" cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "!! 已生成 $APP_DIR/.env,请先填入 NEO4J_* 与 ADMIN_TOKEN 后再启动服务"
fi

echo "==> 8/9 构建前端"
sudo -u "$APP_USER" bash -lc "cd '$APP_DIR/frontend' && pnpm install --frozen-lockfile && pnpm build"

echo "==> 9/9 安装 systemd 服务 + nginx + HTTPS"
install -m 644 "$APP_DIR/deploy/echo-graph.service" /etc/systemd/system/echo-graph.service
systemctl daemon-reload
systemctl enable echo-graph

tee /etc/nginx/sites-available/echo-graph >/dev/null <<EOF
# 由 setup-vps.sh 自动生成
server {
    listen 80;
    server_name $DOMAIN;

    root $APP_DIR/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }

    location /assets/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        try_files \$uri /index.html;
    }
}
EOF
ln -sf /etc/nginx/sites-available/echo-graph /etc/nginx/sites-enabled/echo-graph
nginx -t
systemctl reload nginx

if [[ -n "$CERTBOT_EMAIL" ]]; then
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$CERTBOT_EMAIL" --redirect
else
  echo "!! 未提供邮箱,跳过证书;之后手动执行: sudo certbot --nginx -d $DOMAIN"
fi

# 允许应用用户重启服务(供 deploy.sh 使用)
echo "$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart echo-graph" > /etc/sudoers.d/echo-graph
chmod 440 /etc/sudoers.d/echo-graph

echo "==> 初始化完成"
echo "接下来:"
echo "  1) 编辑 $APP_DIR/.env,填入 NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / ADMIN_TOKEN"
echo "  2) sudo systemctl start echo-graph"
echo "  3) 验证: curl https://$DOMAIN/api/health"
echo "  4) 如需防火墙: sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw --force enable"
