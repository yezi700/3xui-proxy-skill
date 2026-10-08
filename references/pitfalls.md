# 踩坑大全

真实部署中踩到的坑，按「现象 → 根因 → 修复」组织。**每次部署前先扫一遍**。

---

## 一、系统与教程差异

### 1.1 照抄教程的 UFW 命令会卸载 UFW

**现象**：执行 `apt install ufw` 后，`ufw` 装了又被卸，`iptables -S INPUT` 只剩 `-P INPUT ACCEPT`，防火墙形同虚设。

**根因**：Debian 12/13 中 `ufw` 的包声明了 `Breaks: iptables-persistent, netfilter-persistent`，
两者互斥。装 `iptables-persistent` 会把 `ufw` 卸掉，反之亦然。教程写于更早的系统版本。

**修复**：放弃 UFW，用纯 iptables + `netfilter-persistent`：

```bash
apt-get install -y iptables-persistent
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -A INPUT -p icmp --icmp-type 8 -j ACCEPT
iptables -A INPUT -p tcp --dport 22 -j ACCEPT
# ... 业务端口 ...
iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
iptables -P INPUT DROP
netfilter-persistent save
```

⚠️ **改防火墙时一定要挂一个定时回滚兜底**，否则规则写错会把自己锁在外面：

```bash
( sleep 180; iptables-restore < /root/rules.v4.bak ) &
# 确认 SSH 还能连上后，再 kill 掉这个后台任务
```

### 1.2 `/etc/sysctl.conf` 在 Debian 13 不存在

**现象**：`echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf` 报 No such file，
或写了但不生效。

**根因**：Debian 13 起废弃 `/etc/sysctl.conf`，只读 `/etc/sysctl.d/*.conf`。

**修复**：

```bash
cat > /etc/sysctl.d/99-network-tuning.conf <<'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
EOF
sysctl --system
sysctl net.ipv4.tcp_congestion_control   # 应输出 bbr
```

### 1.3 教程里的面板版本已过时

教程往往写"当时最新版"。**永远装当前最新稳定版**，并在交付文档里写明版本差异。
3x-ui 的版本直接决定了入站字段结构（例如 v3.9.0 才原生支持 TUIC）。

---

## 二、3x-ui 面板 API

### 2.1 所有 API 突然返回 403，响应体为空

**现象**：之前能用的 `curl -H "Authorization: Bearer $TOKEN" https://127.0.0.1:46821/.../panel/api/inbounds/list`
突然返回 `403 Forbidden`，`Content-Length: 0`，看不出任何原因。

**根因**：面板设置了 `webDomain`（面板域名）后，会启用 `DomainValidatorMiddleware`，
校验请求的 **Host 头**是否等于配置的域名。用 `127.0.0.1:46821` 访问时 Host 不匹配 → 403。
该中间件在面板重启后才完全生效，所以"刚才还好好的"。

**修复**：调 API 时显式带 Host 头：

```bash
curl -sk -H "Host: $PANEL_DOMAIN" -H "Authorization: Bearer $TOKEN" "https://127.0.0.1:46821$BASE/panel/api/inbounds/list"
```

**副作用（要写进交付文档）**：面板从此**只能用域名访问，用 IP 会 403**。这是安全特性，不是故障。

### 2.2 改了 `settings.clients[].subId` 但完全不生效

**现象**：`GET /panel/api/inbounds/get/1` 拿到完整入站对象，改掉 `settings.clients[0].subId`，
再 `POST /panel/api/inbounds/update/1` 返回 `success:true`，但回读发现值没变，订阅也没变。

**根因**：3x-ui v3.9.0 起客户端数据存在**规范化表**（`clients` + `client_inbounds`），
入站 JSON 里的 `settings.clients` 是**派生视图**，改它不会回写数据库。

**修复**：走专门的客户端 API：

```bash
# 读
curl -sk -H "Host: $D" -H "Authorization: Bearer $T" "$API/clients/get/$EMAIL"
# 改（body 是 model.Client，注意 id 是「凭据字符串」不是数据库行号）
curl -sk -X POST -H "Host: $D" -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  --data-binary @client.json "$API/clients/update/$EMAIL"
```

⚠️ `model.Client.id` 是 `string` 类型（VLESS/TUIC 的 UUID 凭据），
而 `GET /clients/get/:email` 返回的 `id` 是**数据库行号（数字）**——
直接把它原样回传会报 `cannot unmarshal number into Go struct field .id of type string`。
必须自己构造 body。

### 2.3 `Duplicate subId` —— 无法靠共享 subId 合并订阅

**现象**：想把 3 个节点的客户端设成同一个 subId，让一条订阅返回全部节点，报
`Something went wrong (Duplicate subId: xxx)`。

**根因**：3x-ui v3.9.0 起 subId **全局唯一**。

**修复**：改用「**一个客户端身份绑定多个入站**」：

```bash
curl -sk -X POST -H "Host: $D" -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"client":{"email":"u1","id":"<uuid>","auth":"<hy2-pw>","password":"<tuic-pw>","subId":"<sub>","enable":true},
       "inboundIds":[1,2,3]}' "$API/clients/add"
```

同一个 `id` 同时作为 VLESS 与 TUIC 的凭据、`auth` 作为 Hysteria2 的凭据，互不冲突。
⚠️ 别忘了 `flow: "xtls-rprx-vision"`，否则生成的 REALITY 链接会丢掉 flow。

### 2.4 TUIC 入站报 `empty client ID`

**根因**：TUIC 客户端需要**同时**提供 `id` 和 `uuid` 两个字段——
`id` 走 `model.Client` 的通用校验，`uuid` 走 `tuic.InstanceFromInbound` 的解析。

**修复**：两个字段填同一个 UUID 值。

### 2.5 `/panel/api/setting/all` 是 POST 不是 GET，且是整份回写

用 GET 会 404。更新设置时**必须提交完整对象**（`UpdateAllSetting` 会遍历全部字段），
只传部分字段会把其余字段清空。正确姿势：先 `POST /setting/all` 读全量 → 改目标字段 → 整份写回。

---

## 三、分享链接生成

### 3.1 链接里的主机名是 `localhost`

**根因**：入站级 `shareAddrStrategy` 默认是 `node`，面板会尝试推断本机地址；
从 `127.0.0.1` 调 API 时推断出的就是 localhost。

**修复**：给每个入站设置：

```json
"shareAddrStrategy": "custom",
"shareAddr": "你的域名"
```

### 3.2 Hysteria2 链接里 `sni=` 是空的

**根因**：订阅服务用递归 `searchKey(tlsSetting, "serverName")` 查找，
而 Go 的 map 遍历是无序的，可能先命中 `tlsSettings.settings.serverName`（空串）而不是顶层的值。

**修复**：删掉那个空的 `settings.serverName` 字段。

### 3.3 REALITY 目标站的告警

Xray 对**任意外部目标站**都会打印
`Choosing "X" as the target will increase the likelihood of your server's IP being blocked by the GFW`。
这是信息性提示，不是错误。3x-ui 自带的候选列表（cloudflare / microsoft / amazon / nvidia…）同样是这类大站。

选目标站的要点：**支持 TLS 1.3 + HTTP/2、不在同一台机器上、最好是常见大站**。

---

## 四、网络与验证

### 4.1 在服务器上自测"通了"，但外部连不上

**根因**：VPS 访问**自己的公网 IP** 时，内核路由表显示 `local <ip> dev lo`，
数据包走 loopback，**根本不经过 INPUT 链**，所以端口放行规则有没有生效完全测不出来。

```bash
ip route get <公网IP>   # 输出含 "dev lo" 就说明这个陷阱成立
```

**修复**：必须从**外部网络**验证。两种可行方式：

1. 本机（或另一台机器）用真实客户端拨号；
2. 在 VPS 上用 `socat` 临时监听目标端口，从外部 `nc -zv` 探测（TCP 适用）。

### 4.2 UDP 端口怎么验证

UDP 没有握手，`nc -z` 测不出来。可靠做法：

- 用真实客户端（sing-box / mihomo）拨号后 `curl` 出网；
- 对 TUIC / Hysteria2 这类支持 UDP 中继的协议，另跑一个 SOCKS5 UDP ASSOCIATE 测试
  （向 `8.8.8.8:53` 发 DNS 查询，能收到应答即证明 UDP 转发正常）。

### 4.3 后台进程在命令结束后被回收

用 Bash 工具启动后台进程再在**下一条命令**里测试，进程往往已经没了。
**启动 + 测试 + 回收必须写在同一个脚本里**。

---

## 五、SSH 自动化

### 5.1 `pkill -f` / `pgrep -f` 会杀掉自己

**现象**：脚本执行到 `pkill -f "client.json"` 时 SSH 会话直接断开。

**根因**：`-f` 匹配完整命令行，脚本自身的命令行里也含 `client.json`，于是把自己杀了。

**修复**：改用 PID 文件；若必须用 `pkill`，用 `pkill -x <精确进程名>`。

### 5.2 SFTP `put` 到 `/root/` 报 ENOENT

**修复**：不要用 SFTP 上传到 `/root/`，改用「base64 编码 + heredoc 写入」或直接内联执行。

### 5.3 需要 PTY 与不需要 PTY 的场景不同

带 PTY（`get_pty=True`）时输出里会有 `\r\n`，需要归一化；但 `nohup ... &` 这类命令
带 PTY 会导致会话挂住不返回。提供一个 `--no-pty` 开关。

### 5.4 本地没有 `jq`

Windows 的 Git Bash 通常没有 `jq`。本地 JSON 处理一律用 Python；`jq` 只在 VPS 上用。

---

## 六、协议与客户端（最容易误判为"部署失败"）

### 6.1 部署全部成功，但某些客户端连不上 REALITY

**现象**：Xray 客户端（v2rayN）正常，但 sing-box 系客户端（Hiddify / Karing）和旧版 Shadowrocket
一律报 `reality verification failed` / `authentication failed`。

**根因**：**Xray-core ≥ v26.9.8 的破坏性变更** —— REALITY 服务端现在要求客户端的 TLS ClientHello
中必须携带 `X25519MLKEM768`（后量子混合密钥交换），且排在普通 X25519 之前；
不满足就静默 fallback 到伪装目标站，客户端表现为握手校验失败。

**这不是你的配置问题，也不是 `minClientVer` 的问题**（已双向实验证伪）。

**处理**：不要试图"修好"它。正确做法是**在交付文档里给出客户端兼容性矩阵**，
引导用户按客户端选协议。详见 `protocols-and-clients.md`。

### 6.2 把 `minClientVer` 当成万能钥匙

教程常说"最小客户端版本必须填 1.0.0，否则小火箭用不了"。
实测：填与不填对 Xray 客户端都正常，对 sing-box 客户端**都没用**（那是另一个原因）。
填 `1.0.0` 是安全的最小值（只会拒绝声明版本 < 1.0.0 的客户端），可以保留，但不要指望它解决兼容性问题。

---

## 七、其它

- **REALITY 私钥泄露**：私钥只存服务器，**永远不要**写进交付文档；文档里只放公钥 `pbk`。
- **`spx`（spiderX）每次生成链接都会变**：它是随机值，不影响认证，文档里照抄当时的值即可。
- **证书目录 `/root/cert/` 不能删**：面板、Hysteria2、TUIC 三者共用。
- **改完入站配置记得 `x-ui restart`**，否则 Xray 配置不会重载。
- **备份优先**：任何改动前先 `cp /etc/x-ui/x-ui.db /root/x-ui-backup-$(date +%Y%m%d-%H%M).db`。
