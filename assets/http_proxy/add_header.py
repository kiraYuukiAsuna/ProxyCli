"""
mitmproxy 脚本：拦截所有 HTTP/HTTPS 请求，支持全局注入 Header、按规则改写请求与改写响应。

使用方法：
    mitmproxy  -s add_header.py --listen-port 8080
    mitmdump   -s add_header.py --listen-port 8080   # 无 UI 模式
    mitmweb    -s add_header.py --listen-port 8080   # Web UI 模式

配置文件：proxy_config.json（修改后自动热加载，无需重启代理）
"""

import base64
import json
import os
from mitmproxy import http

# ============================================================
# 配置文件路径
# ============================================================
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_config.json")

# ============================================================
# 配置热加载
# ============================================================
_config_mtime = None
_config_cache = {"custom_headers": {}, "request_modifiers": [], "response_modifiers": []}


def _load_config() -> dict:
    """加载配置文件，返回配置字典。"""
    global _config_mtime, _config_cache
    try:
        st = os.stat(CONFIG_FILE)
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        if sig == _config_mtime:
            return _config_cache
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError("proxy_config.json must contain a JSON object")
        _config_mtime = sig
        _config_cache = cfg
        print(f"[配置热加载] 已加载配置文件 (mtime={st.st_mtime})")
        return cfg
    except Exception as e:
        print(f"[配置热加载] 加载失败: {e}")
        return _config_cache


# ============================================================
# 请求/响应处理
# ============================================================


def request(flow: http.HTTPFlow) -> None:
    """在每个请求发出前注入自定义 Header，并按规则改写匹配的请求。"""
    cfg = _load_config()
    for key, value in (cfg.get("custom_headers") or {}).items():
        flow.request.headers[key] = str(value)

    url = flow.request.pretty_url
    method = getattr(flow.request, "method", "")
    for mod in cfg.get("request_modifiers") or []:
        if _request_matches(url, method, mod):
            _apply_request_modifier(flow, mod, url)
            return


def response(flow: http.HTTPFlow) -> None:
    """拦截并改写匹配的响应。"""
    cfg = _load_config()
    url = flow.request.pretty_url
    for mod in cfg.get("response_modifiers") or []:
        if _url_matches(url, mod.get("match_url", [])):
            _apply_modifier(flow, mod, url)
            return


def _url_matches(url: str, patterns: list) -> bool:
    """检查 URL 是否匹配任一关键字。"""
    for p in patterns:
        if p in url:
            return True
    return False


def _request_matches(url: str, method: str, mod: dict) -> bool:
    """检查请求是否同时满足 URL 与可选 HTTP 方法匹配条件。"""
    if not _url_matches(url, mod.get("match_url", [])):
        return False
    match_method = mod.get("match_method")
    if match_method:
        methods = match_method if isinstance(match_method, list) else [match_method]
        allowed = {str(m).upper() for m in methods}
        if str(method).upper() not in allowed:
            return False
    return True


def _set_multidict(mapping, key, value, *, as_bytes: bool = False) -> None:
    """向 mitmproxy MultiDict/Headers 或普通 dict 写入单值或多值字段。"""
    enc = (lambda v: str(v).encode("utf-8")) if as_bytes else str
    target_key = enc(key)
    if isinstance(value, list):
        target_values = [enc(v) for v in value]
        if hasattr(mapping, "set_all"):
            mapping.set_all(target_key, target_values)
        else:
            mapping[target_key] = target_values
    else:
        mapping[target_key] = enc(value)


def _remove_keys(mapping, keys: list, *, as_bytes: bool = False) -> None:
    """从 mitmproxy MultiDict/Headers 或普通 dict 移除指定键。"""
    enc = (lambda v: str(v).encode("utf-8")) if as_bytes else str
    for key in keys:
        target_key = enc(key)
        if target_key in mapping:
            mapping.pop(target_key, None)


def _apply_request_modifier(flow: http.HTTPFlow, mod: dict, url: str) -> None:
    """应用请求改写规则（支持 mitmproxy http.Request 全部可写字段）。"""
    req = flow.request

    # 1. 协议与方法
    if "http_version" in mod:
        req.http_version = str(mod["http_version"])
    if "method" in mod:
        req.method = str(mod["method"]).upper()

    # 2. 完整 URL 与目标地址（host_header 放在 host 之后，便于独立覆盖虚拟主机头）
    if "url" in mod:
        req.url = str(mod["url"])
    if "scheme" in mod:
        req.scheme = str(mod["scheme"])
    if "host" in mod:
        req.host = str(mod["host"])
    if "port" in mod:
        req.port = int(mod["port"])
    if "authority" in mod:
        req.authority = str(mod["authority"])
    if "host_header" in mod:
        req.host_header = str(mod["host_header"])

    # 3. 路径改写
    if "path" in mod:
        req.path = str(mod["path"])
    if "path_components" in mod:
        req.path_components = [str(part) for part in mod["path_components"]]
    if "path_replace" in mod:
        replacements = mod["path_replace"]
        if isinstance(replacements, dict):
            replacements = [replacements]
        path_part, sep, query_part = req.path.partition("?")
        for item in replacements:
            old = item.get("from", "")
            new = item.get("to", "")
            if old:
                path_part = path_part.replace(str(old), str(new))
        req.path = f"{path_part}{sep}{query_part}"

    # 4. Query 参数（放在路径改写之后，便于组合使用）
    if "remove_query" in mod:
        _remove_keys(req.query, mod["remove_query"])
    if "query" in mod:
        for k, v in mod["query"].items():
            _set_multidict(req.query, k, v)

    # 5. 缓存与压缩辅助方法
    if mod.get("anticache"):
        req.anticache()
    if mod.get("anticomp"):
        req.anticomp()

    # 6. Header / Cookie / Trailer
    if "remove_headers" in mod:
        _remove_keys(req.headers, mod["remove_headers"])
    if "headers" in mod:
        for k, v in mod["headers"].items():
            _set_multidict(req.headers, k, v)

    if "remove_cookies" in mod:
        _remove_keys(req.cookies, mod["remove_cookies"])
    if "cookies" in mod:
        for k, v in mod["cookies"].items():
            _set_multidict(req.cookies, k, v)

    if "remove_trailers" in mod and req.trailers is not None:
        _remove_keys(req.trailers, mod["remove_trailers"])
    if "trailers" in mod:
        if req.trailers is None:
            headers_cls = getattr(http, "Headers", None)
            req.trailers = headers_cls() if headers_cls is not None else {}
        for k, v in mod["trailers"].items():
            _set_multidict(req.trailers, k, v)

    # 7. 请求体（互斥，按优先级生效）
    if "body_base64" in mod:
        try:
            req.content = base64.b64decode(mod["body_base64"], validate=True)
        except (ValueError, TypeError) as e:
            print(f"[请求改写] Base64 解码失败，跳过 body_base64: {url}, error: {e}")
    elif "body" in mod:
        req.text = str(mod["body"])
    elif "body_patch" in mod:
        try:
            data = json.loads(req.text)
            if not isinstance(data, dict):
                raise TypeError("JSON body is not an object")
            _deep_merge(data, mod["body_patch"])
            req.text = json.dumps(data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[请求改写] JSON 解析失败，跳过 body_patch: {url}, error: {e}")
    elif "urlencoded_form" in mod or "remove_urlencoded_form" in mod:
        if "remove_urlencoded_form" in mod:
            _remove_keys(req.urlencoded_form, mod["remove_urlencoded_form"])
        if "urlencoded_form" in mod:
            for k, v in mod["urlencoded_form"].items():
                _set_multidict(req.urlencoded_form, k, v)
    elif "multipart_form" in mod or "remove_multipart_form" in mod:
        if "remove_multipart_form" in mod:
            _remove_keys(req.multipart_form, mod["remove_multipart_form"], as_bytes=True)
        if "multipart_form" in mod:
            for k, v in mod["multipart_form"].items():
                _set_multidict(req.multipart_form, k, v, as_bytes=True)

    print(f"[请求改写] 已应用规则: {url} -> {getattr(req, 'method', '')} {req.pretty_url}")


def _apply_modifier(flow: http.HTTPFlow, mod: dict, url: str) -> None:
    """应用响应改写规则。"""
    if "status_code" in mod:
        flow.response.status_code = int(mod["status_code"])

    if "headers" in mod:
        for k, v in mod["headers"].items():
            _set_multidict(flow.response.headers, k, v)

    if "body" in mod:
        flow.response.text = str(mod["body"])
        print(f"[响应改写] 已替换 body: {url}")
        return

    if "body_patch" in mod:
        try:
            data = json.loads(flow.response.text)
            if not isinstance(data, dict):
                raise TypeError("JSON body is not an object")
            _deep_merge(data, mod["body_patch"])
            flow.response.text = json.dumps(data, ensure_ascii=False)
            print(f"[响应改写] 已 patch body: {url}")
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[响应改写] JSON 解析失败，跳过 patch: {url}, error: {e}")


def _deep_merge(base: dict, patch: dict) -> None:
    """递归合并 patch 到 base（原地修改）。"""
    for key, value in patch.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
