#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新增 HTTP 代理 / SOCKS5 代理（3x-ui 协议名 `mixed`）入站。

为什么需要这个脚本：
    HTTP / SOCKS5 是**通用本地代理协议**，给「能设代理但不认 vless/tuic」的程序用
    （浏览器插件、系统代理、HTTP_PROXY 环境变量、curl / git、Docker 容器）。
    它们和三件套（REALITY / Hysteria2 / TUIC）是互补关系，不是替代。

三个必须知道的坑（脚本已自动规避）：
    1. **协议名必须用 `mixed`，不能用 `socks`**。
       用 `socks` 一律返回 `request body failed validation`，与 settings 内容无关。
       `mixed` = HTTP + SOCKS 同端口，一个端口两种客户端都能连。
    2. **端口不要用 1080 / 1081**。很多机房在上游封了这批"代理常用端口"，
       表现为「服务端监听正常 + 本机自连正常 + 公网连不上」。默认用 2080 / 8080。
    3. **这两个协议不会出现在订阅里**。3x-ui 只为
       vmess/vless/trojan/shadowsocks/tuic 生成分享链接，HTTP/SOCKS 必须手动配置。
       这是设计如此，改不出来。

用法：
    # 用默认端口（HTTP 8080 / SOCKS5 2080）和默认凭据
    python scripts/add_http_socks.py

    # 自定义
    HTTP_PORT=8080 SOCKS_PORT=2080 PROXY_USER=bowei PROXY_PASS=xxxx \\
      python scripts/add_http_socks.py

    # 只加其中一个
    WITH_HTTP=1 WITH_SOCKS=0 python scripts/add_http_socks.py

部署完记得放行端口：
    ssh_run.py -c 'iptables -A INPUT -p tcp --dport 8080 -j ACCEPT \\
                   && iptables -A INPUT -p tcp --dport 2080 -j ACCEPT \\
                   && netfilter-persistent save'
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xui_api import XuiApi, XuiError  # noqa: E402

HTTP_PORT = int(os.environ.get("HTTP_PORT") or 8080)
SOCKS_PORT = int(os.environ.get("SOCKS_PORT") or 2080)
PROXY_USER = os.environ.get("PROXY_USER") or "proxyuser"
PROXY_PASS = os.environ.get("PROXY_PASS") or ""
WITH_HTTP = (os.environ.get("WITH_HTTP") or "1") not in ("0", "false", "False")
WITH_SOCKS = (os.environ.get("WITH_SOCKS") or "1") not in ("0", "false", "False")

# 机房黑名单端口，硬性拦下，避免白折腾
BANNED_PORTS = {1080, 1081, 3128, 8888}

SNIFFING = {
    "enabled": True,
    "destOverride": ["http", "tls", "quic", "fakedns"],
    "metadataOnly": False,
    "routeOnly": False,
}


def _build_http(remark: str, port: int) -> dict:
    return {
        "up": 0, "down": 0, "total": 0,
        "remark": remark, "enable": True, "expiryTime": 0,
        "listen": "", "port": port, "protocol": "http",
        # ⚠️ http 用的是 accounts，不是 clients
        "settings": json.dumps({
            "accounts": [{"user": PROXY_USER, "pass": PROXY_PASS}],
            "allowTransparent": False,
        }, ensure_ascii=False),
        "streamSettings": json.dumps({"network": "tcp", "security": "none"},
                                     ensure_ascii=False),
        "sniffing": json.dumps(SNIFFING, ensure_ascii=False),
        "allocate": json.dumps({"strategy": "always", "refresh": 5,
                                "concurrency": 3}, ensure_ascii=False),
    }


def _build_mixed(remark: str, port: int) -> dict:
    return {
        "up": 0, "down": 0, "total": 0,
        "remark": remark, "enable": True, "expiryTime": 0,
        "listen": "", "port": port,
        # ⚠️ 关键：协议名是 mixed，不是 socks
        "protocol": "mixed",
        "settings": json.dumps({
            "auth": "password",
            "accounts": [{"user": PROXY_USER, "pass": PROXY_PASS}],
            "udp": True,                      # 允许 UDP ASSOCIATE
        }, ensure_ascii=False),
        "streamSettings": json.dumps({"network": "tcp", "security": "none"},
                                     ensure_ascii=False),
        "sniffing": json.dumps(SNIFFING, ensure_ascii=False),
        "allocate": json.dumps({"strategy": "always", "refresh": 5,
                                "concurrency": 3}, ensure_ascii=False),
    }


def _add(api: XuiApi, purpose: str, proto: str, port: int, remark: str,
         builder) -> int:
    """新增一个入站；已存在同协议则跳过。返回入站 id（跳过时返回 0）。"""
    if port in BANNED_PORTS:
        print(f"[拒绝] {purpose} 端口 {port} 在机房黑名单里"
              f"（{sorted(BANNED_PORTS)}），请换一个，建议 2000-3000 或 7000-9000 段。")
        return 0

    for ib in api.inbounds_list():
        if ib.get("protocol") == proto:
            print(f"[跳过] 已存在 {proto} 入站 #{ib['id']} "
                  f"({ib.get('remark')} port={ib.get('port')})")
            return 0

    payload = builder(remark, port)
    try:
        r = api.inbound_add(payload)
        print(f"[新增] {remark}  ->  {r.get('msg')}")
    except XuiError as e:
        print(f"[失败] {remark}: {e}")
        return 0

    # 回读确认端口 / 密码真的落库（空 pass 有被丢掉的先例）
    for ib in api.inbounds_list():
        if ib.get("protocol") == proto and int(ib.get("port") or 0) == port:
            iid = int(ib["id"])
            got = XuiApi.decode_inbound(api.inbound_get(iid))
            accs = (got.get("settings") or {}).get("accounts") or []
            print(f"        确认 -> #{iid} port={ib['port']} accounts={accs}")
            return iid
    return 0


def main() -> int:
    if not PROXY_PASS:
        print("!! PROXY_PASS 不能为空 —— 绝不要部署无密码的开放代理。")
        print("   例如：PROXY_PASS='你的强密码' python scripts/add_http_socks.py")
        return 1

    api = XuiApi.from_env()
    print(f"面板: {api.base}")
    print(f"凭据: {PROXY_USER} / {'*' * len(PROXY_PASS)}")
    print(f"待部署: HTTP={WITH_HTTP}({HTTP_PORT})  SOCKS5={WITH_SOCKS}({SOCKS_PORT})")
    print()

    if WITH_HTTP:
        _add(api, "HTTP", "http", HTTP_PORT, f"HTTP-{HTTP_PORT}", _build_http)
    if WITH_SOCKS:
        _add(api, "SOCKS5", "mixed", SOCKS_PORT, f"SOCKS5-{SOCKS_PORT}", _build_mixed)

    print()
    print("=" * 64)
    print("入站列表")
    for ib in api.inbounds_list():
        print(f"  #{ib['id']}  {ib.get('remark')}  "
              f"{ib.get('protocol')}/{ib.get('port')}  enable={ib.get('enable')}")

    print()
    print("=" * 64)
    print("⚠️ 后续必做两件事")
    print()
    print("1) 放行端口（脚本不会自动改防火墙）：")
    ports = []
    if WITH_HTTP:
        ports.append(str(HTTP_PORT))
    if WITH_SOCKS:
        ports.append(str(SOCKS_PORT))
    cmds = " && ".join(
        f"iptables -C INPUT -p tcp --dport {p} -j ACCEPT 2>/dev/null "
        f"|| iptables -A INPUT -p tcp --dport {p} -j ACCEPT"
        for p in ports
    )
    print(f"   {cmds} && netfilter-persistent save")
    print()
    print("2) 从外部验证（先裸探测 TCP，再看出口 IP）：")
    for p in ports:
        print(f"   for i in 1 2 3 4 5; do timeout 5 bash -c "
              f"\"exec 3<>/dev/tcp/<VPS_IP>/{p}\" && echo OK || echo TIMEOUT; done")
    if WITH_HTTP:
        print(f"   curl -s -x 'http://{PROXY_USER}:{PROXY_PASS}@<VPS_IP>:{HTTP_PORT}' "
              f"https://api.ipify.org")
    if WITH_SOCKS:
        print(f"   curl -s --proxy 'socks5h://{PROXY_USER}:{PROXY_PASS}@<VPS_IP>:{SOCKS_PORT}' "
              f"https://api.ipify.org")
    print()
    print("3) 交付文档里单独列出这两个节点 ——")
    print("   它们【不会】出现在订阅里（3x-ui 只为 vmess/vless/trojan/ss/tuic 生成链接）。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except XuiError as exc:
        sys.stderr.write(f"[XuiError] {exc}\n")
        raise SystemExit(1)
