# HTTP/HTTPS 代理工具包 Quick Guide

一页式速查指南，覆盖启动、HTTPS 证书信任、抓包查看、请求/响应改写与收尾清理。完整参数和排障说明见 [README.md](./README.md)。

## 0. 环境准备

确认 `mitmdump` 和 Python 3.9+ 已在 `PATH` 中（未安装 mitmproxy 时，macOS 可执行 `brew install --cask mitmproxy`，其余平台见 [官方安装文档](https://docs.mitmproxy.org/stable/overview/installation/)）：

```sh
mitmdump --version
python3 --version   # Windows 使用 python --version
```

---

## 1. 三步跑通本地代理

打开两个终端，都进入本工具包目录。

### macOS / Linux

```sh
# 终端 A：启动代理（默认 8080，静默模式；加 --web 可打开 Web 抓包界面）
bash ./scripts/start_proxy.sh 8080
# 或：bash ./scripts/start_proxy.sh --web
```

```sh
# 终端 B：启用代理环境变量并测试
source ./scripts/proxy_env.sh 8080
curl -i https://example.com
```

### Windows PowerShell

```powershell
# 窗口 A：启动代理（加 -Web 可打开 Web 抓包界面）
.\scripts\start_proxy.ps1 -Port 8080
# 或：.\scripts\start_proxy.ps1 -Web
```

```powershell
# 窗口 B：启用代理环境变量并测试
. .\scripts\proxy_env.ps1 -Port 8080
curl.exe -i https://example.com
```

> `proxy_env` 脚本会自动设置通用代理变量（`HTTP_PROXY` / `HTTPS_PROXY` 等）与 CA 环境变量（`SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` / `NODE_EXTRA_CA_CERTS`）。

---

## 2. 安装系统 CA 证书（浏览器 / 原生应用需要）

`curl`、Python、Node.js 等命令行工具在 `source ./scripts/proxy_env.sh` 后的终端中可直接使用环境变量信任 CA；若要拦截 **Chrome / Safari / Edge、Electron、Go / macOS / Windows 原生应用** 的 HTTPS 流量，先启动一次代理生成 CA，再执行安装脚本：

```sh
# macOS（默认安装到登录钥匙串；SSH / 无弹窗环境或需全局生效时加 --system）
bash ./scripts/install_ca.sh
bash ./scripts/install_ca.sh --system

# Linux（自动识别 Debian/Ubuntu、RHEL/Fedora、Arch，自动调用 sudo）
bash ./scripts/install_ca.sh
```

```powershell
# Windows PowerShell（默认安装到当前用户根证书库；加 -System 安装到本机证书库，需管理员权限）
.\scripts\install_ca.ps1
.\scripts\install_ca.ps1 -System
```

- 浏览器或移动设备配置代理后，也可直接访问 `http://mitm.it` 下载并安装当前代理的 CA 证书。
- Firefox 需在 `about:config` 开启 `security.enterprise_roots.enabled = true`，或在设置中手动导入 `~/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem`。

---

## 3. 高频操作速查

规则写入 `assets/http_proxy/proxy_config.json`，**保存后立即热加载，无需重启代理**。Windows 下将 `python3` 替换为 `python`。

### 查看抓包流量

```sh
bash ./scripts/start_proxy.sh --web              # 推荐：Web UI（默认代理 8080，Web 8081）
bash ./scripts/start_proxy.sh --flow-detail 4    # 终端打印：0 静默 / 1 摘要 / 2 +头 / 3 +截断体 / 4 +完整体
```

### 全局注入请求 Header

```sh
python3 ./scripts/http_proxy.py headers X-Debug-Label=local-test
```

### 按 URL / 方法改写请求

```sh
# 转发主机、替换路径、增删 Query/Header、递归合并 JSON Body
python3 ./scripts/http_proxy.py request \
  --match-url 'https://example.invalid/api/v1/demo' \
  --match-method POST \
  --host staging.example.invalid \
  --port 8443 \
  --path-replace '/api/v1/=/api/v2/' \
  --query debug=1 \
  --remove-query legacy \
  --header X-Rewrite=enabled \
  --remove-header X-Deprecated \
  --body-patch '{"dry_run":true}'

# 替换请求路径与完整文本 Body
python3 ./scripts/http_proxy.py request \
  --match-url 'https://example.invalid/api/raw' \
  --method POST \
  --path '/api/raw-override?source=proxy' \
  --body '{"override":true}'

# 改写表单字段（application/x-www-form-urlencoded）
python3 ./scripts/http_proxy.py request \
  --match-url 'https://example.invalid/api/form' \
  --form mode=preview \
  --remove-form obsolete
```

### 模拟或改写响应

```sh
# 局部修改 JSON 响应体与响应头
python3 ./scripts/http_proxy.py response \
  --match-url 'https://example.invalid/api/demo' \
  --body-patch '{"example":true,"msg":"mocked"}' \
  --header X-Mock=1

# 完整替换响应体与状态码
python3 ./scripts/http_proxy.py response \
  --match-url 'https://example.invalid/api/demo' \
  --body '{"ok":true}' \
  --status-code 200
```

### 查看与清空规则

```sh
python3 ./scripts/http_proxy.py show    # 查看当前生效规则
python3 ./scripts/http_proxy.py clear   # 一键清空全部 Header、请求改写与响应改写规则
```

复杂规则（多规则、`multipart_form`、`body_base64`、`trailers`、`cookies`、`host_header`、`anticache`、`anticomp` 等）建议直接编辑 `assets/http_proxy/proxy_config.json`，完整示例见 [examples/proxy_config.example.json](./examples/proxy_config.example.json)。

---

## 4. 结束测试与清理

```sh
# 1. 终端 B 停用当前终端代理环境变量
source ./scripts/proxy_env.sh off         # PowerShell: . .\scripts\proxy_env.ps1 -Off

# 2. 终端 A 按 Ctrl+C 停止代理进程

# 3. 清空代理改写规则（可选）
python3 ./scripts/http_proxy.py clear

# 4. 如安装过系统 CA，不再调试时建议卸载
bash ./scripts/install_ca.sh --uninstall            # 安装时用了 --system 则加 --system
# PowerShell: .\scripts\install_ca.ps1 -Uninstall   # 安装时用了 -System 则加 -System
```

---

## 5. 常见卡点速查

| 现象 | 处理方式 |
|---|---|
| `CA not found` | 先启动一次 `start_proxy` 生成 `~/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem`，再执行 `proxy_env` 或 `install_ca`。 |
| HTTPS 证书不受信任 | 确认在同一终端 `source` 了 `proxy_env`；浏览器 / 原生应用先执行 `install_ca` 安装系统 CA。 |
| 规则未生效 | 执行 `python3 ./scripts/http_proxy.py show` 确认规则；请求/响应改写按顺序仅第一条匹配规则生效。 |
| 修改 `scheme` 后连不通 | 切换 `https` ↔ `http` 时同步指定 `port`（如 `80` / `443`）。 |
| 停用后程序仍走代理 | 重启目标进程（已有进程不会继承后续环境变量变更）。 |

运行离线自检确认工具包状态：

```sh
python3 ./tests/self_test.py
```
