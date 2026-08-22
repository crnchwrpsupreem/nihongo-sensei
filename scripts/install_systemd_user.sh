#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
INTERVAL="3h"

if [[ "${1:-}" == "--interval" ]]; then
  INTERVAL="${2:-}"
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--interval 3h]" >&2
  exit 2
fi

if [[ ! "${INTERVAL}" =~ ^[0-9]+(s|min|h|d|w)$ ]]; then
  echo "Invalid interval '${INTERVAL}'. Examples: 30min, 3h, 1d." >&2
  exit 2
fi

CONFIG_DIR="${HOME}/.config/nihongo-sensei"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
mkdir -p "${CONFIG_DIR}" "${SYSTEMD_DIR}"

if [[ ! -f "${CONFIG_DIR}/config.env" ]]; then
  cp "${REPO_DIR}/config.env.example" "${CONFIG_DIR}/config.env"
  chmod 600 "${CONFIG_DIR}/config.env"
  echo "Created ${CONFIG_DIR}/config.env; review it before the first scheduled run."
fi

sed "s|@REPO_DIR@|${REPO_DIR}|g" \
  "${REPO_DIR}/systemd/nihongo-sensei.service.in" \
  > "${SYSTEMD_DIR}/nihongo-sensei.service"
sed "s|@INTERVAL@|${INTERVAL}|g" \
  "${REPO_DIR}/systemd/nihongo-sensei.timer.in" \
  > "${SYSTEMD_DIR}/nihongo-sensei.timer"

systemctl --user daemon-reload
systemctl --user enable --now nihongo-sensei.timer
echo "Installed Nihongo Sensei user timer with interval ${INTERVAL}."
echo "Run once now with: systemctl --user start nihongo-sensei.service"
