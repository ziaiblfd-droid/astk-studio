#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${HOME}/.local/bin"
RPM_PATH="${1:-/tmp/cloudflared.rpm}"

mkdir -p "$INSTALL_DIR" /tmp/cloudflared-unpack
rm -rf /tmp/cloudflared-unpack/*
(
  cd /tmp/cloudflared-unpack
  rpm2cpio "$RPM_PATH" | cpio -idm --quiet
  binary_path="$(find . -name cloudflared -type f -print -quit)"
  test -n "$binary_path"
  install -m 755 "$binary_path" "$INSTALL_DIR/cloudflared"
)

"$INSTALL_DIR/cloudflared" --version
