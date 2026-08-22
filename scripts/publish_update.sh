#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${NIHONGO_CONFIG_FILE:-${HOME}/.config/nihongo-sensei/config.env}"
NO_SYNC=false
NO_PUSH=false

for argument in "$@"; do
  case "${argument}" in
    --no-sync) NO_SYNC=true ;;
    --no-push) NO_PUSH=true ;;
    *) echo "Unknown argument: ${argument}" >&2; exit 2 ;;
  esac
done

if [[ -f "${CONFIG_FILE}" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${CONFIG_FILE}"
  set +a
fi

PROFILE="${NIHONGO_ANKI_PROFILE:-${HOME}/.local/share/Anki2/User 1}"
DECK_ROOT="${NIHONGO_DECK_ROOT:-日本語}"
REMOTE="${NIHONGO_GIT_REMOTE:-origin}"
BRANCH="${NIHONGO_GIT_BRANCH:-main}"
WORK_DIR="${REPO_DIR}/work/current-session"
PUBLIC_DIR="${REPO_DIR}/tutor-data/current"

mkdir -p "${WORK_DIR}" "${PUBLIC_DIR}"
exec 9>"${REPO_DIR}/work/publisher.lock"
if ! flock -n 9; then
  echo "Another Nihongo Sensei publisher run is active; exiting." >&2
  exit 3
fi

cd "${REPO_DIR}"
export PYTHONDONTWRITEBYTECODE=1

if [[ "${NO_PUSH}" == false ]]; then
  git pull --rebase --autostash "${REMOTE}" "${BRANCH}"
fi

if [[ "${NO_SYNC}" == false ]]; then
  python3 scripts/sync_anki.py
fi

python3 .agents/skills/nihongo-sensei/scripts/build_session.py \
  --profile "${PROFILE}" \
  --deck-root "${DECK_ROOT}" \
  --inclusion-mode historical \
  --output-dir "${WORK_DIR}"

python3 scripts/export_tutor_bundle.py \
  --corpus "${WORK_DIR}/corpus.json" \
  --output "${PUBLIC_DIR}"

python3 -m unittest discover -s tests -v

if [[ "${NO_PUSH}" == true ]]; then
  echo "Tutor bundle generated locally; --no-push requested."
  exit 0
fi

git add tutor-data/current
if git diff --cached --quiet; then
  echo "Tutor data is already current; nothing to publish."
  exit 0
fi

git commit -m "Update public tutor context $(date --iso-8601=seconds)"
git push "${REMOTE}" "${BRANCH}"
echo "Published fresh tutor context to ${REMOTE}/${BRANCH}."
