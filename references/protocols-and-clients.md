# 协议选型与客户端兼容性

> 本文回答两个问题：**该装哪几种协议**，以及**"某个客户端连不上"该怎么解释**。

---

## 1. 协议横向对比

| 协议 | 传输 | 端口 | 抗封锁 | 延迟 | 高丢包吞吐 | 需要自有证书 | 备注 |
|---|---|---|---|---|---|---|---|
| **VLESS + REALITY + Vision** | TCP | 443 | ★★★★★ | 中 | 中 | ❌ 借用目标站证书 | 主力。无 TLS 指纹特征，最像正常 HTTPS |
| **Hysteria2** | QUIC/UDP | 443 | ★★★★ | 低 | ★★★★★ | ✅ | 暴力拥塞控制，丢包链路吞吐碾压 |
| **TUIC v5** | QUIC/UDP | 8443 | ★★★★ | ★最低 | ★★★★ | ✅ | 0-RTT，连接建立最快 |
| VLESS + TLS（自签/LE） | TCP | 443 | ★★★ | 中 | 中 | ✅ | 有 TLS 指纹，不如 REALITY |
| Trojan | TCP | 443 | ★★★ | 中 | 中 | ✅ | 老牌，特征已被识别得差不多 |
| VMess + WS + TLS | TCP | 443 | ★★ | 中 | 中 | ✅ | 需要 CDN 配合才好用 |
| Shadowsocks | TCP | 任意 | ★★ | 低 | 中 | ❌ | 协议简单，抗主动探测差 |
| WireGuard | UDP | 任意 | ★ | 低 | ★★★★ | ❌ | 特征明显，易被 QoS/封 |
| AnyTLS | — | — | — | — | — | — | **3x-ui v3.9.0 不支持**（见下） |

### 为什么推荐"REALITY + Hysteria2 + TUIC"这三件套

三者**互补**，覆盖不同网络条件：

- **REALITY** 走 TCP 443。**在 UDP 被限速/封锁的网络里是唯一活路**，
  且因为借用真实站点证书，被动探测几乎无法区分。作为兜底主力。
- **Hysteria2** 走 UDP 443 + 端口跳跃。**丢包率高时吞吐最好**（比如跨境晚高峰、
  移动网络），但 UDP 可能被 QoS。
- **TUIC** 走 UDP 8443。**连接建立最快**（0-RTT），网页首包体验最好。
  与 Hysteria2 分端口，避免互相抢占。

三个同时可用时，客户端侧按网络情况切换即可。

### AnyTLS 的确认方法

不要凭印象说"支持/不支持"，直接查二进制：

```bash
strings /usr/local/x-ui/bin/xray-linux-amd64 | grep -ci anytls    # → 0
strings /usr/local/x-ui/bin/xray-linux-amd64 | grep -iE '^(vmess|vless|trojan|hysteria|tuic|wireguard)$' | sort -u
```

---

## 2. 端口规划（三件套参考）

| 端口 | 协议 | 说明 |
|---|---|---|
| 22/tcp | SSH | 务必保留，否则自己都进不去 |
| 80/tcp | HTTP | ACME 证书签发（可只用一次） |
| 443/tcp | REALITY | TCP |
| 443/udp | Hysteria2 | 与 TCP 443 共存，**改防火墙时两个都别漏** |
| 58888:60888/udp | Hysteria2 端口跳跃 | 客户端 `mport`，服务端 iptables NAT REDIRECT → 443 |
| 8443/udp | TUIC v5 | |
| 2096/tcp | 订阅服务 | |
| 46821/tcp | 面板 | 建议只对特定 IP 开放，或走域名 |

### 端口跳跃的实现

`mport=58888-60888` 是**客户端**参数。服务端不需要监听整段端口，
而是用 iptables 把整段 UDP 重定向到 443：

```bash
iptables -t nat -A PREROUTING -i eth0 -p udp --dport 58888:60888 \
         -j REDIRECT --to-ports 443
```

配合 INPUT 链放行：

```bash
iptables -A INPUT -p udp --dport 58888:60888 -j ACCEPT
```

⚠️ 漏了 INPUT 放行只加 NAT，包会在 nat 表被改写后仍被 filter 表丢掉。

---

## 3. ⚠️ 客户端兼容性矩阵（重点）

### 3.1 根因：Xray ≥ 26.9.8 的 REALITY 强制要求后量子混合密钥交换

Xray-core 从 **26.9.8** 起，REALITY 服务端要求客户端 ClientHello 中携带
**`X25519MLKEM768`**（X25519 + ML-KEM-768 混合密钥交换）扩展。
不带该扩展的客户端会在 REALITY 校验阶段失败。

实测报错：

```
reality verification failed
```

排查过程与结论：

- 换 5 种 uTLS 指纹（chrome / firefox / safari / ios / edge）**全部失败** → 不是指纹问题
- 用 Xray-core 客户端连 → **成功** → 确认是服务端要求变了
- 上游 issue：sing-box#4520、Xray#6477

### 3.2 兼容性矩阵

| 客户端 | 内核 | REALITY 节点 | Hysteria2 | TUIC |
|---|---|---|---|---|
| v2rayN (Windows) | Xray | ✅ | ✅ | ✅ |
| v2rayNG (Android) | Xray | ✅ | ✅ | ✅ |
| mihomo ≥ 1.19.30 | mihomo | ✅ | ✅ | ✅ |
| Clash Verge Rev (新版) | mihomo | ✅ | ✅ | ✅ |
| **sing-box ≤ 1.15.0-alpha** | sing-box | ❌ | ✅ | ✅ |
| **Hiddify** | sing-box | ❌ | ✅ | ✅ |
| **Karing** | sing-box | ❌ | ✅ | ✅ |
| **Shadowrocket 2.2.92（旧版）** | 自研 | ❌ | ✅ | ✅ |
| Shadowrocket 新版 | 自研 | ✅ | ✅ | ✅ |

**一句话结论**：sing-box 系客户端（Hiddify / Karing）和旧版 Shadowrocket
**连不上 REALITY，但 Hysteria2 和 TUIC 完全正常**。

### 3.3 给用户的建议话术

交付文档里必须写清楚，否则用户会以为是自己配置错了：

> 如果你的客户端是 **Hiddify / Karing / sing-box 系**或**旧版 Shadowrocket**，
> 请**使用 Hysteria2 或 TUIC 节点**，不要用 REALITY 节点。
> 这不是配置错误，是 Xray 26.9.8+ 新增的后量子密钥交换要求，
> 客户端内核尚未跟进。v2rayN / v2rayNG / mihomo 系客户端三个节点都正常。

### 3.4 可选的降级方案

如果确实需要 sing-box 系客户端也能用 REALITY，可以**降级 Xray-core**：

- 降级到 **≤ 26.3.27**（`v26.3.27` 是当时最新的非预发布版；26.9.8 起全是 prerelease）
- 代价：放弃上游安全修复与新特性，且 3x-ui 后续升级可能又覆盖回去

**默认建议**：保持 26.9.30 不降级，靠"Hysteria2/TUIC 兜底 + 文档说明"解决兼容性问题。
只有在用户明确要求"必须让 Hiddify 也能连 REALITY"时才降级。

---

## 4. 排查"某客户端连不上"的流程

1. **先确认是哪个节点**。如果只有 REALITY 不通、Hy2/TUIC 正常 → 十有八九是 §3.1
2. **确认分享链接里的地址不是 `127.0.0.1`**（见 `xui-api.md` §5.1）
3. **确认 `sni` 不为空**（见 `xui-api.md` §5.3）
4. **确认 flow 字段在**：Reality+Vision 必须有 `flow=xtls-rprx-vision`，
   合并订阅后容易丢（见 `xui-api.md` §4.4）
5. **确认端口真的通**：UDP 端口要单独测（TCP 通不代表 UDP 通）
6. **确认证书**：`openssl s_client -connect <域名>:443 -servername <域名>` 看有效期
7. **换一个内核完全不同的客户端**交叉验证（Xray 系 vs sing-box 系），
   这一步能最快区分"服务端问题"和"客户端内核问题"

---

## 5. 实测数据（参考基线）

同一 VPS、同一时段，从中国境外/境内各测一轮，取平均建连时间：

| 节点 | 平均建连 | 成功率 | YouTube 可达 |
|---|---|---|---|
| REALITY (443/tcp) | 0.761 s | 5/5 | ✅ |
| TUIC (8443/udp) | **0.375 s** | 5/5 | ✅ |
| Hysteria2 (443/udp) | **0.370 s** | 5/5 | ✅ |

> 结论符合预期：QUIC 系（TUIC / Hysteria2）建连明显快于 TCP+TLS 系。
> 但**抗封锁能力 REALITY 最强**，所以三者都留着，让用户按场景切换。

---

## 6. 选型速查

| 用户场景 | 推荐 |
|---|---|
| 就要一套最稳的 | REALITY（主力）+ Hysteria2（备用） |
| 网络丢包严重（跨境晚高峰、移动网） | Hysteria2 优先 |
| 追求最低延迟（游戏、实时） | TUIC |
| 客户端是 Hiddify / Karing / 旧 Shadowrocket | 只用 Hysteria2 + TUIC |
| UDP 被完全封锁的网络 | 只能 REALITY（TCP） |
| 要接 CDN | VLESS + WS + TLS（本文三件套不适用） |
