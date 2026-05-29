#!/usr/bin/env python3
"""Create/update a GitHub Release and upload assets using GITHUB_TOKEN."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


API_ROOT = "https://api.github.com"
UPLOAD_HOST = "uploads.github.com"


def token() -> str:
    value = os.environ.get("GITHUB_TOKEN")
    if not value:
        raise SystemExit("GITHUB_TOKEN is required")
    return value


def request_json(method: str, path: str, auth_token: str, payload: dict | None = None):
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {auth_token}",
        "User-Agent": "tsshub-data-release-publisher",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{API_ROOT}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            return response.status, json.loads(body.decode() or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        if exc.code == 404:
            return 404, None
        raise RuntimeError(f"GitHub API {method} {path} failed: HTTP {exc.code}: {body}") from exc


def get_or_create_release(repository: str, tag: str, title: str, body: str, auth_token: str) -> dict:
    status, release = request_json(
        "GET",
        f"/repos/{repository}/releases/tags/{urllib.parse.quote(tag, safe='')}",
        auth_token,
    )
    payload = {"tag_name": tag, "name": title, "body": body, "draft": False, "prerelease": False}
    if status == 404:
        _, created = request_json("POST", f"/repos/{repository}/releases", auth_token, payload)
        return created

    _, updated = request_json("PATCH", f"/repos/{repository}/releases/{release['id']}", auth_token, payload)
    return updated


def list_assets(repository: str, release_id: int, auth_token: str) -> list[dict]:
    assets = []
    page = 1
    while True:
        status, chunk = request_json(
            "GET",
            f"/repos/{repository}/releases/{release_id}/assets?per_page=100&page={page}",
            auth_token,
        )
        if status == 404 or not chunk:
            break
        assets.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return assets


def delete_asset(repository: str, asset_id: int, auth_token: str) -> None:
    request = urllib.request.Request(
        f"{API_ROOT}/repos/{repository}/releases/assets/{asset_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {auth_token}",
            "User-Agent": "tsshub-data-release-publisher",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 204:
                raise RuntimeError(f"delete asset returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"delete asset failed: HTTP {exc.code}: {exc.read().decode()}") from exc


def upload_asset(repository: str, release_id: int, path: Path, auth_token: str) -> dict:
    filename = path.name
    query = urllib.parse.urlencode({"name": filename})
    url_path = f"/repos/{repository}/releases/{release_id}/assets?{query}"
    size = path.stat().st_size

    connection = http.client.HTTPSConnection(UPLOAD_HOST, timeout=300)
    connection.putrequest("POST", url_path)
    connection.putheader("Accept", "application/vnd.github+json")
    connection.putheader("Authorization", f"Bearer {auth_token}")
    connection.putheader("Content-Type", "application/octet-stream")
    connection.putheader("Content-Length", str(size))
    connection.putheader("User-Agent", "tsshub-data-release-publisher")
    connection.putheader("X-GitHub-Api-Version", "2022-11-28")
    connection.endheaders()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            connection.send(chunk)

    response = connection.getresponse()
    body = response.read().decode()
    connection.close()
    if response.status != 201:
        raise RuntimeError(f"upload {filename} failed: HTTP {response.status}: {body}")
    return json.loads(body)


def read_assets(path: Path) -> list[Path]:
    data = path.read_bytes()
    return [Path(os.fsdecode(item)) for item in data.split(b"\0") if item]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="owner/repo")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--assets-nul", required=True)
    parser.add_argument("--clobber", action="store_true")
    args = parser.parse_args()

    auth_token = token()
    body = Path(args.body_file).read_text()
    release = get_or_create_release(args.repository, args.tag, args.title, body, auth_token)
    release_id = release["id"]
    assets = read_assets(Path(args.assets_nul))

    existing = {asset["name"]: asset for asset in list_assets(args.repository, release_id, auth_token)}
    for asset_path in assets:
        if not asset_path.exists():
            raise SystemExit(f"Asset does not exist: {asset_path}")
        if asset_path.name in existing:
            if not args.clobber:
                raise SystemExit(f"Asset already exists and --clobber is not set: {asset_path.name}")
            delete_asset(args.repository, existing[asset_path.name]["id"], auth_token)

        uploaded = upload_asset(args.repository, release_id, asset_path, auth_token)
        print(json.dumps({"uploaded": uploaded["name"], "size": asset_path.stat().st_size}))

    print(json.dumps({"release": release["html_url"], "asset_count": len(assets)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

