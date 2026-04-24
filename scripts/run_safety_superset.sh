#!/usr/bin/env bash
set -euo pipefail

SUPERSET_REPO="${1:-${SUPSERSET_REPO_PATH:-${SUPERSET_REPO_PATH:-../superset}}}"
OUTPUT="${OUTPUT:-demo/dependency-results.json}"

if [[ ! -d "$SUPERSET_REPO" ]]; then
  echo "Superset repo path not found: $SUPERSET_REPO"
  echo "Usage: SUPSERSET_REPO_PATH=/path/to/superset $0"
  echo "   or: $0 /path/to/superset"
  exit 2
fi

mkdir -p "$(dirname "$OUTPUT")"

if python -m pip_audit --version >/dev/null 2>&1; then
  echo "Running pip-audit against $SUPERSET_REPO"
  set +e
  python -m pip_audit --path "$SUPERSET_REPO" --format json --output "$OUTPUT"
  status=$?
  set -e
  tool="pip-audit"
elif python -m safety --version >/dev/null 2>&1; then
  echo "Running Safety against $SUPERSET_REPO"
  set +e
  python -m safety scan --target "$SUPERSET_REPO" --output json > "$OUTPUT"
  status=$?
  set -e
  tool="safety"
else
  echo "Neither pip-audit nor Safety is installed; no dependency scan was run."
  echo "Install one of them:"
  echo "  python -m pip install pip-audit"
  echo "  python -m pip install safety"
  echo "This script does not fabricate dependency findings."
  exit 2
fi

if [[ ! -s "$OUTPUT" ]]; then
  echo '{}' > "$OUTPUT"
fi

finding_count="$(python - "$OUTPUT" "$tool" <<'PY'
import json
import sys
path, tool = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
if tool == "pip-audit":
    deps = data.get("dependencies", []) if isinstance(data, dict) else []
    print(sum(len(dep.get("vulns", [])) for dep in deps))
else:
    if isinstance(data, dict):
        print(len(data.get("vulnerabilities", data.get("results", []))))
    elif isinstance(data, list):
        print(len(data))
    else:
        print(0)
PY
)"

echo "$tool scan complete. Findings: $finding_count"
echo "Raw JSON written to: $OUTPUT"
if [[ "$status" -ne 0 && "$finding_count" -gt 0 ]]; then
  echo "$tool returned a non-zero status because findings were detected; continuing as expected."
elif [[ "$status" -ne 0 ]]; then
  echo "$tool returned status $status. Inspect $OUTPUT for details."
fi
echo "Next: curate real dependency findings into demo/findings.json, then run:"
echo "  python scripts/create_github_issues_from_findings.py --dry-run"
