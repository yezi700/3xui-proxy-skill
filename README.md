# 3xui-proxy-skill

`https://github.com/yezi700/3xui-proxy-skill`

一个 WorkBuddy / Claude **Agent Skill**：把一台全新的 Linux VPS 变成一套可用的代理服务
（3x-ui 面板 + VLESS-REALITY / Hysteria2 / TUIC v5 三协议节点），
并输出可直接导入客户端的链接与订阅。

> 这不是又一个"复制粘贴命令"的教程。它把**真实部署中踩到的几十个坑**（系统版本差异、API 陷阱、
> 机房端口封锁、gRPC 热更新陷阱、客户端兼容性破坏性变更）固化成了可复用的流程与脚本。

## 它能解决什么

| 常见坑 | 本 skill 的处理 |
|---|---|
| 教程用 UFW，但 Debian 13 上 UFW 与 iptables-persistent 互斥，照抄会卸载 UFW 并留下残缺规则 | 改用纯 iptables + netfilter-persistent |
| 教程写 `/etc/sysctl.conf`，Debian 13 已废弃该文件 | 改用 `/etc/sysctl.d/*.conf` |
| 面板 API 突然全部 403，响应体为空 | 根因是 `webDomain` 的 Host 头校验，脚本自动带 `Host:` |
| 分享链接里主机名变成 `localhost` | 设置入站 `shareAddrStrategy=custom` + `shareAddr=域名` |
| Hysteria2 链接 `sni=` 为空 | 删除 `tlsSettings.settings.serverName` 空字段 |
| 三个节点只有三条订阅 | 用「一个客户端绑定多入站」合并为一条 |
| 在服务器上自测"通了"，但外面连不上 | VPS 访问自身公网 IP 走 `lo`，绕过 INPUT 链 —— 必须从外部验证 |
| 某客户端连不上 REALITY | 已知的 Xray ≥26.9.8 破坏性变更，文档给出完整兼容性矩阵 |
| 代理**出口 IP 是 IPv6**，但需要固定 IPv4 出口 | 根因是 Xray `domainStrategy=AsIs` + 系统有 IPv6；`setup_base.sh` 可一键屏蔽 IPv6（**先换 DNS 再关**，带断网自动回滚） |
| TUIC 节点**时通时不通**，重连就失败 | 3x-ui TUIC 认证要求 `HandshakeComplete`，0-RTT 连接必然认证失败；`fix_tuic_0rtt.py` 一键关闭 0-RTT |
| **v2rayN / v2rayNG 导入 TUIC 后一直测速超时** | **Xray 内核根本没有 TUIC/Hysteria2**。v2rayN 切 sing-box 内核即可；v2rayNG 无内核切换，只能用 REALITY |
| 查二进制"确认协议是否支持"，结果**所有协议都是 0 命中** | Debian 默认没装 `strings`（属于 `binutils`），命令静默失败。改用 `grep -a -o -i -- <关键字> <bin> \| wc -l` |
| 增删入站后重启 Xray，**REALITY 与 Hysteria2 一起挂掉** | v3.9.0 增删入站走 Xray 的 gRPC API 热更新，**不重写 `bin/config.json`**；该文件留着旧入站，重启即端口冲突。改完入站必须 `systemctl restart x-ui` |
| 以为 TUIC 不在 Xray 里就是"没装" | TUIC v5 由 **`x-ui` 面板进程自己承载**（转发给内部 socks 入站 127.0.0.1:64003），`xray-linux-amd64` 里查不到属正常 |
| 想加 AnyTLS 节点 | **3x-ui v3.9.0 不支持**（`xray-linux-amd64` 与 `x-ui` 二进制里 `anytls` 均 0 命中），只有 sing-box / mihomo 实现 |
| 装完 API Token 读不出来 | v3.9.0 的 `api_tokens` 表**只存 SHA-256**，明文仅创建时返回一次。脚本改用「登录会话 + `POST /panel/api/setting/apiTokens/create`」获取 |
| Windows 上 `git clone` 后 `.sh` 脚本报 `$'\r': command not found` | Git 的 `core.autocrlf` 把脚本换成了 CRLF。仓库已加 `.gitattributes` 强制 `*.sh`/`*.py` 用 LF |
| 测新代理**时通时不通**，以为服务端不稳 | 本机开着的代理客户端会截胡 `curl -x`。先用 TCP 裸探测（`/dev/tcp`）连续验证再下结论 |

## 安装

### 方式一：克隆到 skill 目录（最简单）

```bash
git clone https://github.com/yezi700/3xui-proxy-skill.git \
  ~/.workbuddy-ai/skills/3xui-proxy-skill
```

Windows：

```powershell
git clone https://github.com/yezi700/3xui-proxy-skill.git `
  "$env:USERPROFILE\.workbuddy-ai\skills\3xui-proxy-skill"
```

重启会话后生效。WorkBuddy 会在识别到"部署代理节点"类请求时自动加载。

> ⚠️ **Windows 用户**：仓库根目录有 `.gitattributes`，已强制 `*.sh` / `*.py` 使用 LF 换行，
> 克隆后脚本可以直接传到 Linux 执行。如果你的 Git 全局设置了 `core.autocrlf=true`
> 且克隆的是**旧版本**，请先 `git pull` 拉取 `.gitattributes`，或参考
> `references/pitfalls.md` §1.5 就地转换。

### 方式二：打包分发

```bash
# 只打包 git 已跟踪的文件（不会带入 .git / __pycache__ / deploy.env）
git archive --format=zip --prefix=3xui-proxy-skill/ \
  -o ../3xui-proxy-skill.zip HEAD
```

生成 `3xui-proxy-skill.zip`，对方解压到 skills 目录即可。

> 也可以直接用 skill-creator 的 `package_skill.py`，但它**不过滤 `.git` 与 `__pycache__`**，
> 建议在干净的检出目录上执行，或改用上面的 `git archive`。

## 第一次部署：先准备域名

还没有域名或不会解析？先看 [域名申请、Cloudflare 接入与 DNS 引导](references/domain-and-dns.md)：
申请免费域名 → 注册 Cloudflare（可选）→ 修改 NS → 添加指向 VPS 的 A 记录（灰云）→ DNS 预检。
已有可用域名时直接检查解析，无需重新注册或迁移 DNS。

```bash
# 替换为实际完整域名和 VPS 公网 IPv4；示例 IP 不可用于部署
python scripts/check_dns.py --domain jp.example.com --ipv4 203.0.113.10
```

预检仅使用 Python 标准库，无需凭据，不改 DNS；默认要求没有 AAAA。
免费域名可能需要续期，实际规则以服务商说明为准。

## 使用

在对话里直接说需求即可，例如：

> 帮我在这台 VPS 上部署 3x-ui 和 Reality / Hysteria2 节点：`1.2.3.4` `22` `root` `密码`，域名 `jp.example.com` 已解析

skill 会先按需引导域名准备与 DNS 预检，再按 Step 0→8 执行：探测环境 → 系统基线 → 装面板+证书 → 建节点 → 合并订阅 →
放行端口 → 端到端验证 → 生成交付文档。

也可以只调用其中一步，例如"给这个面板再加一个 TUIC 节点"。

## 目录结构

```
3xui-proxy-skill/
├── SKILL.md                              # 主流程（agent 入口）
├── README.md
├── LICENSE
├── .gitignore
├── .gitattributes                        # 强制 .sh/.py 用 LF（Windows 克隆不踩 CRLF 坑）
├── references/
│   ├── domain-and-dns.md                 # 免费域名、Cloudflare、A/AAAA 与预检
│   ├── pitfalls.md                       # 踩坑大全（核心价值）
│   ├── xui-api.md                        # 3x-ui API 备忘
│   ├── protocols-and-clients.md          # 协议选型 + 客户端兼容性矩阵
│   └── install-env.md                    # 非交互安装参数
├── scripts/
│   ├── check_dns.py                      # 只读 DNS 预检（标准库）
│   ├── ssh_run.py                        # SSH 执行器
│   ├── xui_api.py                        # 面板 API 客户端
│   ├── setup_base.sh                     # 系统基线（含屏蔽 IPv6）
│   ├── install_3xui.sh                   # 安装面板 + 证书 + 获取 API Token
│   ├── deploy_nodes.py                   # 建 3 个节点
│   ├── fix_tuic_0rtt.py                  # 关闭 TUIC 0-RTT
│   ├── merge_subscription.py             # 合并订阅
│   ├── verify_nodes.sh                   # 端到端验证
│   └── render_report.py                  # 生成交付文档
└── examples/
    └── deploy.env.example                # 参数模板
```

## 客户端兼容性速查

两条"连不上"的根因完全不同，别搞混：

| 客户端内核 | REALITY | Hysteria2 | TUIC | 怎么办 |
|---|---|---|---|---|
| **Xray**（v2rayN 默认 / v2rayNG） | ✅ | ❌ | ❌ | v2rayN 切 sing-box 内核；v2rayNG 只能用 REALITY |
| **sing-box**（Hiddify / Karing / NekoBox / 旧 Shadowrocket） | ❌ | ✅ | ✅ | 用 Hy2 / TUIC |
| **mihomo**（Clash Verge / Clash Meta） | ✅ | ✅ | ✅ | 无需调整，最省心 |

详见 `references/protocols-and-clients.md`。

## 发布与更新

仓库地址：**https://github.com/yezi700/3xui-proxy-skill**

### 首次发布（已完成，留作参考）

```bash
git config user.name  "yezi700"
git config user.email "你的邮箱@example.com"
git add .
git commit -m "feat: 3x-ui 代理节点部署 skill（Reality / Hysteria2 / TUIC）"

gh auth login                       # 首次需要
gh repo create 3xui-proxy-skill --public --source=. --push
```

或手动：

```bash
# 先在 github.com 上建一个空仓库（不要勾选 README / .gitignore / LICENSE）
git remote add origin https://github.com/yezi700/3xui-proxy-skill.git
git push -u origin main
```

### 日常更新

```bash
git add .
git commit -m "docs: 补充 XXX"
git push
```

> ⚠️ **每次提交前确认 `deploy.env` 没被加进去**：
> ```bash
> git ls-files | grep deploy.env          # 只应看到 deploy.env.example
> ```
> `.gitignore` 已排除 `deploy.env` / `VPS-*.md` / `VPS-*.html` / `node-credentials.json`，
> 但**凭据一旦推到公开仓库，即使删除也会留在历史里**。

### 打包分发

```bash
git archive --format=zip --prefix=3xui-proxy-skill/ \
  -o ../3xui-proxy-skill.zip HEAD
```

对方解压到 `~/.workbuddy-ai/skills/` 即可。仓库根已有
`.codebuddy-plugin/plugin.json`，因此也可作为插件分发。

## 依赖

- **本地**：Python 3.8+（`paramiko`）、`bash`、可选 `git`
- **VPS**：Debian 11+ / Ubuntu 20.04+（x86_64 或 arm64），root 权限，能访问 GitHub 与 Let's Encrypt
- 不需要本地安装 Xray / 3x-ui

```bash
pip install paramiko
```

## 开发与验证

```bash
python -m pip install paramiko
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
```

测试在本地模拟 SSH 与面板响应，不连接真实 VPS。Bash 行为测试在 Linux/macOS
使用 `bash`，Windows 使用 Git for Windows 的 Bash；未安装时会跳过对应测试。
建议在 Linux CI 中对 Python 3.8 / 3.11 / 3.13 运行上述完整测试。

部署入口：`deploy_nodes.py`、`merge_subscription.py` 在本地直接用 Python 运行，
它们内部负责 SSH 编排；`ssh_run.py -f` 仅用于 `.sh` 脚本。
部署和合并遇到失败会停止并返回非零状态；停止不等于自动回滚，重试前应回读已有入站。
合并仅选择配置端口对应的三个入站，并保留原客户端；从外部验证新订阅后再按需清理旧身份。
新建 TUIC 已默认关闭 0-RTT，`fix_tuic_0rtt.py` 用于修复旧入站。

## 安全说明

- 脚本会以 root 身份在你的 VPS 上执行命令（安装软件、改防火墙、写 systemd 服务）——
  执行前请自行审阅 `scripts/` 下所有文件。
- `deploy.env` 含明文凭据，**已在 `.gitignore` 中排除**，请勿提交。
- 建议部署完成后在面板里修改默认用户名与密码。

## 版本历史

### v1.3.0

基于一次真实的 VPS 部署复盘做的收敛与加固：

- **移除 HTTP / SOCKS5 通用代理支持** —— 删除 `scripts/add_http_socks.py` 及
  SKILL / README / references / `deploy.env.example` 中的全部相关内容。
  本 skill 聚焦 REALITY / Hysteria2 / TUIC 三件套。
- **修 `install_3xui.sh` 的 API Token 读取**：v3.9.0 起 `api_tokens` 表只存 SHA-256，
  老的 `sqlite3 ... where key='apiToken'` 返回空。改用
  CSRF → 登录 → `POST /panel/api/setting/apiTokens/create` 流程。
- **修 `settings` / `streamSettings` 的类型假设**：写的时候必须是 JSON 字符串，
  但部分版本的**读**接口直接返回对象，`json.loads(dict)` 会抛 `TypeError`。
  `deploy_nodes.py` / `verify_nodes.sh` 已改为两种都兼容。
- **修 `verify_nodes.sh` 的 REALITY 自检**：原来先写客户端配置、后回读公钥，
  导致 `publicKey` 为空、握手必然失败。现在改成**先回读再写配置**。
- **修 `render_report.py` 的兼容性矩阵**：原表把 Xray 内核写成三个节点全可用，
  与实际相反（Xray 无 TUIC / Hysteria2）。交付文档的矩阵已按真实情况重写。
- **`merge_subscription.py` 的 flow 回读更健壮**：`/clients/get/<email>` 在不同版本
  返回结构不一致，现在同时查 `/clients/list` 兜底。
- **新增 6 个坑**：gRPC 热更新不重写 `bin/config.json`（端口冲突定时炸弹）、
  TUIC v5 由 `x-ui` 面板进程承载、AnyTLS 不受支持、
  Debian 默认没装 `strings`（假阴性陷阱）、Windows 克隆的 CRLF 问题、
  清理临时方案时的残留清单。
- **新增 `.gitattributes`** 强制脚本 LF；`setup_base.sh` 补装 `python3`。

### v1.2.0

新增 HTTP / SOCKS5（`mixed`）通用代理支持 + 三个新踩的坑。

### v1.1.0

屏蔽 IPv6 强制 IPv4 出口；关闭 TUIC 0-RTT；修正客户端兼容性结论。

### v1.0.0

首个版本：3x-ui + VLESS-REALITY / Hysteria2 / TUIC v5 全流程。

## 许可

MIT
