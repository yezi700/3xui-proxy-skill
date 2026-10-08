# 3xui-proxy-skill

`https://github.com/yezi700/3xui-proxy-skill`

一个 WorkBuddy / Claude **Agent Skill**：把一台全新的 Linux VPS 变成一套可用的代理服务
（3x-ui 面板 + VLESS-REALITY / Hysteria2 / TUIC v5 三协议节点），并输出可直接导入客户端的链接与订阅。

> 这不是又一个"复制粘贴命令"的教程。它把**真实部署中踩到的 20 多个坑**（系统版本差异、API 陷阱、
> 客户端兼容性破坏性变更）固化成了可复用的流程与脚本。

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

### 方式二：打包分发

```bash
# 只打包 git 已跟踪的文件（不会带入 .git / __pycache__ / deploy.env）
git archive --format=zip --prefix=3xui-proxy-skill/ \
  -o ../3xui-proxy-skill.zip HEAD
```

生成 `3xui-proxy-skill.zip`，对方解压到 skills 目录即可。

> 也可以直接用 skill-creator 的 `package_skill.py`，但它**不过滤 `.git` 与 `__pycache__`**，
> 建议在干净的检出目录上执行，或改用上面的 `git archive`。

## 使用

在对话里直接说需求即可，例如：

> 帮我在这台 VPS 上部署 3x-ui 和 Reality / Hysteria2 节点：`1.2.3.4` `22` `root` `密码`，域名 `jp.example.com` 已解析

skill 会自动按 Step 0→8 执行：探测环境 → 系统基线 → 装面板+证书 → 建节点 → 合并订阅 →
放行端口 → 端到端验证 → 生成交付文档。

也可以只调用其中一步，例如"给这个面板再加一个 TUIC 节点"。

## 目录结构

```
3xui-proxy-skill/
├── SKILL.md                              # 主流程（agent 入口）
├── README.md
├── LICENSE
├── .gitignore
├── references/
│   ├── pitfalls.md                       # 踩坑大全（核心价值）
│   ├── xui-api.md                        # 3x-ui API 备忘
│   ├── protocols-and-clients.md          # 协议选型 + 客户端兼容性矩阵
│   └── install-env.md                    # 非交互安装参数
├── scripts/
│   ├── ssh_run.py                        # SSH 执行器
│   ├── xui_api.py                        # 面板 API 客户端
│   ├── setup_base.sh                     # 系统基线（含屏蔽 IPv6）
│   ├── install_3xui.sh                   # 安装面板 + 证书
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

## 安全说明

- 脚本会以 root 身份在你的 VPS 上执行命令（安装软件、改防火墙、写 systemd 服务）——
  执行前请自行审阅 `scripts/` 下所有文件。
- `deploy.env` 含明文凭据，**已在 `.gitignore` 中排除**，请勿提交。
- 建议部署完成后在面板里修改默认用户名与密码。

## 许可

MIT
