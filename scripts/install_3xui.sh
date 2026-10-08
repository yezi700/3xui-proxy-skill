#!/bin/bash
# ============================================================================
# 3x-ui 非交互安装 + Let's Encrypt 证书
#
# 通过 `python scripts/ssh_run.py -f scripts/install_3xui.sh` 执行。
# 参数从 deploy.env 注入的环境变量读取。
#
# 前提：
#   * 域名已解析到本机公网 IP（dig +short $DOMAIN 应返回 $SERVER_IP）
#   * 80 端口可达且未被占用（ACME HTTP-01 需要）
# ============================================================================
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive
cd /root || exit 1

PANEL_USER="${PANEL_USER:-admin}"
PANEL_PASS="${PANEL_PASS:-}"
PANEL_PORT="${PANEL_PORT:-46821}"
PANEL_PATH="${PANEL_PATH:-}"
DOMAIN="${DOMAIN:-}"
SERVER_IP="${SERVER_IP:-}"
ACME_PORT="${ACME_PORT:-80}"

if [ -z "$PANEL_PASS" ]; then
  PANEL_PASS="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)"
  echo "未提供 PANEL_PASS，已随机生成"
fi
if [ -z "$PANEL_PATH" ]; then
  PANEL_PATH="$(head -c 24 /dev/urandom | base64 | tr -dc 'a-z0-9' | head -c 16)"
  echo "未提供 PANEL_PATH，已随机生成"
fi

echo "########## 安装参数 ##########"
echo "PANEL_USER = ${PANEL_USER}"
echo "PANEL_PASS = ***"
echo "PANEL_PORT = ${PANEL_PORT}"
echo "PANEL_PATH = ${PANEL_PATH}"
echo "DOMAIN     = ${DOMAIN}"
echo "SERVER_IP  = ${SERVER_IP}"

# ---------------------------------------------------------------- 前置检查
echo ""
echo "########## 1. 前置检查 ##########"
if [ -n "$DOMAIN" ]; then
  RESOLVED="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1)"
  echo "DNS 解析: ${DOMAIN} -> ${RESOLVED:-<失败>}"
  if [ -n "$SERVER_IP" ] && [ "$RESOLVED" != "$SERVER_IP" ]; then
    echo "⚠️  DNS 解析结果与 SERVER_IP 不一致，ACME 申请可能失败。"
  fi
fi

if ss -lntp 2>/dev/null | grep -q ":${ACME_PORT} "; then
  echo "⚠️  ${ACME_PORT} 端口已被占用，ACME standalone 会失败："
  ss -lntp | grep ":${ACME_PORT} "
fi

# ---------------------------------------------------------------- 安装
echo ""
echo "########## 2. 下载官方安装脚本 ##########"
curl -Ls --retry 3 --connect-timeout 20 -o /root/3xui-install.sh \
  https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh
ls -l /root/3xui-install.sh
head -3 /root/3xui-install.sh

echo ""
echo "########## 3. 设置非交互参数 ##########"
export XUI_NONINTERACTIVE=1
export XUI_USERNAME="$PANEL_USER"
export XUI_PASSWORD="$PANEL_PASS"
export XUI_PANEL_PORT="$PANEL_PORT"
export XUI_WEB_BASE_PATH="$PANEL_PATH"
export XUI_ACME_HTTP_PORT="$ACME_PORT"

if [ -n "$DOMAIN" ]; then
  export XUI_SSL_MODE="domain"
  export XUI_DOMAIN="$DOMAIN"
else
  export XUI_SSL_MODE="ip"
  export XUI_SERVER_IP="$SERVER_IP"
fi

env | grep '^XUI_' | sed 's/\(PASSWORD=\).*/\1***/'

echo ""
echo "########## 4. 执行安装 ##########"
bash /root/3xui-install.sh 2>&1 | tee /root/3xui-install.log
INSTALL_RC="${PIPESTATUS[0]}"
echo "安装脚本退出码: ${INSTALL_RC}"

# ---------------------------------------------------------------- 校验
echo ""
echo "########## 5. 服务状态 ##########"
systemctl is-active x-ui || true
systemctl is-enabled x-ui || true
ss -lntp | grep -E ":${PANEL_PORT} " || echo "⚠️  面板端口 ${PANEL_PORT} 未监听"

echo ""
echo "########## 6. 面板设置 ##########"
/usr/local/x-ui/x-ui setting -show 2>/dev/null || true

echo ""
echo "########## 7. 证书 ##########"
if [ -n "$DOMAIN" ]; then
  ls -l "/root/cert/${DOMAIN}/" 2>/dev/null || \
  ls -l "/root/.acme.sh/${DOMAIN}_ecc/" 2>/dev/null || \
  echo "⚠️  未找到证书目录，检查 acme.sh 日志"
fi

echo ""
echo "########## 8. 读取 API Token ##########"
API_TOKEN="$(sqlite3 /etc/x-ui/x-ui.db \
  "select value from settings where key='apiToken';" 2>/dev/null || true)"
echo "API_TOKEN = ${API_TOKEN:-<未取到，可在面板设置里查看>}"

# ---------------------------------------------------------------- 结果落盘
echo ""
echo "########## 9. 写入 /etc/x-ui/install-result.env ##########"
cat > /etc/x-ui/install-result.env <<EOF
PANEL_USER=${PANEL_USER}
PANEL_PASS=${PANEL_PASS}
PANEL_PORT=${PANEL_PORT}
PANEL_PATH=${PANEL_PATH}
DOMAIN=${DOMAIN}
SERVER_IP=${SERVER_IP}
API_TOKEN=${API_TOKEN}
PANEL_URL=https://${DOMAIN:-$SERVER_IP}:${PANEL_PORT}/${PANEL_PATH}/
INSTALL_RC=${INSTALL_RC}
EOF
chmod 600 /etc/x-ui/install-result.env
cat /etc/x-ui/install-result.env

echo ""
echo "########## INSTALL DONE ##########"
