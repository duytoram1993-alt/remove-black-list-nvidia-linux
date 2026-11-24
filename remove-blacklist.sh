#!/usr/bin/env bash
# ==============================================================================
# remove-blacklist.sh - Wrapper for patch_nvidia_blacklist.py
#
# Usage:
#   bash remove-blacklist.sh check [--ko /path/to/nvidia.ko*]
#   sudo bash remove-blacklist.sh apply [--ko /path/to/nvidia.ko*]
#   sudo bash remove-blacklist.sh revert [--ko /path/to/nvidia.ko*]
#   sudo bash remove-blacklist.sh restore-orig [--ko /path/to/nvidia.ko*]
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHER="${SCRIPT_DIR}/patch_nvidia_blacklist.py"

ACTION="${1:-}"
case "${ACTION}" in
  check|apply|revert|restore-orig)
    shift
    exec python3 "${PATCHER}" "${ACTION}" "$@"
    ;;
  *)
    echo "Usage: [sudo] bash $0 {check|apply|revert|restore-orig} [--ko /path/to/nvidia.ko*]"
    exit 2
    ;;
esac
