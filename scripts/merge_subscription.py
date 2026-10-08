#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把三个入站合并成"一条订阅 URL 返回全部节点"。

背景（3x-ui v3.9.0）：
    * subId 全局唯一 → 三个入站不能共用一个 subId（会报 Duplicate subId）
    * 客户端被抽到 clients / client_inbounds 两张表 →
      直接改 inbound.settings.clients[] 无效，必须走 /panel/api/clients/*

正确做法：
    建 **一个** 客户端身份，用 inboundIds:[1,2,3] 绑定三个入站。
    model.Client 自带 id / password / auth / flow 四个独立字段，
    因此同一条身份可以同时承载：
        id       -> VLESS-REALITY 的 uuid，也是 TUIC 的 uuid
        password -> TUIC 的密码
        auth     -> Hysteria2 的认证密码
        flow     -> xtls-rprx-vision（Vision 必需，合并后最容易丢）

执行：
    python scripts/merge_subscription.py
"""
from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssh_run import get_client, load_env, run  # noqa: E402

REMOTE_SCRIPT = r"""
set -uo pipefail
BASE="https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/panel/api"
H1="Host: ${DOMAIN}"
AUTH="Authorization: Bearer ${API_TOKEN}"
CB="$BASE/clients"
CRED=/root/.xui-skill/node-credentials.json

[ -f "$CRED" ] || { echo "缺少 $CRED，请先跑 deploy_nodes.py"; exit 1; }

echo "=== 0. 备份数据库 ==="
cp -f /etc/x-ui/x-ui.db "/root/.xui-skill/x-ui-backup-$(date +%Y%m%d-%H%M).db"

echo "=== 1. 读取凭据 ==="
REALITY_UUID="$(python3 -c "import json;print(json.load(open('$CRED'))['reality_uuid'])")"
HY2_AUTH="$(python3     -c "import json;print(json.load(open('$CRED'))['hy2_auth'])")"
TUIC_PASSWORD="$(python3 -c "import json;print(json.load(open('$CRED'))['tuic_password'])")"
echo "reality_uuid  = $REALITY_UUID"
echo "hy2_auth      = $HY2_AUTH"
echo "tuic_password = $TUIC_PASSWORD"

echo "=== 2. 收集入站 ID ==="
curl -sk -H "$H1" -H "$AUTH" "$BASE/inbounds/list" > /root/.xui-skill/inbounds.json
python3 - <<'PYEOF'
import json
d = json.load(open("/root/.xui-skill/inbounds.json"))
ids = []
for ib in (d.get("obj") or []):
    if ib.get("protocol") in ("vless", "hysteria", "tuic"):
        ids.append(ib.get("id"))
        print("#%s %s/%s %s" % (ib.get("id"), ib.get("protocol"),
                                ib.get("port"), ib.get("remark")))
open("/root/.xui-skill/ids.txt", "w").write(",".join(str(i) for i in ids))
PYEOF
IDS="$(cat /root/.xui-skill/ids.txt)"
echo "inboundIds = [$IDS]"
[ -n "$IDS" ] || { echo "没找到可合并的入站"; exit 1; }

echo "=== 3. 创建合并客户端 ==="
# ⚠️ 必须手工构造 body。直接回写 GET 的对象会踩 id 类型陷阱：
#    model.Client.id 是 string，但 GET /clients/get/:email 返回的 id 是数字行号
# ⚠️ heredoc 用的是「引号定界符」，bash 不会展开 ${VAR}，
#    所以 email / subId 必须通过 sys.argv 传进去
python3 - "$IDS" "$REALITY_UUID" "$HY2_AUTH" "$TUIC_PASSWORD" \
        "$MERGED_EMAIL" "$MERGED_SUBID" <<'PYEOF' > /root/.xui-skill/merge.json
import json, sys
ids, rid, hauth, tpass, email, subid = sys.argv[1:7]
print(json.dumps({
    "client": {
        "id": rid,                    # VLESS uuid，同时也是 TUIC uuid
        "password": tpass,            # TUIC 密码
        "auth": hauth,                # Hysteria2 认证
        "flow": "xtls-rprx-vision",   # Reality Vision 必需
        "email": email,
        "subId": subid,
        "enable": True,
        "limitIp": 0,
        "totalGB": 0,
        "expiryTime": 0,
        "comment": "merged",
        "reset": 0,
    },
    "inboundIds": [int(x) for x in ids.split(",") if x],
}, ensure_ascii=False))
PYEOF
cat /root/.xui-skill/merge.json; echo

RESP="$(curl -sk -X POST -H "$H1" -H "$AUTH" -H 'Content-Type: application/json' \
        --data-binary @/root/.xui-skill/merge.json "$CB/add")"
echo "$RESP" | head -c 600; echo
echo "$RESP" | grep -q '"success":true' || echo "!!! 合并客户端创建失败"

echo "=== 4. 删除各入站上的原始客户端 ==="
for e in "reality-${REALITY_PORT}" "hy2-${HY2_PORT}" "tuic-${TUIC_PORT}"; do
  echo -n "del $e -> "
  curl -sk -X POST -H "$H1" -H "$AUTH" "$CB/del/$e" | head -c 200; echo
done

echo "=== 5. 校验 flow 是否保留 ==="
curl -sk -H "$H1" -H "$AUTH" "$CB/get/${MERGED_EMAIL}" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
o=d.get("obj") or {}
print("email=%s flow=%r id=%s" % (o.get("email"), o.get("flow"), o.get("id")))
if not o.get("flow"):
    print("!!! flow 丢失，需要补 update")'

echo "=== 6. 重启 Xray ==="
curl -sk -X POST -H "$H1" -H "$AUTH" "$BASE/setting/restartXrayService" | head -c 200
echo
systemctl restart x-ui
sleep 8
echo "x-ui: $(systemctl is-active x-ui)"

echo "=== 7. 合并后的分享链接 ==="
curl -sk -H "$H1" -H "$AUTH" "$BASE/inbounds/allLinks" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
for it in (d.get("obj") or []):
    print(it.get("remark"), "|", it.get("uri"))'

echo "=== 8. 订阅内容 ==="
echo "订阅地址: https://${DOMAIN}:${SUB_PORT}/${SUB_PATH}/${MERGED_SUBID}"
curl -sk "https://127.0.0.1:${SUB_PORT}/${SUB_PATH}/${MERGED_SUBID}" \
  -H "$H1" -o /root/.xui-skill/sub.txt -w "HTTP %{http_code}\n"
echo "--- 解码后 ---"
base64 -d /root/.xui-skill/sub.txt 2>/dev/null \
  | sed 's/#.*//' | cut -c1-80 || cat /root/.xui-skill/sub.txt | head -5

echo "=== MERGE DONE ==="
"""


def main() -> int:
    cfg = load_env()
    cfg.setdefault("MERGED_EMAIL", "merged")
    cfg.setdefault("MERGED_SUBID", "")
    cfg.setdefault("SUB_PORT", "2096")
    cfg.setdefault("SUB_PATH", "")
    cfg.setdefault("REALITY_PORT", "443")
    cfg.setdefault("HY2_PORT", "443")
    cfg.setdefault("TUIC_PORT", "8443")

    if not cfg.get("MERGED_SUBID"):
        import secrets
        import string
        alphabet = string.ascii_lowercase + string.digits
        cfg["MERGED_SUBID"] = "".join(secrets.choice(alphabet) for _ in range(16))
        print(f"未提供 MERGED_SUBID，已随机生成: {cfg['MERGED_SUBID']}")

    for key in ("VPS_HOST", "VPS_USER", "DOMAIN", "PANEL_PORT", "PANEL_PATH",
                "API_TOKEN"):
        if not cfg.get(key):
            sys.stderr.write(f"deploy.env 缺少 {key}\n")
            return 2

    cli = get_client(cfg)
    try:
        encoded = base64.b64encode(REMOTE_SCRIPT.encode("utf-8")).decode("ascii")
        run(cli, f"echo '{encoded}' | base64 -d > /root/.xui-skill/_merge.sh",
            timeout=60)

        keys = ("PANEL_PORT", "PANEL_PATH", "DOMAIN", "API_TOKEN", "SUB_PORT",
                "SUB_PATH", "MERGED_EMAIL", "MERGED_SUBID", "REALITY_PORT",
                "HY2_PORT", "TUIC_PORT")
        exports = "\n".join(
            "export %s='%s'" % (k, cfg.get(k, "")) for k in keys
        )
        rc, out, err = run(
            cli, f"{exports}\nbash /root/.xui-skill/_merge.sh 2>&1",
            timeout=600,
        )
        sys.stdout.write(out)
        if err.strip():
            sys.stderr.write("\n[stderr]\n" + err)
    finally:
        cli.close()

    print("\n" + "=" * 64)
    print("合并结果")
    print("=" * 64)
    print(f"客户端 email : {cfg['MERGED_EMAIL']}")
    print(f"subId        : {cfg['MERGED_SUBID']}")
    print(f"订阅 URL     : https://{cfg['DOMAIN']}:{cfg['SUB_PORT']}"
          f"/{cfg['SUB_PATH']}/{cfg['MERGED_SUBID']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
