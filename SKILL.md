---
name: 3xui-proxy-skill
description: 在全新 VPS 上部署 3x-ui 面板与抗封锁代理节点（VLESS-REALITY+Vision / Hysteria2 / TUIC v5），可选追加 HTTP / SOCKS5 通用代理，覆盖非交互安装、Let's Encrypt 证书、iptables 加固、BBR 调优、面板 API 建站、合并订阅与端到端真机验证。当用户要求「搭梯子 / 部署机场节点 / 装 3x-ui / 配 Reality、Hysteria2、TUIC / 加个 http 或 socks5 代理 / 照教程部署代理 / 自建科学上网」时使用。Deploy a censorship-resistant proxy stack (3x-ui panel + VLESS-REALITY, Hysteria2, TUIC v5, optionally HTTP/SOCKS5) on a fresh VPS with non-interactive install, ACME certs, iptables hardening and end-to-end verification.
metadata:
  description_zh: 在 VPS 上部署 3x-ui 面板与 Reality / Hysteria2 / TUIC 代理节点（可选 HTTP / SOCKS5）
  description_en: Deploy a 3x-ui panel with VLESS-REALITY, Hysteria2, TUIC v5 and optional HTTP/SOCKS5 proxy nodes on a VPS
  version: 1.2.0
  agent_created: true
---

# 3x-ui 代理节点部署

## 用途

把一台**全新的 Linux VPS** 变成一套可用的代理服务：3x-ui 管理面板 + 三种互补的代理协议节点，
并输出可直接导入客户端的分享链接与订阅地址。

产出：

| 产物 | 说明 |
|---|---|
| 3x-ui 面板 | 随机路径 + 随机端口 + Let's Encrypt 证书（HTTPS） |
| 节点 1：VLESS + REALITY + XTLS-Vision | TCP 443，抗封锁主力，无需自有证书 |
| 节点 2：Hysteria2 | UDP 443 + 端口跳跃，高丢包链路吞吐最强 |
| 节点 3：TUIC v5 | UDP 8443，默认关闭 0-RTT 以兼容认证 |
| 节点 4/5（可选）：HTTP / SOCKS5 | 通用本地代理，给浏览器插件、系统代理、`curl`/`git`、Docker 用 |
| 一条订阅 URL | 一次返回全部**翻墙**节点（base64） |
| 交付文档 | 面板凭据、节点参数、防火墙、运维命令、实测数据 |

> ⚠️ HTTP / SOCKS5 **不会进订阅**（3x-ui 只为 vmess/vless/trojan/ss/tuic 生成链接），
> 必须在交付文档里单独列出。

## 何时使用

在以下任一情形触发：

- 用户给了 VPS 的 IP / SSH 凭据，要求搭代理、部署节点、"搭梯子"、自建科学上网
- 用户要求安装 / 配置 3x-ui、x-ui、Xray、Reality、Hysteria2、TUIC
- 用户要求「加个 HTTP 代理 / SOCKS5 代理」「给浏览器或脚本用」「给 Docker 用」
- 用户提供一份代理部署教程（视频或图文）并要求照着做
- 用户要求为已有面板新增节点、合并订阅、排查节点连不上

**不适用**：客户端软件配置（v2rayN / Shadowrocket 的界面操作）、纯 DNS 分流规则、商业机场选购。

## 前置条件

必须先从用户处取得（缺一不可，缺失则先问）：

1. VPS 公网 IP、SSH 端口、用户名、密码或密钥
2. 一个已解析到该 IP 的域名（用于申请证书 + 订阅 + REALITY 无关）
3. 期望的面板端口 / 订阅端口（未指定则用默认：面板 46821，订阅 2096）

可选：面板用户名密码、节点数量偏好、是否要 BBR、是否要 fail2ban。

## 工作流

按顺序执行，**每一步都要验证通过再进入下一步**。

### Step 0 · 准备参数

复制 `examples/deploy.env.example` 为 `deploy.env`，填入实际值。
所有脚本都从 `deploy.env`（或同名环境变量）读取配置：

```bash
cp examples/deploy.env.example deploy.env
$EDITOR deploy.env
```

### Step 1 · 探测环境

先确认能连上、系统版本、架构、是否已有面板：

```bash
python scripts/ssh_run.py -c "cat /etc/os-release | head -3; uname -m; free -m | head -2; df -h / | tail -1"
python scripts/ssh_run.py -c "systemctl is-active x-ui 2>/dev/null || echo 'x-ui not installed'"
```

记录：发行版（影响防火墙方案）、架构（影响二进制选择）、内存（影响 Xray 版本策略）。

### Step 2 · 系统基线

```bash
python scripts/ssh_run.py -f scripts/setup_base.sh
```

做五件事：设时区 → 装依赖 → 配 iptables 白名单 → **屏蔽 IPv6（可选）** → 启用 BBR。

⚠️ **不要用 UFW**：Debian 12+ 上 `ufw` 与 `iptables-persistent` 互斥，装了会把 UFW 卸载并留下残缺规则。用纯 iptables。

**关于 IPv6（`DISABLE_IPV6=1`，默认开启）**：

3x-ui 生成的 Xray 配置里 `routing.domainStrategy = "AsIs"`，域名交给系统解析；
VPS 若有可用 IPv6，glibc 会优先返回 AAAA，**代理出口就变成 IPv6**。
脚本会：

1. **先**把 `/etc/resolv.conf` 换成纯 IPv4 DNS（原文件备份到 `/root/.xui-skill/resolv.conf.bak`）
2. 写入 `/etc/sysctl.d/99-disable-ipv6.conf` 关掉 IPv6
3. 把 `rules.v6` 收紧到只放行 lo / established / icmpv6
4. 做一次 IPv4 + DNS 自检，**失败自动回滚**，避免把机器搞成断网

不需要屏蔽 IPv6 时把 `deploy.env` 里 `DISABLE_IPV6` 设为 `0`。详见 `references/pitfalls.md` §4.4。

### Step 3 · 安装面板 + 申请证书

```bash
python scripts/ssh_run.py -f scripts/install_3xui.sh
```

非交互安装，自动完成：下载安装脚本 → 静默安装 → acme.sh 申请证书 → 写入面板设置。
结果落在 VPS 的 `/etc/x-ui/install-result.env`（含 API Token），脚本会回读并打印。

### Step 4 · 创建节点

```bash
python scripts/deploy_nodes.py
```

创建 3 个入站（Reality / Hysteria2 / TUIC），并生成随机凭据。
凭据会打印出来，**必须原样记入交付文档**。

### Step 4.5 · TUIC 兼容性加固（强烈建议）

```bash
python scripts/fix_tuic_0rtt.py
```

新建 TUIC 入站已默认关闭 `zero_rtt_handshake`；此步骤用于检查、修复旧入站。

**为什么必须做**：3x-ui 的 TUIC 认证依赖 TLS Keying Material Exporter，
而 `internal/tuic/auth.go` 里有 `if !cs.HandshakeComplete { return ErrInvalidTLSState }`。
**0-RTT 连接在认证时握手尚未完成**，于是认证直接被拒（连接以 `0x100` 关闭）。
服务端开着 `Allow0RTT` 时，任何启用 0-RTT 的客户端都会踩中——
包括**面板自己导出的 Clash 配置**（默认 `reduce-rtt: true`）。

脚本会先备份原 inbound JSON 再改。详见 `references/pitfalls.md` §6.3。

### Step 4.6 · （可选）追加 HTTP / SOCKS5 通用代理

**仅在用户明确要求时执行**（"加个 http/socks5 代理"、"给浏览器/脚本/Docker 用"）。

```bash
PROXY_USER=bowei PROXY_PASS='<强密码>' \
  python scripts/add_http_socks.py
```

默认建两个入站：HTTP（8080/tcp）与 SOCKS5（2080/tcp）。

**三个必须记住的点**（脚本已内建防护）：

1. **协议名用 `mixed`，绝不用 `socks`** —— 用 `socks` 一律
   `request body failed validation`，与 `settings` 内容无关。
   `mixed` = HTTP + SOCKS 同端口，两种客户端都能连。
2. **端口避开 1080 / 1081 / 3128 / 8888** —— 脚本会**直接拒绝**这些端口。
   机房在上游封了这批"代理常用端口"，症状是「服务端监听正常 + VPS 自连正常 +
   公网连不上」。默认用 2080 / 8080（2080 实测在多家机房可用）。
3. **这两个协议不进订阅** —— 3x-ui 只为 `vmess/vless/trojan/shadowsocks/tuic`
   生成分享链接（`strings x-ui | grep gen.*Link` 可验证）。
   交付文档必须**单独列出**它们的地址与凭据。

**必做**：脚本不会自动改防火墙，执行完按它打印的命令放行端口，
然后**从外部**做 TCP 裸探测 + 出口 IP 验证。

⚠️ **这两个是明文协议**（无 TLS、无混淆），抗封锁能力≈0。
必须开认证、建议按来源 IP 限制，并在文档里注明"仅建议受信任网络使用"。
详见 `references/protocols-and-clients.md` §7 与 `references/pitfalls.md` §4.5 / §4.7 / §6.5 / §6.6。

### Step 5 · 合并订阅

```bash
python scripts/merge_subscription.py
```

3x-ui v3.9.0 起 `subId` **全局唯一**，无法靠共享 subId 合并订阅。
正确做法是**一个客户端身份绑定多个入站**（`/panel/api/clients/add` + `inboundIds:[...]`），
这样一条订阅 URL 就能返回全部节点。合并脚本保留原客户端；仅在从外部验证新订阅可用后，按用户要求清理旧身份。
合并失败会以非零状态退出；重复运行若遇到已有 email/subId，应先回读核对，不能盲目删除后重建。

### Step 6 · 放行端口

`deploy_nodes.py` 会按实际端口生成 iptables 命令，执行后务必 `netfilter-persistent save`。

### Step 7 · 端到端验证

```bash
python scripts/ssh_run.py -f scripts/verify_nodes.sh
```

⚠️ **关键陷阱**：VPS 访问自己的公网 IP 走 `lo` 接口，**不经过 INPUT 链**，
所以在服务器上自测**无法验证防火墙规则**。要验证外部可达性，必须：
- 从本机（外部网络）用真实客户端拨号，或
- 用 `scripts/verify_nodes.sh` 里的 Xray 客户端拨号（可验证协议本身），再单独用外部探测验证端口

### Step 8 · 输出交付文档

```bash
python scripts/render_report.py -o .
```

生成 `VPS-<域名>-部署信息.md` 与 `.html`（含复制按钮），数据全部来自实测回读，至少包含：

- 面板地址 / 用户名 / 密码 / 随机路径 / API Token / 证书有效期
- 每个节点的分享链接 + 参数明细表
- 订阅 URL
- **客户端兼容性矩阵**（见 `references/protocols-and-clients.md`，这一步不能省）
- 防火墙放行端口表
- 实测数据
- 常用运维命令
- 注意事项

⚠️ **兼容性矩阵必须写两条，不能只写一条**：

1. **sing-box 系**（Hiddify / Karing / NekoBox / 旧 Shadowrocket）→ 连不上 REALITY，用 Hy2/TUIC
2. **Xray 系**（v2rayN 默认 / v2rayNG）→ 连不上 Hy2/TUIC，只能用 REALITY

只写一条的话，用户会在两种"连不上"之间来回折腾。详见 `references/pitfalls.md` §6.4。

## 关键约束（务必遵守）

1. **不要删除 `/root/cert/`** —— 面板、Hysteria2、TUIC 共用这里的证书。
2. **443 端口同时承载 TCP（Reality）与 UDP（Hysteria2）**，改防火墙时两个都要留。
3. **面板启用 `webDomain` 后会校验 Host 头**：从 127.0.0.1 调面板 API 必须带
   `Host: <域名>`，否则返回 403 且响应体为空（极易误判成 API 挂了）。见 `references/xui-api.md`。
4. **改任何入站配置后要 `x-ui restart`**。
5. **动手前先备份**：`cp /etc/x-ui/x-ui.db /root/x-ui-backup-$(date +%Y%m%d-%H%M).db`。
6. **不要用 `pkill -f` / `pgrep -f` 匹配自己的脚本**（会匹配到脚本自身命令行导致自杀），用 PID 文件。
7. 涉及删除、覆盖、改端口等破坏性操作前，先向用户说明并取得确认。
8. **TUIC 入站要把 `zero_rtt_handshake` 设为 `false`**（Step 4.5），否则部分客户端重连时认证失败。
9. **Xray-core 不支持 TUIC / Hysteria2**。遇到"某客户端连不上 TUIC"先问清客户端内核，
   不要盲目改服务端配置——先用 `journalctl -u x-ui | grep tuic` 看服务端日志再判断。
10. **建 SOCKS 入站必须用协议名 `mixed`**，用 `socks` 会被 `request body failed validation` 拒绝。
11. **代理端口避开 1080 / 1081 / 3128 / 8888** —— 机房会在上游封锁这批端口，
    症状是「服务端正常但公网连不上」。选 2000-3000 或 7000-9000 段。
12. **HTTP / SOCKS5 不会出现在订阅里**（3x-ui 只为 vmess/vless/trojan/ss/tuic 生成链接），
    交付文档必须单独列出，不要等用户来问"为什么订阅里没有"。
13. **验证新端口时先做 TCP 裸探测**（`/dev/tcp/<IP>/<PORT>`，连续 5-10 次）。
    若本机开着本地代理客户端，`curl -x` 的结果可能被截胡造成"时通时不通"的假象。

## 参考资料

按需加载，不要一次性全读：

| 文件 | 何时读 |
|---|---|
| `references/pitfalls.md` | **每次部署都读**——汇集了 30+ 个实际踩过的坑与修复方式 |
| `references/xui-api.md` | 需要直接调面板 API 时（字段结构、鉴权、客户端模型、http/mixed 入站结构） |
| `references/protocols-and-clients.md` | 选协议、排查"某客户端连不上"、写交付文档的兼容性矩阵、部署 HTTP/SOCKS5 时 |
| `references/install-env.md` | 需要自定义安装参数（面板路径、SSL 模式、端口）时 |

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `scripts/ssh_run.py` | 通用 SSH 执行器（跑单条命令或整个脚本文件，自动注入 `deploy.env`） |
| `scripts/xui_api.py` | 面板 API 客户端（自动处理 Host 头、Bearer 鉴权；也可当 CLI 用） |
| `scripts/setup_base.sh` | 系统基线：时区、依赖、iptables 白名单、屏蔽 IPv6、BBR（带 180 秒回滚保险） |
| `scripts/install_3xui.sh` | 非交互安装面板 + ACME 证书 |
| `scripts/deploy_nodes.py` | 创建 Reality / Hysteria2 / TUIC 入站（自动生成凭据） |
| `scripts/fix_tuic_0rtt.py` | 关闭 TUIC 0-RTT，修复部分客户端认证失败（会先备份 inbound JSON） |
| `scripts/add_http_socks.py` | （可选）新增 HTTP / SOCKS5（`mixed`）入站，内建黑名单端口与幂等防护 |
| `scripts/merge_subscription.py` | 合并为一条订阅（一个客户端绑多入站） |
| `scripts/verify_nodes.sh` | 端到端拨号验证（含 TUIC UDP relay 独立验证） |
| `scripts/render_report.py` | 生成交付文档 `.md` / `.html`（数据全部实测回读） |

### 典型执行顺序

```bash
cp examples/deploy.env.example deploy.env && $EDITOR deploy.env

python scripts/ssh_run.py -c "cat /etc/os-release | head -3; uname -m"
python scripts/ssh_run.py -f scripts/setup_base.sh        # 含屏蔽 IPv6
python scripts/ssh_run.py -f scripts/install_3xui.sh      # 记下 API_TOKEN 回填 deploy.env
python scripts/deploy_nodes.py
python scripts/fix_tuic_0rtt.py                           # 关掉 TUIC 0-RTT
# 可选：PROXY_USER=.. PROXY_PASS=.. python scripts/add_http_socks.py
python scripts/merge_subscription.py
python scripts/ssh_run.py -f scripts/verify_nodes.sh
python scripts/render_report.py -o .
```

## 风格要求

- 全程**边做边验证**，每步都回读确认，不要"发完命令就假定成功"。
- 所有凭据最终必须落到交付文档里，不要让用户去面板里自己找。
- 遇到与教程不一致的地方，**按实际系统版本修正并在文档里说明差异**，不要机械照抄教程。
