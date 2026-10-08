#!/bin/bash
# ============================================================================
# 系统基线：时区 / 依赖 / iptables 白名单 / BBR
#
# 通过 `python scripts/ssh_run.py -f scripts/setup_base.sh` 执行。
# 所有参数从 deploy.env 注入的环境变量读取（ssh_run.py 会自动 export）。
#
# ⚠️ 本脚本不使用 UFW。
#    Debian 12+ 上 ufw 与 iptables-persistent / netfilter-persistent 互斥
#    （ufw 的包声明了 Breaks:），安装 ufw 会把 iptables-persistent 卸掉，
#    留下一套残缺规则，非常容易把自己锁在外面。直接用纯 iptables。
# ============================================================================
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------- 参数
SSH_PORT="${SSH_PORT:-22}"
PANEL_PORT="${PANEL_PORT:-46821}"
SUB_PORT="${SUB_PORT:-2096}"
REALITY_PORT="${REALITY_PORT:-443}"
HY2_PORT="${HY2_PORT:-443}"
TUIC_PORT="${TUIC_PORT:-8443}"
HY2_HOP_RANGE="${HY2_HOP_RANGE:-58888:60888}"
ACME_PORT="${ACME_PORT:-80}"

echo "########## 参数 ##########"
cat <<EOF
SSH_PORT        = ${SSH_PORT}
ACME_PORT       = ${ACME_PORT}
PANEL_PORT      = ${PANEL_PORT}
SUB_PORT        = ${SUB_PORT}
REALITY_PORT    = ${REALITY_PORT} (tcp)
HY2_PORT        = ${HY2_PORT} (udp)
TUIC_PORT       = ${TUIC_PORT} (udp)
HY2_HOP_RANGE   = ${HY2_HOP_RANGE} (udp)
EOF

# ---------------------------------------------------------------- 1. 依赖
echo ""
echo "########## 1. 安装基础依赖 ##########"
apt-get update -y
apt-get install -y \
  sudo curl wget ca-certificates unzip socat cron tzdata jq sqlite3 \
  iptables iptables-persistent netfilter-persistent

echo "########## 2. 设置时区 Asia/Shanghai ##########"
timedatectl set-timezone Asia/Shanghai 2>/dev/null \
  || ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
date

# ---------------------------------------------------------------- 3. 防火墙
echo ""
echo "########## 3. 备份现有 iptables 规则（回滚用） ##########"
mkdir -p /root/.xui-skill
cp -f /etc/iptables/rules.v4 /root/.xui-skill/rules.v4.bak 2>/dev/null || true
cp -f /etc/iptables/rules.v6 /root/.xui-skill/rules.v6.bak 2>/dev/null || true
echo "已备份到 /root/.xui-skill/rules.v{4,6}.bak"

echo "########## 4. 写入 IPv4 规则 ##########"
cat > /etc/iptables/rules.v4 <<EOF
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -i lo -j ACCEPT
-A INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-A INPUT -p icmp --icmp-type echo-request -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${SSH_PORT} -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${ACME_PORT} -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${REALITY_PORT} -j ACCEPT
-A INPUT -p udp -m udp --dport ${HY2_PORT} -j ACCEPT
-A INPUT -p udp -m udp --dport ${HY2_HOP_RANGE} -j ACCEPT
-A INPUT -p udp -m udp --dport ${TUIC_PORT} -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${SUB_PORT} -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${PANEL_PORT} -j ACCEPT
-A INPUT -m conntrack --ctstate INVALID -j DROP
COMMIT
*nat
:PREROUTING ACCEPT [0:0]
:INPUT ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
:POSTROUTING ACCEPT [0:0]
-A PREROUTING -p udp -m udp --dport ${HY2_HOP_RANGE} -j REDIRECT --to-ports ${HY2_PORT}
COMMIT
EOF

echo "########## 5. 写入 IPv6 规则 ##########"
cat > /etc/iptables/rules.v6 <<EOF
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -i lo -j ACCEPT
-A INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-A INPUT -p ipv6-icmp -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${SSH_PORT} -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${ACME_PORT} -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${REALITY_PORT} -j ACCEPT
-A INPUT -p udp -m udp --dport ${HY2_PORT} -j ACCEPT
-A INPUT -p udp -m udp --dport ${HY2_HOP_RANGE} -j ACCEPT
-A INPUT -p udp -m udp --dport ${TUIC_PORT} -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${SUB_PORT} -j ACCEPT
-A INPUT -p tcp -m tcp --dport ${PANEL_PORT} -j ACCEPT
-A INPUT -m conntrack --ctstate INVALID -j DROP
COMMIT
*nat
:PREROUTING ACCEPT [0:0]
:INPUT ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
:POSTROUTING ACCEPT [0:0]
-A PREROUTING -p udp -m udp --dport ${HY2_HOP_RANGE} -j REDIRECT --to-ports ${HY2_PORT}
COMMIT
EOF

echo "########## 6. 应用规则（带 180 秒自动回滚保险） ##########"
# 万一规则写错把自己锁在外面，180 秒后自动恢复旧规则。
# 确认能正常登录后，执行： kill "$(cat /root/.xui-skill/fw_rollback.pid)"
nohup sh -c "sleep 180; iptables-restore < /root/.xui-skill/rules.v4.bak 2>/dev/null; \
             ip6tables-restore < /root/.xui-skill/rules.v6.bak 2>/dev/null" \
      >/dev/null 2>&1 &
echo $! > /root/.xui-skill/fw_rollback.pid
echo "回滚定时器 PID: $(cat /root/.xui-skill/fw_rollback.pid)（180 秒后触发）"

iptables-restore < /etc/iptables/rules.v4
ip6tables-restore < /etc/iptables/rules.v6

echo "--- INPUT 链 ---"
iptables -S INPUT
echo "--- nat PREROUTING ---"
iptables -t nat -S PREROUTING

netfilter-persistent save >/dev/null 2>&1 && echo "规则已持久化"

# ---------------------------------------------------------------- 7. BBR
echo ""
echo "########## 7. 开启 BBR + 内核调优 ##########"
# ⚠️ Debian 13 起 /etc/sysctl.conf 已废弃，用 /etc/sysctl.d/*.conf
cat > /etc/sysctl.d/99-network-tuning.conf <<'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
fs.file-max = 1000000
EOF
sysctl --system >/dev/null 2>&1

echo "--- 拥塞控制 ---"
sysctl net.ipv4.tcp_congestion_control
sysctl net.core.default_qdisc
echo "--- 可用算法 ---"
sysctl net.ipv4.tcp_available_congestion_control

# ---------------------------------------------------------------- 8. 校验
echo ""
echo "########## 8. 网卡与监听 ##########"
ip -brief addr
echo "--- 当前监听端口 ---"
ss -lntup | head -30 || true

echo ""
echo "########## BASE SETUP DONE ##########"
echo "提醒：确认 SSH 仍可登录后，执行下面这条关掉回滚定时器："
echo "  kill \$(cat /root/.xui-skill/fw_rollback.pid) 2>/dev/null"
