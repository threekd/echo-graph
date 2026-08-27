#!/usr/bin/env bash
# Litnebula VPS 一键初始化(Ubuntu 22.04 / 24.04+)
# 用法: sudo bash setup-vps.sh <域名> [certbot邮箱]
# 示例: sudo bash setup-vps.sh litnebula.com admin@example.com
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
if [[ "$REPO_URL" == *"你的仓库地址"* ]]; then
  echo "!! 请先修改本脚本顶部的 REPO_URL(仓库地址),再运行初始化" >&2
  exit 1
fi

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
  echo "!! 已生成 $APP_DIR/.env,请先填入 ADMIN_BOOTSTRAP_EMAIL 后再启动服务"
fi

echo "==> 8/9 构建前端"
sudo -u "$APP_USER" bash -lc "cd '$APP_DIR/frontend' && pnpm install --frozen-lockfile && pnpm build"

echo "==> 9/9 安装 systemd 服务 + nginx + HTTPS"
install -m 644 "$APP_DIR/deploy/echo-graph.service" /etc/systemd/system/echo-graph.service
systemctl daemon-reload
systemctl enable echo-graph

tee /etc/nginx/sites-available/echo-graph >/dev/null <<EOF
# 由 setup-vps.sh 自动生成
# X-Forwarded-For 直接用 \$remote_addr(单层代理):不要用
# \$proxy_add_x_forwarded_for 追加客户端可控值,否则可伪造最左 IP
# 绕过应用层限流(app/ratelimit.py 从右向左解析)。
server {
    listen 80;
    server_name $DOMAIN;

    root $APP_DIR/frontend/dist;
    index index.html;

    # 安全响应头(HTTPS 部署时 HSTS 生效;CSP 若引入新外部资源需同步调整)
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; object-src 'none'; base-uri 'self'; form-action 'self'" always;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }

    location /assets/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        # 子块定义 add_header 后不再继承 server 级头,需重复安全头
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header Referrer-Policy strict-origin-when-cross-origin always;
        add_header Strict-Transport-Security "max-age=31536000" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; object-src 'none'; base-uri 'self'; form-action 'self'" always;
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
echo "  1) 编辑 $APP_DIR/.env,填入 ADMIN_BOOTSTRAP_EMAIL(第一个管理员邮箱)"
echo "  2) sudo systemctl start echo-graph"
echo "  3) 验证: curl https://$DOMAIN/api/health"
echo "  4) 如需防火墙: sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw --force enable"
echo "  5) 私有仓库若用 SSH 克隆,需为 $APP_USER 配置 deploy key:"
echo "     sudo -u $APP_USER ssh-keygen -t ed25519 && sudo cat /home/$APP_USER/.ssh/id_ed25519.pub(加入仓库 Deploy keys)"
