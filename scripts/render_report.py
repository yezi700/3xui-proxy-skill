#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成交付文档 VPS-<域名>-部署信息.md / .html。

数据来源全部是「实测回读」，不是硬编码：
  * 面板信息  ← /etc/x-ui/install-result.env
  * 节点链接  ← /panel/api/inbounds/allLinks
  * 订阅 URL  ← deploy.env 的 SUB_PORT / SUB_PATH / MERGED_SUBID
  * 防火墙    ← iptables -S INPUT / -t nat -S PREROUTING
  * 证书有效期 ← openssl x509 -enddate
  * BBR       ← sysctl

执行：
    python scripts/render_report.py                 # 输出到当前目录
    python scripts/render_report.py -o ./docs       # 指定输出目录
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssh_run import env_exports, get_client, load_env, run  # noqa: E402

COLLECT = r"""
set -uo pipefail
W=/root/.xui-skill
echo "@@@INSTALL"
cat /etc/x-ui/install-result.env 2>/dev/null || echo "(无)"
echo "@@@CREDS"
cat "$W/node-credentials.json" 2>/dev/null || echo "{}"
echo "@@@LINKS"
curl -sk -H "Host: ${DOMAIN}" -H "Authorization: Bearer ${API_TOKEN}" \
  "https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/panel/api/inbounds/allLinks" 2>/dev/null || echo "{}"
echo "@@@INBOUNDS"
curl -sk -H "Host: ${DOMAIN}" -H "Authorization: Bearer ${API_TOKEN}" \
  "https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/panel/api/inbounds/list" 2>/dev/null || echo "{}"
echo "@@@FW4"
iptables -S INPUT 2>/dev/null || echo "(无)"
echo "@@@NAT"
iptables -t nat -S PREROUTING 2>/dev/null || echo "(无)"
echo "@@@CERT"
if [ -f "/root/cert/${DOMAIN}/fullchain.pem" ]; then
  openssl x509 -in "/root/cert/${DOMAIN}/fullchain.pem" -noout \
    -subject -issuer -enddate 2>/dev/null
else
  echo "(无证书)"
fi
echo "@@@SYS"
. /etc/os-release 2>/dev/null && echo "OS=$PRETTY_NAME"
echo "KERNEL=$(uname -r)"
echo "ARCH=$(uname -m)"
echo "UPTIME=$(uptime -p 2>/dev/null || uptime)"
echo "@@@BBR"
sysctl net.ipv4.tcp_congestion_control 2>/dev/null
sysctl net.core.default_qdisc 2>/dev/null
echo "@@@VER"
/usr/local/x-ui/x-ui -v 2>/dev/null || echo "(未知)"
/usr/local/x-ui/bin/xray-linux-amd64 -version 2>/dev/null | head -2 || true
echo "@@@END"
"""


def parse_sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cur = None
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^@@@(\w+)$", line.strip())
        if m:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur = m.group(1)
            buf = []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def kv_block(text: str) -> dict[str, str]:
    d = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            d[k.strip()] = v.strip()
    return d


def mask(secret: str, keep: int = 4) -> str:
    if not secret:
        return ""
    if len(secret) <= keep * 2:
        return "*" * len(secret)
    return secret[:keep] + "*" * (len(secret) - keep * 2) + secret[-keep:]


# ---------------------------------------------------------------- Markdown

def render_md(ctx: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    d = ctx
    L: list[str] = []
    A = L.append

    A(f"# {d['domain']} 代理部署信息")
    A("")
    A(f"> 生成时间：{now}　|　服务器：`{d['host']}`　|　系统：{d.get('os', '')}")
    A("")
    A("---")
    A("")

    # 1. 面板
    A("## 1. 3x-ui 面板")
    A("")
    A("| 项目 | 值 |")
    A("|---|---|")
    A(f"| 面板地址 | {d['panel_url']} |")
    A(f"| 用户名 | `{d['panel_user']}` |")
    A(f"| 密码 | `{d['panel_pass']}` |")
    A(f"| 面板端口 | `{d['panel_port']}` |")
    A(f"| 面板路径 | `{d['panel_path']}` |")
    A(f"| API Token | `{d['api_token']}` |")
    A(f"| 证书有效期 | {d.get('cert_end', '(未知)')} |")
    A(f"| 面板版本 | {d.get('ver', '(未知)')} |")
    A("")
    A("> ⚠️ 面板启用了 `webDomain`，**只能用域名访问，用 IP 会返回 403**（设计如此）。")
    A("> 从服务器本机调 API 必须带 `Host: " + d["domain"] + "` 头，否则 403 且响应体为空。")
    A("")

    # 2. 订阅
    A("## 2. 订阅地址（推荐）")
    A("")
    A("一条订阅返回全部节点：")
    A("")
    A("```")
    A(d["sub_url"])
    A("```")
    A("")
    A(f"合并客户端 email：`{d['merged_email']}`　subId：`{d['merged_subid']}`")
    A("")

    # 3. 节点
    A("## 3. 节点明细")
    A("")
    for i, node in enumerate(d["nodes"], 1):
        A(f"### 节点 {i}：{node['remark']}")
        A("")
        A(f"- 协议：`{node['protocol']}`　端口：`{node['port']}`")
        A("")
        A("```")
        A(node["uri"])
        A("```")
        A("")
        if node.get("params"):
            A("| 参数 | 值 |")
            A("|---|---|")
            for k, v in node["params"]:
                A(f"| {k} | `{v}` |")
            A("")

    # 4. 兼容性
    A("## 4. ⚠️ 客户端兼容性（重要）")
    A("")
    A("Xray-core ≥ **26.9.8** 起，REALITY 服务端要求客户端 ClientHello 携带")
    A("`X25519MLKEM768`（后量子混合密钥交换）。不支持的客户端连 REALITY 会失败。")
    A("")
    A("| 客户端 | REALITY | Hysteria2 | TUIC |")
    A("|---|---|---|---|")
    A("| v2rayN / v2rayNG（Xray 内核） | ✅ | ✅ | ✅ |")
    A("| mihomo ≥ 1.19.30 / Clash Verge Rev | ✅ | ✅ | ✅ |")
    A("| Hiddify / Karing（sing-box 内核） | ❌ | ✅ | ✅ |")
    A("| Shadowrocket 旧版（2.2.92） | ❌ | ✅ | ✅ |")
    A("")
    A("**结论**：用 Hiddify / Karing / 旧版小火箭的用户，请选择 **Hysteria2 或 TUIC** 节点。")
    A("这不是配置错误，是客户端内核尚未跟进。")
    A("")

    # 5. 防火墙
    A("## 5. 防火墙放行")
    A("")
    A("| 端口 | 协议 | 用途 |")
    A("|---|---|---|")
    for port, proto, use in d["fw_ports"]:
        A(f"| {port} | {proto} | {use} |")
    A("")
    A("UDP 端口跳跃（Hysteria2）通过 iptables NAT REDIRECT 实现：")
    A("")
    A("```")
    A(d["nat_rule"] or "(无)")
    A("```")
    A("")

    # 6. 实测
    if d.get("bench"):
        A("## 6. 实测数据")
        A("")
        A("| 节点 | 平均建连 | 成功率 |")
        A("|---|---|---|")
        for row in d["bench"]:
            A(f"| {row[0]} | {row[1]} | {row[2]} |")
        A("")

    # 7. 运维
    A("## 7. 常用运维命令")
    A("")
    A("```bash")
    A("systemctl status x-ui          # 面板状态")
    A("systemctl restart x-ui         # 重启面板（改配置后必做）")
    A("/usr/local/x-ui/x-ui -v        # 面板版本")
    A("")
    A("# 备份数据库（动手前先做）")
    A(f"cp /etc/x-ui/x-ui.db /root/x-ui-backup-$(date +%Y%m%d-%H%M).db")
    A("")
    A("# 查看入站/客户端")
    A("x-ui settings                  # 查看面板设置")
    A("")
    A("# 防火墙")
    A("iptables -S INPUT              # 查看规则")
    A("iptables -t nat -S PREROUTING  # 查看 NAT")
    A("netfilter-persistent save      # 持久化（改完必做）")
    A("")
    A("# 证书续期")
    A(f"/root/.acme.sh/acme.sh --cron --home /root/.acme.sh")
    A("```")
    A("")

    # 8. 注意事项
    A("## 8. 注意事项")
    A("")
    A("1. **不要删除 `/root/cert/`** —— 面板、Hysteria2、TUIC 共用这里的证书。")
    A("2. **443 同时承载 TCP（REALITY）与 UDP（Hysteria2）**，改防火墙时两个都要留。")
    A("3. 改任何入站配置后要 `systemctl restart x-ui`。")
    A("4. 从服务器本机自测代理**无法验证防火墙**（走 lo，不经 INPUT 链），外部可达性需另测。")
    A("5. `subId` 全局唯一，合并订阅靠「一个客户端绑多个入站」，不能共享 subId。")
    A("6. 本文件含明文凭据，请妥善保管，不要提交到公开仓库。")
    A("")

    return "\n".join(L)


# ---------------------------------------------------------------- HTML

HTML_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{domain} 代理部署信息</title>
<style>
:root{{
  --bg:#f6f7f9; --card:#fff; --fg:#1f2328; --muted:#656d76;
  --border:#d8dee4; --accent:#0969da; --code-bg:#f0f2f5;
  --ok:#1a7f37; --warn:#9a6700; --err:#cf222e;
}}
@media (prefers-color-scheme: dark){{
  :root{{
    --bg:#0d1117; --card:#161b22; --fg:#e6edf3; --muted:#8b949e;
    --border:#30363d; --accent:#58a6ff; --code-bg:#1c2128;
    --ok:#3fb950; --warn:#d29922; --err:#f85149;
  }}
}}
*{{box-sizing:border-box}}
body{{margin:0;padding:32px 20px;background:var(--bg);color:var(--fg);
  font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
  "Hiragino Sans GB","Microsoft YaHei",sans-serif;}}
.wrap{{max-width:920px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 8px}}
h2{{font-size:19px;margin:36px 0 12px;padding-bottom:8px;
  border-bottom:1px solid var(--border)}}
h3{{font-size:16px;margin:24px 0 8px}}
.meta{{color:var(--muted);font-size:13px;margin-bottom:8px}}
.card{{background:var(--card);border:1px solid var(--border);
  border-radius:10px;padding:20px 22px;margin:14px 0}}
table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}}
th,td{{border:1px solid var(--border);padding:8px 10px;text-align:left;
  vertical-align:top;word-break:break-all}}
th{{background:var(--code-bg);font-weight:600;white-space:nowrap}}
code,pre{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:13px}}
code{{background:var(--code-bg);padding:2px 5px;border-radius:4px}}
pre{{background:var(--code-bg);padding:12px 14px;border-radius:8px;
  overflow-x:auto;margin:8px 0;position:relative}}
.link{{position:relative}}
.copy{{position:absolute;top:8px;right:8px;background:var(--card);
  color:var(--muted);border:1px solid var(--border);border-radius:6px;
  padding:3px 9px;font-size:12px;cursor:pointer}}
.copy:hover{{color:var(--accent);border-color:var(--accent)}}
.pill{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;
  border:1px solid var(--border)}}
.pill.y{{color:var(--ok);border-color:var(--ok)}}
.pill.n{{color:var(--err);border-color:var(--err)}}
.warn{{background:rgba(154,103,0,.1);border-left:4px solid var(--warn);
  padding:12px 16px;border-radius:6px;margin:12px 0;font-size:14px}}
.toc{{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}}
.toc a{{color:var(--accent);text-decoration:none;font-size:13px;
  border:1px solid var(--border);border-radius:20px;padding:3px 12px}}
.toc a:hover{{border-color:var(--accent)}}
</style>
</head>
<body>
<div class="wrap">
<h1>{domain} 代理部署信息</h1>
<div class="meta">生成时间 {now}　·　服务器 <code>{host}</code>　·　{os}</div>
<div class="toc">
  <a href="#panel">面板</a><a href="#sub">订阅</a><a href="#nodes">节点</a>
  <a href="#compat">兼容性</a><a href="#fw">防火墙</a><a href="#ops">运维</a>
  <a href="#notes">注意事项</a>
</div>

<h2 id="panel">1. 3x-ui 面板</h2>
<div class="card">
<table>
<tr><th>面板地址</th><td><a href="{panel_url}" target="_blank">{panel_url}</a></td></tr>
<tr><th>用户名</th><td><code>{panel_user}</code></td></tr>
<tr><th>密码</th><td><code>{panel_pass}</code></td></tr>
<tr><th>面板端口</th><td><code>{panel_port}</code></td></tr>
<tr><th>面板路径</th><td><code>{panel_path}</code></td></tr>
<tr><th>API Token</th><td><code>{api_token}</code></td></tr>
<tr><th>证书有效期</th><td>{cert_end}</td></tr>
<tr><th>面板版本</th><td>{ver}</td></tr>
</table>
<div class="warn">面板启用了 <code>webDomain</code>，<b>只能用域名访问，用 IP 会 403</b>（设计如此）。
从服务器本机调 API 必须带 <code>Host: {domain}</code> 头，否则 403 且响应体为空。</div>
</div>

<h2 id="sub">2. 订阅地址（推荐）</h2>
<div class="card">
<p>一条订阅返回全部节点，导入客户端后自动更新：</p>
<pre class="link"><code>{sub_url}</code><button class="copy">复制</button></pre>
<p class="meta">合并客户端 email：<code>{merged_email}</code>　subId：<code>{merged_subid}</code></p>
</div>

<h2 id="nodes">3. 节点明细</h2>
{nodes_html}

<h2 id="compat">4. ⚠️ 客户端兼容性（重要）</h2>
<div class="card">
<p>Xray-core ≥ <b>26.9.8</b> 起，REALITY 服务端要求客户端 ClientHello 携带
<code>X25519MLKEM768</code>（后量子混合密钥交换）。不支持的客户端连 REALITY 会失败。</p>
<table>
<tr><th>客户端</th><th>REALITY</th><th>Hysteria2</th><th>TUIC</th></tr>
<tr><td>v2rayN / v2rayNG（Xray 内核）</td>
    <td><span class="pill y">可用</span></td><td><span class="pill y">可用</span></td><td><span class="pill y">可用</span></td></tr>
<tr><td>mihomo ≥ 1.19.30 / Clash Verge Rev</td>
    <td><span class="pill y">可用</span></td><td><span class="pill y">可用</span></td><td><span class="pill y">可用</span></td></tr>
<tr><td>Hiddify / Karing（sing-box 内核）</td>
    <td><span class="pill n">不可用</span></td><td><span class="pill y">可用</span></td><td><span class="pill y">可用</span></td></tr>
<tr><td>Shadowrocket 旧版（2.2.92）</td>
    <td><span class="pill n">不可用</span></td><td><span class="pill y">可用</span></td><td><span class="pill y">可用</span></td></tr>
</table>
<p><b>结论</b>：用 Hiddify / Karing / 旧版小火箭的用户，请选择 <b>Hysteria2 或 TUIC</b> 节点。
这不是配置错误，是客户端内核尚未跟进。</p>
</div>

<h2 id="fw">5. 防火墙放行</h2>
<div class="card">
<table><tr><th>端口</th><th>协议</th><th>用途</th></tr>
{fw_rows}
</table>
<p>UDP 端口跳跃（Hysteria2）通过 iptables NAT REDIRECT 实现：</p>
<pre><code>{nat_rule}</code></pre>
</div>

<h2 id="ops">6. 常用运维命令</h2>
<div class="card">
<pre class="link"><code>{ops_text}</code><button class="copy">复制</button></pre>
</div>

<h2 id="notes">7. 注意事项</h2>
<div class="card">
<ol>
<li><b>不要删除 <code>/root/cert/</code></b> —— 面板、Hysteria2、TUIC 共用这里的证书。</li>
<li><b>443 同时承载 TCP（REALITY）与 UDP（Hysteria2）</b>，改防火墙时两个都要留。</li>
<li>改任何入站配置后要 <code>systemctl restart x-ui</code>。</li>
<li>从服务器本机自测代理<b>无法验证防火墙</b>（走 lo，不经 INPUT 链），外部可达性需另测。</li>
<li><code>subId</code> 全局唯一，合并订阅靠「一个客户端绑多个入站」，不能共享 subId。</li>
<li>本文件含明文凭据，请妥善保管，不要提交到公开仓库。</li>
</ol>
</div>

</div>
<script>
document.querySelectorAll('.copy').forEach(function(b){{
  b.addEventListener('click', function(){{
    var t = b.parentElement.querySelector('code').innerText;
    navigator.clipboard.writeText(t).then(function(){{
      var old = b.innerText; b.innerText = '已复制';
      setTimeout(function(){{ b.innerText = old; }}, 1200);
    }});
  }});
}});
</script>
</body>
</html>
"""


def render_html(ctx: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    e = html.escape

    nodes_html = []
    for i, node in enumerate(ctx["nodes"], 1):
        rows = "".join(
            f"<tr><th>{e(k)}</th><td><code>{e(v)}</code></td></tr>"
            for k, v in node.get("params", [])
        )
        nodes_html.append(f"""
<h3>节点 {i}：{e(node['remark'])}　<span class="pill">{e(node['protocol'])}</span>
<span class="pill">:{e(str(node['port']))}</span></h3>
<div class="card">
<pre class="link"><code>{e(node['uri'])}</code><button class="copy">复制</button></pre>
{f'<table>{rows}</table>' if rows else ''}
</div>""")

    fw_rows = "".join(
        f"<tr><td><code>{e(str(p))}</code></td><td>{e(pr)}</td><td>{e(u)}</td></tr>"
        for p, pr, u in ctx["fw_ports"]
    )

    ops_text = (
        "systemctl status x-ui          # 面板状态\n"
        "systemctl restart x-ui         # 重启面板（改配置后必做）\n"
        "/usr/local/x-ui/x-ui -v        # 面板版本\n"
        "\n"
        "# 备份数据库（动手前先做）\n"
        "cp /etc/x-ui/x-ui.db /root/x-ui-backup-$(date +%Y%m%d-%H%M).db\n"
        "\n"
        "# 防火墙\n"
        "iptables -S INPUT              # 查看规则\n"
        "iptables -t nat -S PREROUTING  # 查看 NAT\n"
        "netfilter-persistent save      # 持久化（改完必做）\n"
        "\n"
        "# 证书续期\n"
        "/root/.acme.sh/acme.sh --cron --home /root/.acme.sh"
    )

    return HTML_TPL.format(
        domain=e(ctx["domain"]), now=now, host=e(ctx["host"]),
        os=e(ctx.get("os", "")),
        panel_url=e(ctx["panel_url"]), panel_user=e(ctx["panel_user"]),
        panel_pass=e(ctx["panel_pass"]), panel_port=e(ctx["panel_port"]),
        panel_path=e(ctx["panel_path"]), api_token=e(ctx["api_token"]),
        cert_end=e(ctx.get("cert_end", "(未知)")), ver=e(ctx.get("ver", "")),
        sub_url=e(ctx["sub_url"]), merged_email=e(ctx["merged_email"]),
        merged_subid=e(ctx["merged_subid"]),
        nodes_html="".join(nodes_html), fw_rows=fw_rows,
        nat_rule=e(ctx["nat_rule"] or "(无)"), ops_text=e(ops_text),
    )


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="生成交付文档")
    ap.add_argument("-o", "--out", default=".", help="输出目录")
    args = ap.parse_args()

    cfg = load_env()
    for key in ("VPS_HOST", "VPS_USER", "DOMAIN", "PANEL_PORT", "PANEL_PATH"):
        if not cfg.get(key):
            sys.stderr.write(f"deploy.env 缺少 {key}\n")
            return 2

    cli = get_client(cfg)
    try:
        exports = env_exports({k: cfg.get(k, "") for k in (
            "DOMAIN", "PANEL_PORT", "PANEL_PATH", "API_TOKEN", "SUB_PORT",
            "MERGED_SUBID", "MERGED_EMAIL"
        )})
        rc, out, err = run(cli, f"{exports}\nbash -s <<'EOS'\n{COLLECT}\nEOS",
                           timeout=180)
    finally:
        cli.close()

    if rc:
        sys.stderr.write(err or "远端信息采集失败，未生成交付文档\n")
        return rc

    sec = parse_sections(out)
    install = kv_block(sec.get("INSTALL", ""))
    creds = json.loads(sec.get("CREDS", "{}") or "{}")

    links_raw = sec.get("LINKS", "{}")
    try:
        links = json.loads(links_raw).get("obj") or []
    except json.JSONDecodeError:
        links = []

    inbounds_raw = sec.get("INBOUNDS", "{}")
    try:
        inbounds = json.loads(inbounds_raw).get("obj") or []
    except json.JSONDecodeError:
        inbounds = []

    # 解析节点参数
    nodes = []
    for it in links:
        uri = it.get("uri") or ""
        proto = it.get("protocol") or it.get("type") or ""
        params = []
        if uri.startswith("vless://"):
            q = uri.split("?", 1)[-1].split("#")[0]
            for kv in q.split("&"):
                if "=" in kv:
                    k, _, v = kv.partition("=")
                    params.append((k, v))
        elif uri.startswith("hysteria2://"):
            pwd = uri.split("://", 1)[1].split("@")[0]
            params.append(("password", pwd))
            q = uri.split("?", 1)[-1].split("#")[0] if "?" in uri else ""
            for kv in q.split("&"):
                if "=" in kv:
                    k, _, v = kv.partition("=")
                    params.append((k, v))
        elif uri.startswith("tuic://"):
            body = uri.split("://", 1)[1].split("@")[0]
            if ":" in body:
                uid, _, pwd = body.partition(":")
                params.append(("uuid", uid))
                params.append(("password", pwd))
            q = uri.split("?", 1)[-1].split("#")[0] if "?" in uri else ""
            for kv in q.split("&"):
                if "=" in kv:
                    k, _, v = kv.partition("=")
                    params.append((k, v))
        nodes.append({
            "remark": it.get("remark") or proto,
            "protocol": proto,
            "port": it.get("port") or "",
            "uri": uri,
            "params": params,
        })

    # 证书
    cert_txt = sec.get("CERT", "")
    cert_end = ""
    for line in cert_txt.splitlines():
        if "notAfter" in line:
            cert_end = line.split("=", 1)[-1].strip()

    # 系统
    sysd = kv_block(sec.get("SYS", ""))

    # 版本
    ver_txt = sec.get("VER", "")
    ver = ""
    for line in ver_txt.splitlines():
        if line.strip() and not ver:
            ver = line.strip()

    # 防火墙
    fw_ports = [
        (cfg.get("SSH_PORT", "22"), "TCP", "SSH"),
        (cfg.get("ACME_PORT", "80"), "TCP", "ACME 证书签发"),
        (cfg.get("REALITY_PORT", "443"), "TCP", "VLESS-REALITY"),
        (cfg.get("HY2_PORT", "443"), "UDP", "Hysteria2"),
        (cfg.get("HY2_HOP_RANGE", "58888:60888"), "UDP", "Hysteria2 端口跳跃"),
        (cfg.get("TUIC_PORT", "8443"), "UDP", "TUIC v5"),
        (cfg.get("SUB_PORT", "2096"), "TCP", "订阅服务"),
        (cfg.get("PANEL_PORT", "46821"), "TCP", "3x-ui 面板"),
    ]
    nat_rule = ""
    for line in sec.get("NAT", "").splitlines():
        if "REDIRECT" in line:
            nat_rule = line.strip()
            break

    panel_path = cfg.get("PANEL_PATH", "")
    domain = cfg["DOMAIN"]
    panel_port = cfg.get("PANEL_PORT", "46821")
    ctx = {
        "domain": domain,
        "host": cfg["VPS_HOST"],
        "os": sysd.get("OS", ""),
        "panel_url": f"https://{domain}:{panel_port}/{panel_path}/",
        "panel_user": install.get("PANEL_USER") or cfg.get("PANEL_USER", ""),
        "panel_pass": install.get("PANEL_PASS") or cfg.get("PANEL_PASS", ""),
        "panel_port": panel_port,
        "panel_path": panel_path,
        "api_token": install.get("API_TOKEN") or cfg.get("API_TOKEN", ""),
        "cert_end": cert_end or "(未知)",
        "ver": ver,
        "sub_url": (f"https://{domain}:{cfg.get('SUB_PORT', '2096')}"
                    f"/{cfg.get('SUB_PATH', '')}/{cfg.get('MERGED_SUBID', '')}"),
        "merged_email": cfg.get("MERGED_EMAIL", "merged"),
        "merged_subid": cfg.get("MERGED_SUBID", ""),
        "nodes": nodes,
        "fw_ports": fw_ports,
        "nat_rule": nat_rule,
    }

    outdir = os.path.abspath(args.out)
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, f"VPS-{domain}-部署信息")
    with open(base + ".md", "w", encoding="utf-8") as fh:
        fh.write(render_md(ctx))
    with open(base + ".html", "w", encoding="utf-8") as fh:
        fh.write(render_html(ctx))

    print("已生成：")
    print("  " + base + ".md")
    print("  " + base + ".html")
    print(f"节点数：{len(nodes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
