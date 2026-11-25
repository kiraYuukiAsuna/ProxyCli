#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash ./scripts/start_proxy.sh [PORT] [OPTIONS]

Options:
  -p, --port PORT        Proxy listen port (1-65535, default: 8080)
  --web                  Start Web UI to inspect requests and responses
  --web-port PORT        Web UI listen port (1-65535, default: 8081; implies --web)
  --flow-detail LEVEL    Print traffic detail in terminal (0-4, default: 0)
                           0: quiet  1: summary  2: +headers
                           3: +truncated body    4: +full body
  -h, --help             Show this help message
EOF
}

validate_port() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9]{1,5}$ ]] || (( 10#$value < 1 || 10#$value > 65535 )); then
    echo "$label must be an integer from 1 to 65535." >&2
    exit 2
  fi
}

toolkit_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
proxy_port="8080"
port_set=0
web_mode=0
web_port="8081"
flow_detail="0"
flow_detail_set=0

while (( $# > 0 )); do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -p|--port)
      if (( $# < 2 )); then
        echo "Missing value for $1." >&2
        exit 2
      fi
      if (( port_set )); then
        echo 'Port was specified more than once.' >&2
        exit 2
      fi
      proxy_port="$2"
      port_set=1
      shift 2
      ;;
    --port=*)
      if (( port_set )); then
        echo 'Port was specified more than once.' >&2
        exit 2
      fi
      proxy_port="${1#*=}"
      port_set=1
      shift
      ;;
    --web)
      web_mode=1
      shift
      ;;
    --web-port)
      if (( $# < 2 )); then
        echo "Missing value for $1." >&2
        exit 2
      fi
      web_mode=1
      web_port="$2"
      shift 2
      ;;
    --web-port=*)
      web_mode=1
      web_port="${1#*=}"
      shift
      ;;
    --flow-detail)
      if (( $# < 2 )); then
        echo "Missing value for $1." >&2
        exit 2
      fi
      flow_detail="$2"
      flow_detail_set=1
      shift 2
      ;;
    --flow-detail=*)
      flow_detail="${1#*=}"
      flow_detail_set=1
      shift
      ;;
    -*)
      echo "Unknown option: $1 (use --help for usage)" >&2
      exit 2
      ;;
    *)
      if (( port_set )); then
        echo "Unexpected argument: $1 (use --help for usage)" >&2
        exit 2
      fi
      proxy_port="$1"
      port_set=1
      shift
      ;;
  esac
done

validate_port "Port" "$proxy_port"
if (( web_mode )); then
  validate_port "Web port" "$web_port"
  if (( flow_detail_set )); then
    echo '--flow-detail cannot be used together with --web.' >&2
    exit 2
  fi
  if (( 10#$web_port == 10#$proxy_port )); then
    echo 'Web port must be different from proxy port.' >&2
    exit 2
  fi
  command -v mitmweb >/dev/null 2>&1 || { echo 'Install mitmproxy and add mitmweb to PATH.' >&2; exit 1; }
else
  if [[ ! "$flow_detail" =~ ^[0-4]$ ]]; then
    echo 'Flow detail must be an integer from 0 to 4.' >&2
    exit 2
  fi
  command -v mitmdump >/dev/null 2>&1 || { echo 'Install mitmproxy and add mitmdump to PATH.' >&2; exit 1; }
fi

umask 077
proxy_ca_dir="$HOME/.http-proxy-toolkit/mitmproxy"
mkdir -p "$proxy_ca_dir"
addon="$toolkit_dir/assets/http_proxy/add_header.py"

echo "Proxy: http://127.0.0.1:$proxy_port (foreground; Ctrl+C to stop)"
if (( web_mode )); then
  echo "Web UI: http://127.0.0.1:$web_port (open the URL printed by mitmweb below)"
elif (( flow_detail > 0 )); then
  echo "Flow detail: $flow_detail"
fi
echo "CA: $proxy_ca_dir/mitmproxy-ca-cert.pem"
echo "In your client terminal: source ./scripts/proxy_env.sh $proxy_port"
echo 'Disable proxy: source ./scripts/proxy_env.sh off'

if (( web_mode )); then
  exec mitmweb --listen-host 127.0.0.1 --listen-port "$proxy_port" \
    --web-host 127.0.0.1 --web-port "$web_port" \
    --set "confdir=$proxy_ca_dir" \
    -s "$addon"
else
  exec mitmdump --listen-host 127.0.0.1 --listen-port "$proxy_port" \
    --set "confdir=$proxy_ca_dir" --flow-detail "$flow_detail" \
    -s "$addon"
fi
