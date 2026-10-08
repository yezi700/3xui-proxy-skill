#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""创建三个入站：VLESS-REALITY+Vision / Hysteria2 / TUIC v5。

执行方式（在技能目录下）：
    python scripts/deploy_nodes.py

原理：
    本机生成随机凭据与入站 payload → base64 → 通过 SSH 传到 VPS →
    在 VPS 上用 curl 调 127.0.0.1 的面板 API 写入。

    之所以要在 VPS 上跑 curl，是因为面板 API 只在 127.0.0.1 监听，
    且启用了 webDomain 后必须带 Host 头（脚本已处理）。

产出：
    /root/.xui-skill/node-credentials.json  （VPS 上，权限 600）
    终端打印全部凭据，请原样记入交付文档。
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import string
import sys
import uuid as uuidlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssh_run import get_client, load_env, run  # noqa: E402

AL = string.ascii_letters + string.digits
LOW = string.ascii_lowercase + string.digits


def rnd(n: int, alphabet: str = AL) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


def b64(obj) -> str:
    return base64.b64encode(
        json.dumps(obj, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")


# ---------------------------------------------------------------- 入站构造

def build_reality(cfg: dict, cred: dict) -> dict:
    reality_port = int(cfg.get("REALITY_PORT") or 443)
    return {
        "enable": True,
        "remark": f"{cfg.get('NODE_PREFIX', 'JP')}-Reality-Vision-{reality_port}",
        "listen": "",
        "port": reality_port,
        "protocol": "vless",
        "expiryTime": 0,
        "total": 0,
        "settings": {
            "clients": [{
                "id": cred["reality_uuid"],
                "flow": "xtls-rprx-vision",
                "email": "reality-%d" % reality_port,
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": 0,
                "subId": cred["reality_subid"],
                "comment": "Reality Vision",
                "reset": 0,
            }],
            "decryption": "none",
            "fallbacks": [],
        },
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "externalProxy": [],
            "realitySettings": {
                "show": False,
                "xver": 0,
                "dest": cred["reality_dest"],
                "serverNames": [cred["reality_sni"]],
                "privateKey": cred["reality_priv"],
                # ⚠️ 键名是 minClientVer，不是 minClient
                "minClientVer": "1.0.0",
                "maxClientVer": "",
                "maxTimeDiff": 0,
                "shortIds": [cred["reality_sid"]],
                "settings": {
                    "publicKey": cred["reality_pub"],
                    "fingerprint": "chrome",
                    "serverName": cred["reality_sni"],
                    "spiderX": "/" + rnd(15, LOW),
                },
            },
            "tcpSettings": {"acceptProxyProtocol": False, "header": {"type": "none"}},
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic", "fakedns"],
            "metadataOnly": False,
            "routeOnly": False,
        },
    }


def build_hysteria(cfg: dict, cred: dict) -> dict:
    hy2_port = int(cfg.get("HY2_PORT") or 443)
    hop = cfg.get("HY2_HOP_RANGE") or "58888:60888"
    domain = cfg["DOMAIN"]
    cert_dir = cfg.get("CERT_DIR") or f"/root/cert/{domain}"
    hop_ports = hop.replace(":", "-")   # 分享链接里用 58888-60888

    return {
        "enable": True,
        "remark": f"{cfg.get('NODE_PREFIX', 'JP')}-Hysteria2-{hy2_port}",
        "listen": "",
        "port": hy2_port,
        "protocol": "hysteria",
        "expiryTime": 0,
        "total": 0,
        "settings": {
            "version": 2,
            "clients": [{
                "email": "hy2-%d" % hy2_port,
                "auth": cred["hy2_auth"],
                "subId": cred["hy2_subid"],
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": 0,
                "comment": "Hysteria2",
                "reset": 0,
            }],
        },
        "streamSettings": {
            "network": "hysteria",
            "security": "tls",
            "externalProxy": [],
            "hysteriaSettings": {"version": 2, "auth": "", "udpIdleTimeout": 60},
            "tlsSettings": {
                "serverName": domain,
                "minVersion": "1.3",     # QUIC 强制 TLS1.3
                "maxVersion": "1.3",
                "cipherSuites": "",
                "rejectUnknownSni": False,
                "alpn": ["h3"],
                "certificates": [{
                    "certificateFile": f"{cert_dir}/fullchain.pem",
                    "keyFile": f"{cert_dir}/privkey.pem",
                    "ocspStapling": 3600,
                    "oneTimeLoading": False,
                    "usage": "encipherment",
                    "buildChain": False,
                }],
                "settings": {
                    "allowInsecure": False,
                    "fingerprint": "chrome",
                    "serverName": "",
                },
            },
            "finalmask": {
                "tcp": [],
                "udp": [{"type": "salamander",
                         "settings": {"password": cred["hy2_obfs_pw"]}}],
                "quicParams": {
                    "congestion": "bbr",
                    "udpHop": {"ports": hop_ports, "interval": "5-10"},
                },
            },
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic", "fakedns"],
            "metadataOnly": False,
            "routeOnly": False,
        },
    }


def build_tuic(cfg: dict, cred: dict) -> dict:
    tuic_port = int(cfg.get("TUIC_PORT") or 8443)
    domain = cfg["DOMAIN"]
    cert_dir = cfg.get("CERT_DIR") or f"/root/cert/{domain}"

    return {
        "enable": True,
        "remark": f"{cfg.get('NODE_PREFIX', 'JP')}-TUIC-v5-{tuic_port}",
        "listen": "",
        "port": tuic_port,
        "protocol": "tuic",
        "expiryTime": 0,
        "total": 0,
        "settings": {
            "server": {
                "certificate": f"{cert_dir}/fullchain.pem",
                "private_key": f"{cert_dir}/privkey.pem",
                "congestion_control": "bbr",
                "alpn": ["h3"],
                "udp_relay_mode": "native",
                "zero_rtt_handshake": True,
                "log_level": "info",
                "max_idle_time": 15,
                "authentication_timeout": 3,
                "max_udp_relay_packet_size": 1500,
                "sni": domain,
            },
            "clients": [{
                # ⚠️ id 和 uuid 必须同时给且相同，否则报 empty client ID
                "id": cred["tuic_uuid"],
                "uuid": cred["tuic_uuid"],
                "password": cred["tuic_password"],
                "email": "tuic-%d" % tuic_port,
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": 0,
                "subId": cred["tuic_subid"],
                "comment": "TUIC v5",
                "reset": 0,
            }],
        },
        "streamSettings": {
            "network": "tuic",
            "security": "none",
            "externalProxy": [],
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic", "fakedns"],
            "metadataOnly": False,
            "routeOnly": False,
        },
        "shareAddrStrategy": "custom",
        "shareAddr": domain,
    }


# ---------------------------------------------------------------- 远端脚本

REMOTE_SCRIPT = r"""
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive
BASE="https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/panel/api"
H1="Host: ${DOMAIN}"
AUTH="Authorization: Bearer ${API_TOKEN}"

mkdir -p /root/.xui-skill
cd /root/.xui-skill

echo "=== 0. 备份数据库 ==="
cp -f /etc/x-ui/x-ui.db "/root/.xui-skill/x-ui-backup-$(date +%Y%m%d-%H%M).db"
ls -l /root/.xui-skill/*.db | tail -2

echo "=== 1. 生成 REALITY 密钥对 ==="
XRAY_BIN="/usr/local/x-ui/bin/xray-linux-amd64"
[ -x "$XRAY_BIN" ] || XRAY_BIN="$(command -v xray)"
echo "使用: $XRAY_BIN"
"$XRAY_BIN" x25519 > /root/.xui-skill/x25519.txt 2>&1 || true
cat /root/.xui-skill/x25519.txt

# 兼容不同版本的输出格式（Private key / PrivateKey / 私钥）
PRIV="$(awk -F'[:：]' 'tolower($1) ~ /private/ {gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2; exit}' /root/.xui-skill/x25519.txt)"
PUB="$(awk  -F'[:：]' 'tolower($1) ~ /public/  {gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2; exit}' /root/.xui-skill/x25519.txt)"
# 兜底：某些版本输出两行纯 base64
if [ -z "$PRIV" ]; then PRIV="$(sed -n '1p' /root/.xui-skill/x25519.txt | awk '{print $NF}')"; fi
if [ -z "$PUB" ];  then PUB="$(sed -n '2p' /root/.xui-skill/x25519.txt | awk '{print $NF}')"; fi
echo "PRIV=$PRIV"
echo "PUB=$PUB"
if [ -z "$PRIV" ] || [ -z "$PUB" ]; then
  echo "!!! 无法解析 x25519 输出，请手动执行 $XRAY_BIN x25519 后填入 deploy.env 的 REALITY_PRIV / REALITY_PUB"
fi

# 用真实密钥覆盖 payload 里的占位符
for f in in_reality.json; do
  sed -i "s|__REALITY_PRIV__|$PRIV|g; s|__REALITY_PUB__|$PUB|g" "$f"
done

echo "=== 2. 写入入站 ==="
for pair in "reality:in_reality.json" "hy2:in_hy2.json" "tuic:in_tuic.json"; do
  name="${pair%%:*}"; file="${pair##*:}"
  echo "--- add $name ---"
  RESP="$(curl -sk -X POST -H "$H1" -H "$AUTH" \
       -H 'Content-Type: application/json' \
       --data-binary @"$file" "$BASE/inbounds/add")"
  echo "$RESP" | head -c 600; echo
  echo "$RESP" | grep -q '"success":true' || echo "!!! $name 添加失败"
done

echo "=== 3. 当前入站列表 ==="
curl -sk -H "$H1" -H "$AUTH" "$BASE/inbounds/list" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
for ib in (d.get("obj") or []):
    s=json.loads(ib.get("settings") or "{}")
    print("#%s  %s  %s/%s  clients=%d" % (ib.get("id"), ib.get("remark"),
          ib.get("protocol"), ib.get("port"), len(s.get("clients") or [])))'

echo "=== 4. 设置分享地址 ==="
curl -sk -H "$H1" -H "$AUTH" -X POST "$BASE/setting/all" > /root/.xui-skill/settings.json
# ⚠️ /setting/all 是 POST；/setting/update 是整体覆盖，必须拿全量改完再回写。
# ⚠️ heredoc 用引号定界符时 bash 不展开 ${VAR}，域名靠 sys.argv 传入。
python3 - "$DOMAIN" <<'PYEOF'
import json, sys
domain = sys.argv[1]
p = "/root/.xui-skill/settings.json"
d = json.load(open(p))
obj = d.get("obj") or {}
obj["shareAddrStrategy"] = "custom"
obj["shareAddr"] = domain
json.dump(obj, open("/root/.xui-skill/settings.new.json", "w"))
print("shareAddr ->", domain, "| 键数:", len(obj))
PYEOF
curl -sk -X POST -H "$H1" -H "$AUTH" -H 'Content-Type: application/json' \
  --data-binary @/root/.xui-skill/settings.new.json "$BASE/setting/update" | head -c 300
echo

echo "=== 5. 重启 Xray ==="
curl -sk -X POST -H "$H1" -H "$AUTH" "$BASE/setting/restartXrayService" | head -c 200
echo
systemctl restart x-ui
sleep 8
echo "x-ui: $(systemctl is-active x-ui)"

echo "=== 6. 分享链接 ==="
curl -sk -H "$H1" -H "$AUTH" "$BASE/inbounds/allLinks" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
for it in (d.get("obj") or []):
    print(it.get("remark"), "|", it.get("uri"))'

echo "=== DEPLOY DONE ==="
"""


def main() -> int:
    cfg = load_env()
    for key in ("VPS_HOST", "VPS_USER", "DOMAIN", "PANEL_PORT", "PANEL_PATH",
                "API_TOKEN"):
        if not cfg.get(key):
            sys.stderr.write(f"deploy.env 缺少 {key}\n")
            return 2

    # ---- 生成凭据 ----
    cred = {
        "reality_uuid": str(uuidlib.uuid4()),
        "reality_sid": secrets.token_hex(8),
        "reality_priv": "__REALITY_PRIV__",   # 由远端 xray x25519 填充
        "reality_pub": "__REALITY_PUB__",
        "reality_dest": cfg.get("REALITY_DEST") or "www.apple.com:443",
        "reality_sni": cfg.get("REALITY_SNI") or "www.apple.com",
        "hy2_auth": rnd(24),
        "hy2_obfs_pw": rnd(24),
        "tuic_uuid": str(uuidlib.uuid4()),
        "tuic_password": rnd(24),
        "reality_subid": rnd(16, LOW),
        "hy2_subid": rnd(16, LOW),
        "tuic_subid": rnd(16, LOW),
    }
    # 允许用 deploy.env 固定密钥（复现/迁移场景）
    if cfg.get("REALITY_PRIV") and cfg.get("REALITY_PUB"):
        cred["reality_priv"] = cfg["REALITY_PRIV"]
        cred["reality_pub"] = cfg["REALITY_PUB"]

    reality = build_reality(cfg, cred)
    hy2 = build_hysteria(cfg, cred)
    tuic = build_tuic(cfg, cred)

    payloads = {
        "in_reality.json": reality,
        "in_hy2.json": hy2,
        "in_tuic.json": tuic,
    }

    cli = get_client(cfg)
    try:
        run(cli, "mkdir -p /root/.xui-skill", timeout=30)
        # 写 payload（保持 __REALITY_PRIV__ 占位符，由远端 sed 替换）
        for name, obj in payloads.items():
            encoded = b64(obj)
            rc, out, err = run(
                cli,
                f"echo '{encoded}' | base64 -d > /root/.xui-skill/{name}",
                timeout=60,
            )
            if rc != 0:
                sys.stderr.write(f"写入 {name} 失败: {err}\n")
                return 1
            print(f"已写入 payload: {name}")

        # 写远端执行脚本
        encoded_script = b64(REMOTE_SCRIPT)
        run(cli, f"echo '{encoded_script}' | base64 -d > /root/.xui-skill/_deploy.sh",
            timeout=60)

        exports = "\n".join(
            f"export {k}='{v}'" for k, v in cfg.items()
            if k in ("PANEL_PORT", "PANEL_PATH", "DOMAIN", "API_TOKEN",
                     "PANEL_USER", "SERVER_IP")
        )
        rc, out, err = run(
            cli, f"{exports}\nbash /root/.xui-skill/_deploy.sh 2>&1",
            timeout=600,
        )
        sys.stdout.write(out)
        if err.strip():
            sys.stderr.write("\n[stderr]\n" + err)

        # 回读真实公钥（远端生成后写回文件）
        rc, pub_out, _ = run(
            cli,
            "grep -o '\"publicKey\"[^,]*' /root/.xui-skill/in_reality.json "
            "| head -1",
            timeout=30,
        )
        if pub_out.strip():
            cred["reality_pub"] = pub_out.split(":")[1].strip().strip('"')

        # 保存凭据到远端
        run(cli, "cat > /root/.xui-skill/node-credentials.json <<'EOF'\n"
                 + json.dumps(cred, ensure_ascii=False, indent=2)
                 + "\nEOF\nchmod 600 /root/.xui-skill/node-credentials.json",
            timeout=30)
    finally:
        cli.close()

    print("\n" + "=" * 64)
    print("生成的凭据（请原样记入交付文档）")
    print("=" * 64)
    for k, v in cred.items():
        print(f"{k:18s} = {v}")
    print("\n已保存到 VPS: /root/.xui-skill/node-credentials.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
