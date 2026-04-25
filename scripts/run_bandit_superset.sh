#!/usr/bin/env bash
set -euo pipefail

SUPERSET_REPO="${1:-${SUPERSET_REPO_PATH:-../superset}}"
OUTPUT="${OUTPUT:-demo/bandit-results.json}"

if [[ ! -d "$SUPERSET_REPO" ]]; then
  echo "Superset repo path not found: $SUPERSET_REPO"
  echo "Usage: SUPERSET_REPO_PATH=/path/to/superset $0"
  echo "   or: $0 /path/to/superset"
  exit 2
fi

if ! python -m bandit --version >/dev/null 2>&1; then
  echo "Bandit is not installed."
  echo "Install it with: python -m pip install bandit"
  exit 2
fi

mkdir -p "$(dirname "$OUTPUT")"

set +e
python -m bandit -r "$SUPERSET_REPO" -f json -o "$OUTPUT"
bandit_status=$?
set -e

if [[ ! -s "$OUTPUT" ]]; then
  echo '{"results":[],"errors":[]}' > "$OUTPUT"
fi

finding_count="$(python - "$OUTPUT" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
print(len(data.get("results", [])))
PY
)"

echo "Bandit scan complete. Findings: $finding_count"
echo "Raw JSON written to: $OUTPUT"
if [[ "$bandit_status" -ne 0 && "$finding_count" -gt 0 ]]; then
  echo "Bandit returned a non-zero status because findings were detected; continuing as expected."
elif [[ "$bandit_status" -ne 0 ]]; then
  echo "Bandit returned status $bandit_status. Inspect $OUTPUT for errors."
fi
echo "Next: curate 5 to 8 real findings into demo/findings.json, then run:"
echo "  python scripts/create_github_issues_from_findings.py --dry-run"
