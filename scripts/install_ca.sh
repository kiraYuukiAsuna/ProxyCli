#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash ./scripts/install_ca.sh [OPTIONS]

Install or uninstall this toolkit's mitmproxy CA certificate in the OS trust store.

Options:
  --cert PATH    Path to the CA certificate PEM file
                 (default: ~/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem)
  --system       macOS: use System Keychain (with sudo) instead of Login Keychain
  --uninstall    Remove the CA certificate from the OS trust store
  -h, --help     Show this help message
EOF
}

cert_path="$HOME/.http-proxy-toolkit/mitmproxy/mitmproxy-ca-cert.pem"
system_scope=0
uninstall_mode=0

while (( $# > 0 )); do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --cert)
      if (( $# < 2 )); then
        echo "Missing value for $1." >&2
        exit 2
      fi
      cert_path="$2"
      shift 2
      ;;
    --cert=*)
      cert_path="${1#*=}"
      shift
      ;;
    --system)
      system_scope=1
      shift
      ;;
    --uninstall)
      uninstall_mode=1
      shift
      ;;
    *)
      echo "Unknown option: $1 (use --help for usage)" >&2
      exit 2
      ;;
  esac
done

run_privileged() {
  if (( EUID == 0 )); then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Root privileges are required (sudo not found). Re-run as root." >&2
    exit 1
  fi
}

cert_sha1() {
  if command -v openssl >/dev/null 2>&1; then
    openssl x509 -noout -fingerprint -sha1 -in "$1" 2>/dev/null \
      | sed -E 's/^.*=//; s/://g' \
      | tr '[:lower:]' '[:upper:]'
  fi
}

install_or_uninstall_macos() {
  command -v security >/dev/null 2>&1 || { echo 'macOS security command not found.' >&2; exit 1; }
  if [[ ! -f "$cert_path" ]]; then
    echo "CA certificate not found: $cert_path" >&2
    echo 'Start the proxy once first (bash ./scripts/start_proxy.sh) to generate the CA, or pass --cert <PATH>.' >&2
    exit 1
  fi

  local keychain="$HOME/Library/Keychains/login.keychain-db"
  local label="macOS Login Keychain"
  if (( system_scope )); then
    keychain="/Library/Keychains/System.keychain"
    label="macOS System Keychain"
  fi

  if (( uninstall_mode )); then
    local sha1 removed=0
    sha1="$(cert_sha1 "$cert_path" || true)"
    if (( system_scope )); then
      if run_privileged security remove-trusted-cert -d "$cert_path"; then
        removed=1
      fi
      if [[ -n "$sha1" ]] && run_privileged security delete-certificate -Z "$sha1" "$keychain" >/dev/null 2>&1; then
        removed=1
      fi
    else
      if security remove-trusted-cert "$cert_path"; then
        removed=1
      fi
      if [[ -n "$sha1" ]] && security delete-certificate -Z "$sha1" "$keychain" >/dev/null 2>&1; then
        removed=1
      fi
    fi
    if (( ! removed )); then
      echo "Failed to remove CA certificate from $label (not installed or authorization denied)." >&2
      exit 1
    fi
    echo "CA certificate removed from $label: $cert_path"
    return 0
  fi

  if (( system_scope )); then
    run_privileged security add-trusted-cert -d -r trustRoot -k "$keychain" "$cert_path"
  else
    security add-trusted-cert -r trustRoot -k "$keychain" "$cert_path"
  fi
  echo "CA certificate installed in $label: $cert_path"
}

install_or_uninstall_linux() {
  local target_dir=""
  local update_cmd=""
  local update_uninstall_args=()
  local update_install_args=()

  if command -v update-ca-certificates >/dev/null 2>&1 && [[ -d /usr/local/share/ca-certificates ]]; then
    target_dir="/usr/local/share/ca-certificates"
    update_cmd="update-ca-certificates"
    update_uninstall_args=(--fresh)
  elif command -v update-ca-trust >/dev/null 2>&1 && [[ -d /etc/pki/ca-trust/source/anchors ]]; then
    target_dir="/etc/pki/ca-trust/source/anchors"
    update_cmd="update-ca-trust"
    update_install_args=(extract)
    update_uninstall_args=(extract)
  elif command -v update-ca-trust >/dev/null 2>&1 && [[ -d /etc/ca-certificates/trust-source/anchors ]]; then
    target_dir="/etc/ca-certificates/trust-source/anchors"
    update_cmd="update-ca-trust"
  else
    echo "Unsupported Linux CA store. Install this certificate manually: $cert_path" >&2
    exit 1
  fi

  local target="$target_dir/http-proxy-toolkit-mitmproxy.crt"
  local use_sudo=0
  if (( EUID != 0 )) && [[ ! -w "$target_dir" ]]; then
    use_sudo=1
  fi

  run_linux_cmd() {
    if (( use_sudo )); then
      run_privileged "$@"
    else
      "$@"
    fi
  }

  if (( uninstall_mode )); then
    run_linux_cmd rm -f "$target"
    if (( ${#update_uninstall_args[@]} > 0 )); then
      run_linux_cmd "$update_cmd" "${update_uninstall_args[@]}" || run_linux_cmd "$update_cmd"
    else
      run_linux_cmd "$update_cmd"
    fi
    echo "CA certificate removed from system trust store: $target"
    return 0
  fi

  if [[ ! -f "$cert_path" ]]; then
    echo "CA certificate not found: $cert_path" >&2
    echo 'Start the proxy once first (bash ./scripts/start_proxy.sh) to generate the CA, or pass --cert <PATH>.' >&2
    exit 1
  fi

  run_linux_cmd cp "$cert_path" "$target"
  run_linux_cmd chmod 644 "$target"
  if (( ${#update_install_args[@]} > 0 )); then
    run_linux_cmd "$update_cmd" "${update_install_args[@]}"
  else
    run_linux_cmd "$update_cmd"
  fi
  echo "CA certificate installed in system trust store: $target"
}

case "$(uname -s)" in
  Darwin)
    install_or_uninstall_macos
    ;;
  Linux)
    install_or_uninstall_linux
    ;;
  *)
    echo "Unsupported platform ($(uname -s)). Install this certificate manually: $cert_path" >&2
    exit 1
    ;;
esac
