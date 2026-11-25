# Source this file from Bash or Zsh: source ./scripts/proxy_env.sh [8080|off]
# Do not set shell options here: this file runs inside the caller's shell.
_http_proxy_env() {
  if (( $# > 1 )); then
    echo 'Usage: source ./scripts/proxy_env.sh [PORT|off]' >&2
    return 2
  fi
  local proxy_port="${1:-8080}"
  local proxy_ca="$HOME/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem"
  if [[ "$proxy_port" == "-h" || "$proxy_port" == "--help" ]]; then
    echo 'Usage: source ./scripts/proxy_env.sh [PORT|off]'
    return 0
  fi
  if [[ "$proxy_port" == off ]]; then
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY \
      SSL_CERT_FILE REQUESTS_CA_BUNDLE CURL_CA_BUNDLE NODE_EXTRA_CA_CERTS
    echo 'HTTP/HTTPS proxy disabled in this terminal.'
    return 0
  fi
  if [[ ! "$proxy_port" =~ ^[0-9]{1,5}$ ]] || (( 10#$proxy_port < 1 || 10#$proxy_port > 65535 )); then
    echo 'Port must be an integer from 1 to 65535.' >&2
    return 2
  fi
  if [[ ! -f "$proxy_ca" ]]; then
    echo "CA not found: $proxy_ca. Start the proxy first." >&2
    return 1
  fi
  local proxy_url="http://127.0.0.1:$proxy_port"
  export http_proxy="$proxy_url"
  export https_proxy="$proxy_url"
  export HTTP_PROXY="$proxy_url"
  export HTTPS_PROXY="$proxy_url"
  export SSL_CERT_FILE="$proxy_ca"
  export REQUESTS_CA_BUNDLE="$proxy_ca"
  export CURL_CA_BUNDLE="$proxy_ca"
  export NODE_EXTRA_CA_CERTS="$proxy_ca"
  echo "HTTP/HTTPS proxy: $proxy_url"
  echo "CA: $proxy_ca"
}
_http_proxy_env "$@"
