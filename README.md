# ECH Workers 客户端

跨平台的 ECH Workers 代理客户端，支持 Windows、macOS 和 Linux（ARM/x86）软路由。

tg交流群 https://t.me/+ft-zI76oovgwNmRh

## 致谢

本项目的客户端和 Go 核心程序均基于 [CF_NAT](https://t.me/CF_NAT) 的原始代码开发。

- **原始项目来源**: [CF_NAT - 中转](https://t.me/CF_NAT)

## 功能特性

- ✅ **多服务器管理** - 支持多个服务器配置，快速切换
- ✅ **一键系统代理** - 自动设置系统代理，支持分流模式
- ✅ **智能分流** - 全局代理、跳过中国大陆、不改变代理三种模式
- ✅ **中国IP列表** - 自动下载并应用完整的中国IP列表（基于 [mayaxcn/china-ip-list](https://github.com/mayaxcn/china-ip-list)）
- ✅ **系统托盘** - 最小化到系统托盘，不占用任务栏
- ✅ **开机自启** - 支持 Windows 和 macOS 开机自动启动
- ✅ **高 DPI 支持** - 完美支持高分辨率显示器
- ✅ **实时日志** - 查看代理运行状态和日志
- ✅ **配置持久化** - 自动保存配置，下次启动自动加载

## 快速开始

### 方法 1: 使用预编译版本（推荐）

从 [GitHub Releases](https://github.com/byJoey/ech-wk/releases) 下载对应平台的压缩包：

- **Windows**: `ECHWorkers-windows-amd64.zip`
- **macOS Intel**: `ECHWorkers-darwin-amd64.zip`
- **macOS Apple Silicon**: `ECHWorkers-darwin-arm64.zip`
- **Linux x86_64**: `ECHWorkers-linux-amd64.tar.gz`
- **Linux ARM64**: `ECHWorkers-linux-arm64.tar.gz`

解压后直接运行：
- **Windows**: 双击 `ECHWorkersGUI.exe` 启动 GUI，或运行 `ech-workers.exe` 使用命令行
- **macOS**: 运行 `./ECHWorkersGUI` 启动 GUI，或运行 `./ech-workers` 使用命令行

> **注意**: 预编译版本已包含所有依赖，无需安装 Python 或任何其他软件。

## 命令行使用

### 基本命令

`ech-workers` 支持纯命令行运行，适合服务器环境或无图形界面场景。

#### 必需参数

- `-f`: 服务端地址（必需）
  ```bash
  -f your-worker.workers.dev:443
  ```

#### 可选参数

- `-l`: 监听地址（默认：`127.0.0.1:30000`）
  ```bash
  -l 127.0.0.1:30001
  ```

- `-token`: 身份验证令牌
  ```bash
  -token your-token-here
  ```

- `-ip`: 指定服务端 IP（绕过 DNS 解析）
  ```bash
  -ip 1.2.3.4
  ```

- `-dns`: ECH 查询 DoH 服务器（默认：`dns.alidns.com/dns-query`）
  ```bash
  -dns dns.alidns.com/dns-query
  ```

- `-ech`: ECH 查询域名（默认：`cloudflare-ech.com`）
  ```bash
  -ech cloudflare-ech.com
  ```

### 使用示例

#### 基本用法

```bash
# Windows
ech-workers.exe -f your-worker.workers.dev:443 -l 127.0.0.1:30001

# macOS / Linux
./ech-workers -f your-worker.workers.dev:443 -l 127.0.0.1:30001
```

#### 完整参数示例

```bash
./ech-workers \
  -f your-worker.workers.dev:443 \
  -l 0.0.0.0:30001 \
  -token your-token \
  -ip saas.sin.fan \
  -dns dns.alidns.com/dns-query \
  -ech cloudflare-ech.com
```

#### 后台运行

**Linux/macOS:**
```bash
# 使用 nohup
nohup ./ech-workers -f your-worker.workers.dev:443 -l 127.0.0.1:30001 > ech-workers.log 2>&1 &

# 使用 screen
screen -S ech-workers
./ech-workers -f your-worker.workers.dev:443 -l 127.0.0.1:30001
# 按 Ctrl+A 然后 D 分离会话

# 使用 systemd (创建服务文件)
sudo nano /etc/systemd/system/ech-workers.service
```

**systemd 服务文件示例：**
```ini
[Unit]
Description=ECH Workers Proxy
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/ech-workers
ExecStart=/path/to/ech-workers -f your-worker.workers.dev:443 -l 127.0.0.1:30001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

然后启用并启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable ech-workers
sudo systemctl start ech-workers
sudo systemctl status ech-workers
```

**Windows:**
```powershell
# 使用 Start-Process
Start-Process -FilePath "ech-workers.exe" -ArgumentList "-f", "your-worker.workers.dev:443", "-l", "127.0.0.1:30001" -WindowStyle Hidden

# 或使用任务计划程序创建计划任务
```

### 配置代理客户端

启动代理后，配置你的应用程序使用 SOCKS5 代理：

- **代理地址**: `127.0.0.1:30001`（或你指定的监听地址）
- **代理类型**: SOCKS5
- **端口**: 30001（或你指定的端口）

#### 浏览器配置示例

**Chrome/Edge:**
```bash
# Linux/macOS
google-chrome --proxy-server="socks5://127.0.0.1:30001"

# Windows
chrome.exe --proxy-server="socks5://127.0.0.1:30001"
```

**Firefox:**
- 设置 → 网络设置 → 手动代理配置
- SOCKS 主机: `127.0.0.1`
- 端口: `30001`
- SOCKS v5

#### 环境变量配置

**Linux/macOS:**
```bash
export ALL_PROXY=socks5://127.0.0.1:30001
export HTTP_PROXY=socks5://127.0.0.1:30001
export HTTPS_PROXY=socks5://127.0.0.1:30001
```

**Windows (PowerShell):**
```powershell
$env:ALL_PROXY="socks5://127.0.0.1:30001"
$env:HTTP_PROXY="socks5://127.0.0.1:30001"
$env:HTTPS_PROXY="socks5://127.0.0.1:30001"
```

### 查看帮助

```bash
./ech-workers -h
# 或
./ech-workers --help
```

### 日志输出

程序会在控制台输出运行日志，包括：
- 启动信息
- ECH 配置获取状态
- 代理连接信息
- 错误信息

将输出重定向到文件：
```bash
./ech-workers -f your-worker.workers.dev:443 -l 127.0.0.1:30001 > ech-workers.log 2>&1
```

## 软路由部署

### OpenWrt 部署

#### 1. 上传文件

将编译好的 `ech-workers` 上传到软路由：

```bash
# 通过 SCP 上传
scp ech-workers root@192.168.1.1:/usr/bin/

# 或通过 WinSCP、FileZilla 等工具上传
```

#### 2. 设置执行权限

```bash
ssh root@192.168.1.1
chmod +x /usr/bin/ech-workers
```

#### 3. 创建启动脚本

创建 `/etc/init.d/ech-workers`：

```bash
#!/bin/sh /etc/rc.common

START=99
STOP=10
USE_PROCD=1
start_service() {
    procd_open_instance
    procd_set_param command /usr/bin/ech-workers \
        -f your-worker.workers.dev:443 \
        -l 0.0.0.0:30001 \
        -token your-token \
        -ip saas.sin.fan \
        -dns dns.alidns.com/dns-query \
        -ech cloudflare-ech.com
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
```

设置权限：
```bash
chmod +x /etc/init.d/ech-workers
```

#### 4. 启用并启动服务

```bash
/etc/init.d/ech-workers enable
/etc/init.d/ech-workers start
```

#### 5. 查看服务状态

```bash
/etc/init.d/ech-workers status
logread | grep ech-workers
```

#### 6. 配置 OpenWrt 代理

**方法 1: 使用 PassWall / OpenClash 等插件**

在插件中配置：
- 代理类型: SOCKS5
- 服务器: `127.0.0.1`
- 端口: `30001`

**方法 2: 使用 Shadowsocks-libev 的 ss-local**

安装 `shadowsocks-libev-ss-local`，配置为转发到本地 SOCKS5。

**方法 3: 使用 iptables 透明代理**

```bash
# 安装 redsocks
opkg update
opkg install redsocks

# 配置 redsocks.conf
# 将流量转发到 127.0.0.1:30001
```

### iKuai 软路由部署

#### 1. 上传文件

通过 iKuai 的 Web 管理界面或 SSH 上传 `ech-workers` 到 `/bin/` 目录。

#### 2. 创建启动脚本

创建 `/etc/init.d/ech-workers.sh`：

```bash
#!/bin/sh
/bin/ech-workers -f your-worker.workers.dev:443 -l 127.0.1:30001 -token your-token &
```

设置权限：
```bash
chmod +x /etc/init.d/ech-workers.sh
```

#### 3. 添加到开机启动

编辑 `/etc/rc.local`，添加：
```bash
/etc/init.d/ech-workers.sh
```

#### 4. 配置 iKuai 代理

在 iKuai 的"流控分流" → "端口分流"中配置：
- 将指定流量转发到 `127.0.0.1:30001` (SOCKS5)

### 其他软路由系统

#### ROS (RouterOS)

1. 上传 `ech-workers` 到路由器的文件系统
2. 使用 System → Scheduler 创建定时任务启动
3. 配置 NAT 规则将流量转发到本地 SOCKS5 代理

#### 爱快 (iKuai) / 高恪 / 其他

基本步骤类似：
1. 上传可执行文件
2. 创建启动脚本
3. 配置开机自启
4. 在路由器的代理/分流功能中配置使用本地 SOCKS5

### 软路由配置建议

#### 网络配置

```bash
# 监听地址建议使用 0.0.0.0 以允许局域网访问
./ech-workers -f your-worker.workers.dev:443 -l 0.0.0.0:30001

# 或仅监听内网接口
./ech-workers -f your-worker.workers.dev:443 -l 192.168.1.1:30001
```

#### 防火墙规则

确保防火墙允许代理端口：

```bash
# OpenWrt
uci add firewall rule
uci set firewall.@rule[-1].name='Allow-ECH-Workers'
uci set firewall.@rule[-1].src='lan'
uci set firewall.@rule[-1].dest_port='30001'
uci set firewall.@rule[-1].proto='tcp'
uci set firewall.@rule[-1].target='ACCEPT'
uci commit firewall
/etc/init.d/firewall reload
```

#### 性能优化

- 使用 `-ip` 参数指定固定 IP，减少 DNS 查询
- 调整系统资源限制（如文件描述符数量）
- 考虑使用 `systemd` 或 `procd` 管理进程

#### 监控和日志

```bash
# 查看进程状态
ps | grep ech-workers

# 查看日志
logread | grep ech-workers

# 测试连接
curl --socks5 127.0.0.1:30001 http://www.google.com
```

### 常见问题

**Q: 软路由重启后服务未启动？**
A: 检查启动脚本权限和开机启动配置，确保脚本在系统启动时执行。

**Q: 无法访问外网？**
A: 检查防火墙规则，确保代理端口开放，并检查路由器的代理/分流配置。

**Q: 性能不佳？**
A: 考虑使用 `-ip` 参数减少 DNS 查询，或检查软路由的 CPU 和内存使用情况。

**Q: 如何更新程序？**
A: 停止服务 → 替换可执行文件 → 重启服务
```bash
/etc/init.d/ech-workers stop
# 上传新版本
/etc/init.d/ech-workers start
```

### 方法 2: 从源码编译

#### 编译 Go 程序

```bash
# 初始化 Go 模块
go mod init ech-workers
go mod tidy

# 编译
go build -o ech-workers ech-workers.go
```

#### 运行 Python 客户端

```bash
# 安装依赖
pip install PyQt5

# 运行
python3 gui.py
```

## 文件说明

### 核心文件
- `ech-workers.go` - Go 源码（核心代理程序，基于 [CF_NAT](https://t.me/CF_NAT) 的原始代码）
- `gui.py` - Python GUI 客户端（使用 PyQt5，基于 [CF_NAT](https://t.me/CF_NAT) 的原始 Windows 客户端）

### 配置文件
- `go.mod`, `go.sum` - Go 模块文件
- `requirements.txt` - Python 依赖列表

## 系统要求

- **Windows**: Windows 10+ (Windows 11 完全支持)
- **macOS**: macOS 10.13+
- **Linux**: Ubuntu 18.04+ / Debian 10+ / CentOS 7+ (支持 x86_64 和 ARM64)
- **Python**: 3.6+ (仅从源码运行时需要)
- **Go**: 1.23+ (仅编译时需要，ECH 功能需要此版本)

## 配置说明

配置文件保存在：
- **Windows**: `%APPDATA%\ECHWorkersClient\config.json`
- **macOS**: `~/Library/Application Support/ECHWorkersClient/config.json`
- **Linux**: `~/.config/ECHWorkersClient/config.json`

## 使用说明

### 基本使用

1. **配置服务器**
   - 点击"新增"添加服务器配置（会创建新配置，不会覆盖现有配置）
   - 填写服务地址（如：`your-worker.workers.dev:443`）和监听地址（如：`127.0.0.1:30001`）
   - 可选：填写身份令牌、优选IP、DOH服务器、ECH域名等高级选项
   - 点击"保存"保存当前配置

2. **启动代理**
   - 点击"启动代理"按钮启动代理服务
   - 查看日志区域了解运行状态
   - 点击"停止"按钮停止代理服务

3. **设置系统代理**
   - 启动代理后，点击"设置系统代理"按钮
   - 系统会自动配置代理设置
   - 停止代理或关闭程序时会自动清理系统代理

### 分流功能

程序支持三种分流模式：

- **全局代理** - 所有流量都走代理（只绕过本地和内网地址）
- **跳过中国大陆** - 中国网站直连，其他网站走代理
  - 自动下载并应用完整的中国IP列表
  - 包含常见中国域名（*.cn, *.baidu.com, *.qq.com 等）
- **不改变代理** - 不设置系统代理，手动配置

切换分流模式后，如果已设置系统代理，会自动更新绕过规则。

### 系统托盘

- **最小化到托盘** - 关闭窗口时程序会最小化到系统托盘，不会退出
- **显示窗口** - 双击托盘图标或右键菜单选择"显示窗口"
- **退出程序** - 右键托盘图标选择"退出"

### 开机自启

勾选"开机启动"复选框，程序会在系统启动时自动运行并启动代理（如果配置了自动启动参数）。

## 故障排除

### PyQt5 安装问题

如果遇到 PyQt5 安装问题：
```bash
# macOS
pip3 install --user PyQt5
# 或
pip3 install --break-system-packages PyQt5

# Windows
pip install PyQt5

# Linux
sudo apt install python3-pyqt5  # Debian/Ubuntu
# 或
pip3 install PyQt5
```

### 找不到 ech-workers

确保已编译 Go 程序：
```bash
go build -o ech-workers ech-workers.go
```

### Windows 11 系统代理问题

如果 Windows 11 系统代理设置失败：
- 确保以管理员权限运行程序
- 检查防火墙设置
- 程序会自动使用正确的代理格式（`127.0.0.1:端口`）

### Linux 系统代理设置

Linux 暂不支持自动设置系统代理，需要手动配置：
- 在系统设置中配置 SOCKS5 代理为 `127.0.0.1:端口`
- 或使用环境变量：`export ALL_PROXY=socks5://127.0.0.1:端口`

### 中国IP列表加载失败

如果中国IP列表下载失败：
- 程序会使用默认的主要IP段
- 检查网络连接
- 列表会缓存24小时，过期后自动重新下载

### 删除服务器后列表清空

已修复：删除服务器后会自动切换到其他服务器，无需重启程序。

### bad CPU type in executable (macOS)

如果遇到此错误：
- Intel Mac 请下载 `darwin-amd64` 版本
- Apple Silicon Mac 请下载 `darwin-arm64` 版本

## 开发

### 本地测试

```bash
# 编译 Go
go build -o ech-workers ech-workers.go

# 测试 Python
python3 -m py_compile gui.py
```

### GitHub Actions

推送标签会自动触发构建和发布：
```bash
git tag v1.0.0
git push origin v1.0.0
```

## 许可证

本项目基于 [CF_NAT](https://t.me/CF_NAT) 的原始代码开发。

## 技术细节

### ECH (Encrypted Client Hello)

ECH 是 TLS 1.3 的扩展功能，用于加密 TLS 握手中的 SNI（服务器名称指示），提供更强的隐私保护。这是本程序的**核心功能**，需要 Go 1.23+ 支持。

### 中国IP列表

程序会自动从 [mayaxcn/china-ip-list](https://github.com/mayaxcn/china-ip-list) 下载完整的中国IP列表，用于"跳过中国大陆"分流模式。列表会缓存24小时，过期后自动更新。

### 系统代理设置

- **Windows**: 通过注册表设置系统代理，支持 SOCKS5 代理
- **macOS**: 使用 `networksetup` 命令设置所有网络服务的 SOCKS 代理
- **Linux**: 暂不支持自动设置，需要手动配置

## 相关链接

- **原始项目**: [CF_NAT - 优选IP Telegram 频道](https://t.me/CF_NAT)
- **Telegram**: [@CF_NAT](https://t.me/CF_NAT)
- **中国IP列表**: [mayaxcn/china-ip-list](https://github.com/mayaxcn/china-ip-list)
## Star History

<a href="https://www.star-history.com/#byJoey/ech-wk&type=timeline&logscale&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=byJoey/ech-wk&type=timeline&theme=dark&logscale&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=byJoey/ech-wk&type=timeline&logscale&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=byJoey/ech-wk&type=timeline&logscale&legend=top-left" />
 </picture>
</a>
## 贡献

欢迎提交 Issue 和 Pull Request！

