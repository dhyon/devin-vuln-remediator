from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a signed demo GitHub label webhook.")
    parser.add_argument("--url", default="http://localhost:8000/webhooks/github")
    parser.add_argument("--secret", default="demo-secret")
    parser.add_argument("--repo", default="demo/superset")
    parser.add_argument("--issue-number", type=int, default=999)
    parser.add_argument("--label", default="devin-remediate")
    args = parser.parse_args()

    payload = {
        "action": "labeled",
        "label": {"name": args.label},
        "repository": {"full_name": args.repo},
        "issue": {
            "number": args.issue_number,
            "title": "Demo scanner finding",
            "body": "A signed simulated webhook should create a Devin remediation session.",
            "html_url": f"https://github.com/{args.repo}/issues/{args.issue_number}",
        },
    }
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )
    with urllib.request.urlopen(request) as response:
        print(response.read().decode())


if __name__ == "__main__":
    main()

