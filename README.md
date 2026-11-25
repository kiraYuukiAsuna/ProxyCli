# 本地 HTTP/HTTPS 代理测试工具包

用于将本机命令行工具或应用的 HTTP/HTTPS 请求转发到 mitmproxy，按需注入请求 Header、改写请求、查看网络请求或模拟响应。快速上手速查见 [QUICK_GUIDE.md](./QUICK_GUIDE.md)。

## 目录与依赖

```text
QUICK_GUIDE.md               一页式快速上手与常用命令速查
scripts/start_proxy.sh       macOS / Linux 前台启动
scripts/proxy_env.sh         Bash / Zsh 启用或停用通用代理环境变量
scripts/install_ca.sh        macOS / Linux 安装或卸载系统信任 CA 证书
scripts/start_proxy.ps1      Windows PowerShell 前台启动
scripts/proxy_env.ps1        PowerShell 启用或停用通用代理环境变量
scripts/install_ca.ps1       Windows PowerShell 安装或卸载系统信任 CA 证书
scripts/http_proxy.py        查看、修改、清空代理规则
assets/http_proxy/           mitmproxy 插件和当前规则
examples/                    通用配置示例
tests/self_test.py           配置、插件、环境、CA 与启动脚本自检
```

准备 mitmproxy 和 Python 3.9 或以上版本，并确保命令在 `PATH` 中。包内不附带这些程序。

- macOS：可用 `brew install --cask mitmproxy` 安装。
- Linux：下载官方独立程序并加入 `PATH`。
- Windows：使用官方安装程序，安装后重新打开终端。
- 已使用 uv 的环境也可执行 `uv tool install mitmproxy`。

安装渠道见 [mitmproxy 官方安装文档](https://docs.mitmproxy.org/stable/overview/installation/)。确认安装：

```sh
mitmdump --version
python3 --version
```

Windows 的 Python 命令使用 `python`；如本机使用 `py -3`，相应替换文档中的 `python`。

## macOS / Linux 快速开始

打开两个终端，都进入工具包文件夹。以下命令从该文件夹执行，路径包含空格时请加引号。

**终端 A：启动代理，保持此终端运行。**

```sh
bash ./scripts/start_proxy.sh 8080
```

代理只监听 `127.0.0.1`。首次运行会在用户目录创建独立 CA，等待终端显示代理已监听后继续。端口占用时启动会失败；可换成 `18080`，并同步修改终端 B 的端口。

**终端 B：启用代理并执行自己的测试命令。**

```sh
source ./scripts/proxy_env.sh 8080

# 使用 curl 或任意支持标准代理环境变量的客户端进行验证。
curl -i https://example.com
```

脚本只设置当前终端的通用代理与 CA 环境变量：

```sh
export http_proxy="http://127.0.0.1:8080"
export https_proxy="http://127.0.0.1:8080"
export HTTP_PROXY="http://127.0.0.1:8080"
export HTTPS_PROXY="http://127.0.0.1:8080"
export SSL_CERT_FILE="$HOME/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem"
export REQUESTS_CA_BUNDLE="$HOME/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem"
export CURL_CA_BUNDLE="$HOME/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem"
export NODE_EXTRA_CA_CERTS="$HOME/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem"
```

这些 CA 变量可让支持对应变量的 CLI（如 `curl`、Python `urllib`/`requests`/`httpx`、Node.js、OpenSSL 等）自动信任代理签发的 HTTPS 证书。对于使用操作系统证书库的客户端（如浏览器、Electron、macOS 原生程序 / Go 程序、GUI 应用等），请按下方「[安装与卸载 CA 证书](#安装与卸载-ca-证书)」安装本工具包生成的 mitmproxy CA。

**结束测试：先在终端 B 停用，再在终端 A 按 `Ctrl+C`。**

```sh
source ./scripts/proxy_env.sh off
```

启用时必须用 `source`；直接执行环境脚本无法改变父终端的环境。新开的终端需重新启用。

## Windows PowerShell 快速开始

打开两个 PowerShell 窗口，都进入工具包目录。

**窗口 A：**

```powershell
.\scripts\start_proxy.ps1 -Port 8080
```

**窗口 B：**

```powershell
. .\scripts\proxy_env.ps1 -Port 8080
curl.exe -i https://example.com
```

结束时先在窗口 B 执行以下命令，再到窗口 A 按 `Ctrl+C`：

```powershell
. .\scripts\proxy_env.ps1 -Off
```

如果组织策略限制脚本执行，可在窗口 A 使用等价的原生命令，窗口 B 直接设置环境变量：

```powershell
# 窗口 A
mitmdump --listen-host 127.0.0.1 --listen-port 8080 --set "confdir=$env:USERPROFILE\.http-proxy-toolkit\mitmproxy" --flow-detail 0 -s .\assets\http_proxy\add_header.py

# 窗口 B：启用
$env:HTTP_PROXY = 'http://127.0.0.1:8080'
$env:HTTPS_PROXY = 'http://127.0.0.1:8080'
$env:SSL_CERT_FILE = "$env:USERPROFILE\.http-proxy-toolkit\mitmproxy\mitmproxy-ca-cert.pem"
$env:REQUESTS_CA_BUNDLE = $env:SSL_CERT_FILE
$env:CURL_CA_BUNDLE = $env:SSL_CERT_FILE
$env:NODE_EXTRA_CA_CERTS = $env:SSL_CERT_FILE

# 窗口 B：停用
foreach ($name in @('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS')) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
```

## 安装与卸载 CA 证书

HTTPS 流量经过代理时由本地 mitmproxy CA 动态签发证书。仅靠 `proxy_env.sh` / `proxy_env.ps1` 设置环境变量只能覆盖读取 `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` / `NODE_EXTRA_CA_CERTS` 的命令行工具；对于依赖操作系统信任库的客户端（Chrome / Safari / Edge、Electron、macOS 原生及 Go 程序、Windows 原生应用等），需要将 CA 证书安装到系统信任库。

**前提**：先启动一次代理（`start_proxy.sh` / `start_proxy.ps1`），等待生成 `~/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem` 后再执行安装脚本。

### macOS / Linux

```sh
# 安装：macOS 默认安装到当前用户「登录钥匙串」（可能弹出系统授权框）；
# Linux 自动识别 Debian/Ubuntu、RHEL/Fedora、Arch 并安装到系统 CA 目录（需要 sudo）。
bash ./scripts/install_ca.sh

# macOS 安装到「系统钥匙串」（所有用户生效；无图形界面或 SSH 终端推荐使用，需要 sudo）。
bash ./scripts/install_ca.sh --system

# 卸载（不再调试时建议移除；安装时用了 --system 则卸载时也需加 --system）。
bash ./scripts/install_ca.sh --uninstall
bash ./scripts/install_ca.sh --system --uninstall
```

可通过 `--cert <PATH>` 指定自定义证书路径；完整参数见 `bash ./scripts/install_ca.sh --help`。

### Windows PowerShell

```powershell
# 安装到当前用户的「受信任的根证书颁发机构」（无需管理员权限，会弹出确认框）。
.\scripts\install_ca.ps1

# 安装到本机系统证书库（需以管理员身份运行 PowerShell）。
.\scripts\install_ca.ps1 -System

# 卸载（安装时用了 -System 则卸载时也需加 -System）。
.\scripts\install_ca.ps1 -Uninstall
.\scripts\install_ca.ps1 -System -Uninstall
```

### 浏览器与特殊运行时

- **浏览器 / 移动设备（备选）**：配置代理后直接访问 `http://mitm.it`，可按页面提示下载并安装当前代理的 CA 证书。
- **Firefox**：默认使用独立证书库，不自动信任系统根证书；可在 `about:config` 将 `security.enterprise_roots.enabled` 设为 `true`，或在「设置 → 隐私与安全 → 证书 → 查看证书 → 证书颁发机构」手动导入 `mitmproxy-ca-cert.pem`。
- **Java**：使用独立 `cacerts` 信任库，可通过 `keytool -importcert` 导入该证书。
- **安全提醒**：信任该 CA 后，持有对应私钥（`mitmproxy-ca.pem`）即可签发任意域名证书。请勿外泄 `.http-proxy-toolkit/mitmproxy` 目录，调试结束后及时卸载。

## 注入 Header

默认规则为空，代理正常转发请求与响应。按测试需要添加规则；以下使用通用示例值：

```sh
python3 ./scripts/http_proxy.py headers X-Debug-Label=local-test
python3 ./scripts/http_proxy.py show
```

Windows 将 `python3` 替换为 `python`。`headers` 会新增或覆盖同名 Header，并保留其他规则。值中包含 `=` 时，仅第一个 `=` 用于分隔名称和值。

规则在下一次请求时自动重载，无需重启。Header 会加到所有经过此代理的请求上；使用本地代理的客户端范围由测试者控制。

清空所有 Header、请求改写与响应改写规则：

```sh
python3 ./scripts/http_proxy.py clear
```

## 查看请求与响应

默认启动脚本使用 `--flow-detail 0` 安静转发，不打印流量详情、不保存抓包文件。

需要查看请求与服务端响应时，先停止已有代理，直接通过启动脚本的参数开启（沿用终端 B 的代理环境即可，无需手动调用 `mitmweb` 或 `mitmdump`）：

**方式 1：Web 界面查看（推荐）**

```sh
# macOS / Linux，默认代理端口 8080、Web 端口 8081。
bash ./scripts/start_proxy.sh --web

# 自定义代理端口和 Web 端口（传 --web-port 时会自动启用 Web 界面）。
bash ./scripts/start_proxy.sh 8080 --web-port 8081
```

```powershell
# Windows PowerShell。
.\scripts\start_proxy.ps1 -Web
.\scripts\start_proxy.ps1 -Port 8080 -WebPort 8081
```

打开终端提示的本机 Web 地址；如提示访问口令，使用该终端给出的口令。选择请求后切换至 Request / Response 查看完整内容。

**方式 2：在终端直接打印流量详情**

```sh
# macOS / Linux：级别 0-4（0 安静、1 摘要、2 含 Header、3 含截断 Body、4 含完整 Body）。
bash ./scripts/start_proxy.sh --flow-detail 4
bash ./scripts/start_proxy.sh 8080 --flow-detail 3
```

```powershell
# Windows PowerShell。
.\scripts\start_proxy.ps1 -FlowDetail 4
```

`--web` 与 `--flow-detail` 不可同时使用，且 Web 端口需与代理端口不同；完整参数可通过 `bash ./scripts/start_proxy.sh --help` 查看。界面与终端输出可能展示完整凭证，导出或截图分享前请脱敏。

## 改写请求（可选）

除全局 `custom_headers` 外，插件支持在 `request_modifiers` 中按 URL 和 HTTP 方法精确改写请求，覆盖 mitmproxy `http.Request` 全部可写字段。`example.invalid` 与 `staging.example.invalid` 为占位域名，使用前替换为自己有权测试的目标地址。

### 常用命令示例

```sh
# 1. 转发到目标主机并替换路径前缀、增删 Query / Header、局部修改 JSON 请求体。
python3 ./scripts/http_proxy.py request \
  --match-url 'https://example.invalid/api/v1/demo' \
  --match-method POST \
  --host staging.example.invalid \
  --port 8443 \
  --path-replace '/api/v1/=/api/v2/' \
  --query debug=1 \
  --remove-query legacy \
  --header X-Request-Rewrite=enabled \
  --remove-header X-Deprecated \
  --body-patch '{"dry_run":true}'

# 2. 改写请求方法与完整 URL，或替换整段文本请求体。
python3 ./scripts/http_proxy.py request \
  --match-url 'https://example.invalid/api/raw' \
  --method POST \
  --path '/api/raw-override?source=proxy' \
  --body '{"override":true}'

# 3. 改写表单字段（application/x-www-form-urlencoded 或 multipart/form-data）。
python3 ./scripts/http_proxy.py request \
  --match-url 'https://example.invalid/api/form' \
  --form mode=preview \
  --remove-form obsolete

# 完成后清空所有规则。
python3 ./scripts/http_proxy.py clear
```

完整 CLI 参数可通过 `python3 ./scripts/http_proxy.py request --help` 查看。复杂规则或 Windows PowerShell 环境建议直接编辑 `assets/http_proxy/proxy_config.json`（修改后自动热加载，无需重启代理），完整配置结构见 `examples/proxy_config.example.json`。

### `request_modifiers` 支持的全部字段

| 分类 | 字段 | 说明 |
|---|---|---|
| 匹配条件 | `match_url`、`match_method` | `match_url` 按 URL 子串匹配（必填）；`match_method` 可选，按 HTTP 方法数组过滤（不区分大小写）。 |
| 协议与方法 | `method`、`http_version` | 改写请求方法（如 `POST`）或协议版本（如 `HTTP/1.1`、`HTTP/2.0`）。 |
| 目标与路由 | `url`、`scheme`、`host`、`port`、`authority`、`host_header` | 替换完整 URL，或分别改写协议、上游主机、端口、HTTP/2 `:authority` 与 `Host` 头。 |
| 路径 | `path`、`path_components`、`path_replace` | `path` 替换路径（含 Query）；`path_components` 按段替换且保留原 Query；`path_replace` 支持单个 `{"from","to"}` 或数组，仅替换路径部分。 |
| Query | `query`、`remove_query` | 增改或删除查询参数；`query` 的值支持字符串或字符串数组（同名多值）。 |
| Header / Cookie / Trailer | `headers`、`remove_headers`、`cookies`、`remove_cookies`、`trailers`、`remove_trailers` | 增改或删除请求头、Cookie 与 HTTP Trailer；值支持字符串或字符串数组。 |
| 请求体（互斥） | `body_base64`、`body`、`body_patch`、`urlencoded_form` / `remove_urlencoded_form`、`multipart_form` / `remove_multipart_form` | 分别对应原始字节（Base64）、纯文本、JSON 对象递归合并、`application/x-www-form-urlencoded` 表单、`multipart/form-data` 表单。 |
| 缓存与压缩 | `anticache`、`anticomp` | 设为 `true` 时分别调用 mitmproxy 的 `anticache()`（移除条件缓存头）与 `anticomp()`（禁用响应压缩）。 |

规则说明：

- `request_modifiers` 在全局 `custom_headers` 之后执行，因此单条规则可覆盖或通过 `remove_headers` 移除全局注入的 Header。
- 按顺序匹配，第一条命中的规则生效；同一条规则内按「协议/方法 → 目标地址 → 路径 → Query → 缓存/压缩 → Header/Cookie/Trailer → 请求体」顺序应用，确保组合配置可预测。
- 修改 `host` 时 mitmproxy 会同步更新 `Host` 头；若需发往某上游主机同时携带不同的虚拟主机 `Host` 头，可在同条规则中再指定 `host_header`。仅修改 `scheme`（如 `https` → `http`）不会自动更改 `port`，如需切换端口请同时指定 `port`。
- 配置 `body_patch` 时原请求体应为 JSON 对象；`multipart_form` 会按 UTF-8 编码键值写入，需要精确控制原始二进制载荷时请使用 `body_base64`。

## 模拟响应（可选）

以下是配置模板。`example.invalid` 是占位域名，使用前替换为自己有权测试的目标地址。

```sh
# 修改匹配响应的 JSON 对象字段与响应头，保留其他字段。
python3 ./scripts/http_proxy.py response \
  --match-url 'https://example.invalid/api/demo' \
  --body-patch '{"example":true,"msg":"test response"}' \
  --header X-Mock-Source=proxy

# 完整替换匹配响应的内容与状态码。
python3 ./scripts/http_proxy.py response \
  --match-url 'https://example.invalid/api/demo' \
  --body '{"example":true}' \
  --status-code 200

# 完成后清空所有规则。
python3 ./scripts/http_proxy.py clear
```

PowerShell 建议直接编辑 `assets/http_proxy/proxy_config.json`，避免不同版本的原生命令参数引号差异；配置结构见 `examples/proxy_config.example.json`。响应规则按 URL 子串匹配，第一条命中的规则生效。配置 `body_patch` 时，目标响应应是 JSON 对象。

## 证书、停止与排查

| 现象 | 检查方法 |
|---|---|
| `mitmdump` / `mitmweb` 找不到 | 先安装 mitmproxy，确认 `mitmdump --version` 和 `mitmweb --version` 能执行。 |
| 端口被占用 | 为启动命令和环境脚本选择同一个空闲端口；不要结束不认识的进程。 |
| `connection refused` | 确认窗口 A 中代理仍在运行，地址和端口一致。 |
| 找不到 CA 文件 | 先启动一次代理，等待它生成 CA，再执行环境脚本。 |
| TLS 不信任代理证书 | CLI 客户端检查 `SSL_CERT_FILE`、`REQUESTS_CA_BUNDLE`、`CURL_CA_BUNDLE`、`NODE_EXTRA_CA_CERTS` 是否指向当前代理的 `mitmproxy-ca-cert.pem`；依赖系统证书库的客户端（浏览器、Go、macOS/Windows 原生应用等）先执行 `install_ca.sh` / `install_ca.ps1` 安装 CA。 |
| 客户端未走代理 | 确认目标程序支持标准 `HTTP_PROXY` / `HTTPS_PROXY` 变量，且在已 `source` 环境脚本的同一终端运行；部分有独立代理配置的客户端需单独设置其代理地址。 |
| 无法验证目标服务器证书 | 这是代理到上游服务器的 TLS 问题；检查目标证书链和组织 CA 配置，不能通过信任代理 CA 解决。 |
| Header 或改写未生效 | 查看 `http_proxy.py show`，确认启动的是本文件夹的插件，目标客户端在已启用代理的终端运行。 |
| 改完环境没有影响已运行进程 | 停止并重新运行该程序，已有进程不会继承后续的环境变更。 |

停用脚本会清除当前终端中的通用代理与 CA 环境变量（`http_proxy`、`https_proxy`、`HTTP_PROXY`、`HTTPS_PROXY`、`SSL_CERT_FILE`、`REQUESTS_CA_BUNDLE`、`CURL_CA_BUNDLE`、`NODE_EXTRA_CA_CERTS`），不修改持久化配置、系统代理或系统证书信任。停止代理进程需要在其窗口按 `Ctrl+C`。

每台机器在首次启动时生成自己的 CA，目录为用户目录下的 `.http-proxy-toolkit/mitmproxy`。`mitmproxy-ca-cert.pem` 是公有 CA 证书，`mitmproxy-ca.pem` 包含私钥；证书文件类型见 [mitmproxy 证书文档](https://docs.mitmproxy.org/stable/concepts/certificates/)。请勿把该运行目录、真实凭证或原始抓包随工具包分发。

## 自检与共享

```sh
python3 ./tests/self_test.py
```

自检在临时副本中检查 Header 注入、配置修改、请求改写、响应规则、清空行为、环境脚本、CA 安装脚本及启动脚本参数，不访问业务服务、不使用账号凭证。

验证范围：macOS 已验证 HTTP Header 转发、HTTPS CA 信任、Bash/Zsh 环境启停、端口占用失败和进程停止。Linux 与 Windows 提供对应脚本及命令，尚未进行真机验证。

分享前检查 `assets/http_proxy/proxy_config.json`，保留需要分发的通用规则，移除个人或环境专属值。仅分享工具包文件夹即可；接收者使用自己的客户端配置和本机生成的 CA。
