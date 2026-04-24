from __future__ import annotations

import urllib.request


def main() -> None:
    request = urllib.request.Request("http://localhost:8000/demo/seed", data=b"{}", method="POST")
    with urllib.request.urlopen(request) as response:
        print(response.read().decode())


if __name__ == "__main__":
    main()

