#!/usr/bin/env python3
"""Manage local HTTP/HTTPS proxy request headers, request modifiers, and response overrides."""

from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any


REQUEST_BODY_FIELDS = (
    "body",
    "body_base64",
    "body_patch",
    "urlencoded_form",
    "remove_urlencoded_form",
    "multipart_form",
    "remove_multipart_form",
)


def config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "http_proxy" / "proxy_config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"custom_headers": {}, "request_modifiers": [], "response_modifiers": []}
    with path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("proxy_config.json must contain a JSON object")
    config.setdefault("custom_headers", {})
    config.setdefault("request_modifiers", [])
    config.setdefault("response_modifiers", [])
    return config


def save_config(config: dict[str, Any]) -> None:
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(config, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, target)
    except Exception:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
        raise


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def parse_pairs(values: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected NAME=VALUE, got: {value}")
        name, header_value = value.split("=", 1)
        if not name:
            raise ValueError(f"header name cannot be empty: {value}")
        pairs[name] = header_value
    return pairs


def parse_multi_pairs(values: list[str]) -> dict[str, str | list[str]]:
    pairs: dict[str, str | list[str]] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected KEY=VALUE, got: {value}")
        name, item_value = value.split("=", 1)
        if not name:
            raise ValueError(f"key cannot be empty: {value}")
        if name not in pairs:
            pairs[name] = item_value
        elif isinstance(pairs[name], list):
            pairs[name].append(item_value)
        else:
            pairs[name] = [pairs[name], item_value]
    return pairs


def parse_replace_pairs(values: list[str]) -> list[dict[str, str]]:
    replacements: list[dict[str, str]] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected OLD=NEW, got: {value}")
        old, new = value.split("=", 1)
        if not old:
            raise ValueError(f"replacement source cannot be empty: {value}")
        replacements.append({"from": old, "to": new})
    return replacements


def find_modifier(config: dict[str, Any], matches: list[str]) -> dict[str, Any]:
    for modifier in config["response_modifiers"]:
        configured_matches = modifier.get("match_url", [])
        if any(pattern in configured_matches for pattern in matches):
            return modifier
    modifier: dict[str, Any] = {"match_url": matches}
    config["response_modifiers"].append(modifier)
    return modifier


def find_request_modifier(
    config: dict[str, Any], matches: list[str], match_methods: list[str] | None
) -> dict[str, Any]:
    normalized_methods = [m.upper() for m in match_methods] if match_methods else None
    for modifier in config["request_modifiers"]:
        configured_matches = modifier.get("match_url", [])
        configured_methods = modifier.get("match_method")
        if configured_methods is not None:
            configured_methods = [str(m).upper() for m in configured_methods]
        if (
            any(pattern in configured_matches for pattern in matches)
            and configured_methods == normalized_methods
        ):
            return modifier
    modifier: dict[str, Any] = {"match_url": matches}
    if normalized_methods:
        modifier["match_method"] = normalized_methods
    config["request_modifiers"].append(modifier)
    return modifier


def _merge_mapping_and_removals(
    modifier: dict[str, Any],
    set_key: str,
    remove_key: str,
    additions: list[str] | None,
    removals: list[str] | None,
) -> None:
    if additions:
        parsed = parse_multi_pairs(additions)
        mapping = modifier.setdefault(set_key, {})
        mapping.update(parsed)
        if remove_key in modifier:
            remaining = [k for k in modifier[remove_key] if k not in parsed]
            if remaining:
                modifier[remove_key] = remaining
            else:
                modifier.pop(remove_key, None)
    if removals:
        existing = modifier.setdefault(remove_key, [])
        for key in removals:
            if key not in existing:
                existing.append(key)
            if set_key in modifier:
                modifier[set_key].pop(key, None)
        if set_key in modifier and not modifier[set_key]:
            modifier.pop(set_key, None)


def _clear_other_body_fields(modifier: dict[str, Any], keep: set[str]) -> None:
    for field in REQUEST_BODY_FIELDS:
        if field not in keep:
            modifier.pop(field, None)


def set_headers(values: list[str]) -> None:
    config = load_config()
    config["custom_headers"].update(parse_pairs(values))
    save_config(config)


def set_request(args: argparse.Namespace) -> None:
    if args.port is not None and not (1 <= args.port <= 65535):
        raise ValueError(f"port must be between 1 and 65535, got: {args.port}")

    body_modes = [
        name
        for name, active in (
            ("--body", args.body is not None),
            ("--body-base64", args.body_base64 is not None),
            ("--body-patch", args.body_patch is not None),
            ("--form/--remove-form", bool(args.form or args.remove_form)),
            ("--multipart/--remove-multipart", bool(args.multipart or args.remove_multipart)),
        )
        if active
    ]
    if len(body_modes) > 1:
        raise ValueError(f"cannot combine mutually exclusive body options: {', '.join(body_modes)}")

    parsed_body_patch: dict[str, Any] | None = None
    if args.body_patch is not None:
        loaded = json.loads(args.body_patch)
        if not isinstance(loaded, dict):
            raise ValueError("--body-patch must be a JSON object")
        parsed_body_patch = loaded

    if args.body_base64 is not None:
        base64.b64decode(args.body_base64, validate=True)

    replacements = parse_replace_pairs(args.path_replace) if args.path_replace else None

    config = load_config()
    modifier = find_request_modifier(config, args.match_url, args.match_method)

    if args.http_version is not None:
        modifier["http_version"] = args.http_version
    if args.method is not None:
        modifier["method"] = args.method.upper()
    if args.url is not None:
        modifier["url"] = args.url
    if args.scheme is not None:
        modifier["scheme"] = args.scheme
    if args.host is not None:
        modifier["host"] = args.host
    if args.port is not None:
        modifier["port"] = args.port
    if args.authority is not None:
        modifier["authority"] = args.authority
    if args.host_header is not None:
        modifier["host_header"] = args.host_header
    if args.path is not None:
        modifier["path"] = args.path
    if args.path_components:
        modifier["path_components"] = args.path_components
    if replacements:
        modifier["path_replace"] = replacements[0] if len(replacements) == 1 else replacements

    _merge_mapping_and_removals(modifier, "query", "remove_query", args.query, args.remove_query)
    _merge_mapping_and_removals(modifier, "headers", "remove_headers", args.header, args.remove_header)
    _merge_mapping_and_removals(modifier, "cookies", "remove_cookies", args.cookie, args.remove_cookie)
    _merge_mapping_and_removals(modifier, "trailers", "remove_trailers", args.trailer, args.remove_trailer)

    if args.anticache:
        modifier["anticache"] = True
    if args.anticomp:
        modifier["anticomp"] = True

    if args.body is not None:
        _clear_other_body_fields(modifier, {"body"})
        modifier["body"] = args.body
    elif args.body_base64 is not None:
        _clear_other_body_fields(modifier, {"body_base64"})
        modifier["body_base64"] = args.body_base64
    elif parsed_body_patch is not None:
        _clear_other_body_fields(modifier, {"body_patch"})
        body_patch = modifier.setdefault("body_patch", {})
        _deep_merge(body_patch, parsed_body_patch)
    elif args.form or args.remove_form:
        _clear_other_body_fields(modifier, {"urlencoded_form", "remove_urlencoded_form"})
        _merge_mapping_and_removals(
            modifier, "urlencoded_form", "remove_urlencoded_form", args.form, args.remove_form
        )
    elif args.multipart or args.remove_multipart:
        _clear_other_body_fields(modifier, {"multipart_form", "remove_multipart_form"})
        _merge_mapping_and_removals(
            modifier, "multipart_form", "remove_multipart_form", args.multipart, args.remove_multipart
        )

    save_config(config)


def set_response(args: argparse.Namespace) -> None:
    if args.status_code is not None and not (100 <= args.status_code <= 599):
        raise ValueError(f"status code must be between 100 and 599, got: {args.status_code}")

    if args.body is not None and (args.msg is not None or args.body_patch is not None):
        raise ValueError("cannot combine --body with --msg or --body-patch")

    parsed_body_patch: dict[str, Any] | None = None
    if args.body_patch is not None:
        loaded = json.loads(args.body_patch)
        if not isinstance(loaded, dict):
            raise ValueError("--body-patch must be a JSON object")
        parsed_body_patch = loaded

    parsed_headers = parse_multi_pairs(args.header) if args.header else None

    config = load_config()
    modifier = find_modifier(config, args.match_url)
    if args.body is not None:
        modifier.pop("body_patch", None)
        modifier["body"] = args.body
    elif args.msg is not None or parsed_body_patch is not None:
        modifier.pop("body", None)
        body_patch = modifier.setdefault("body_patch", {})
        if parsed_body_patch is not None:
            _deep_merge(body_patch, parsed_body_patch)
        if args.msg is not None:
            body_patch["msg"] = args.msg
    if parsed_headers is not None:
        modifier.setdefault("headers", {}).update(parsed_headers)
    if args.status_code is not None:
        modifier["status_code"] = args.status_code
    save_config(config)


def clear_config() -> None:
    save_config({"custom_headers": {}, "request_modifiers": [], "response_modifiers": []})


def _has_request_mutation(args: argparse.Namespace) -> bool:
    return any(
        [
            args.method is not None,
            args.http_version is not None,
            args.url is not None,
            args.scheme is not None,
            args.host is not None,
            args.port is not None,
            args.authority is not None,
            args.host_header is not None,
            args.path is not None,
            bool(args.path_components),
            bool(args.path_replace),
            bool(args.query),
            bool(args.remove_query),
            bool(args.header),
            bool(args.remove_header),
            bool(args.cookie),
            bool(args.remove_cookie),
            bool(args.trailer),
            bool(args.remove_trailer),
            args.body is not None,
            args.body_base64 is not None,
            args.body_patch is not None,
            bool(args.form),
            bool(args.remove_form),
            bool(args.multipart),
            bool(args.remove_multipart),
            args.anticache,
            args.anticomp,
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    headers_parser = subparsers.add_parser("headers", help="set global request headers")
    headers_parser.add_argument("pairs", nargs="+", metavar="NAME=VALUE")

    request_parser = subparsers.add_parser("request", help="set a request modifier")
    request_parser.add_argument("--match-url", action="append", required=True)
    request_parser.add_argument("--match-method", action="append")
    request_parser.add_argument("--method")
    request_parser.add_argument("--http-version")
    request_parser.add_argument("--url")
    request_parser.add_argument("--scheme")
    request_parser.add_argument("--host")
    request_parser.add_argument("--port", type=int)
    request_parser.add_argument("--authority")
    request_parser.add_argument("--host-header")
    request_parser.add_argument("--path")
    request_parser.add_argument("--path-component", action="append", dest="path_components")
    request_parser.add_argument("--path-replace", action="append", metavar="OLD=NEW")
    request_parser.add_argument("--query", action="append", metavar="KEY=VALUE")
    request_parser.add_argument("--remove-query", action="append", metavar="KEY")
    request_parser.add_argument("--header", action="append", metavar="NAME=VALUE")
    request_parser.add_argument("--remove-header", action="append", metavar="NAME")
    request_parser.add_argument("--cookie", action="append", metavar="NAME=VALUE")
    request_parser.add_argument("--remove-cookie", action="append", metavar="NAME")
    request_parser.add_argument("--trailer", action="append", metavar="NAME=VALUE")
    request_parser.add_argument("--remove-trailer", action="append", metavar="NAME")
    request_parser.add_argument("--body")
    request_parser.add_argument("--body-base64")
    request_parser.add_argument("--body-patch", metavar="JSON")
    request_parser.add_argument("--form", action="append", metavar="KEY=VALUE")
    request_parser.add_argument("--remove-form", action="append", metavar="KEY")
    request_parser.add_argument("--multipart", action="append", metavar="KEY=VALUE")
    request_parser.add_argument("--remove-multipart", action="append", metavar="KEY")
    request_parser.add_argument("--anticache", action="store_true")
    request_parser.add_argument("--anticomp", action="store_true")

    response_parser = subparsers.add_parser("response", help="set a response modifier")
    response_parser.add_argument("--match-url", action="append", required=True)
    response_parser.add_argument("--msg")
    response_parser.add_argument("--body-patch", metavar="JSON")
    response_parser.add_argument("--body")
    response_parser.add_argument("--header", action="append", metavar="NAME=VALUE")
    response_parser.add_argument("--status-code", type=int)

    subparsers.add_parser("show", help="print current configuration")
    subparsers.add_parser("clear", help="clear headers, request modifiers, and response modifiers")
    args = parser.parse_args()

    if args.command == "headers":
        set_headers(args.pairs)
    elif args.command == "request":
        if not _has_request_mutation(args):
            parser.error("request requires at least one modification option")
        set_request(args)
    elif args.command == "response":
        if (
            args.body is None
            and args.msg is None
            and args.body_patch is None
            and not args.header
            and args.status_code is None
        ):
            parser.error("response requires --body, --body-patch, --msg, --header, or --status-code")
        set_response(args)
    elif args.command == "show":
        print(json.dumps(load_config(), ensure_ascii=False, indent=2))
    elif args.command == "clear":
        clear_config()


if __name__ == "__main__":
    main()
