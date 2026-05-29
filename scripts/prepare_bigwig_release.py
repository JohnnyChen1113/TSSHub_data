#!/usr/bin/env python3
"""Prepare a GitHub Release manifest for TSSHub TSSr BigWig files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


BIGWIG_SUFFIXES = (".bigwig", ".bw")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_strand(filename: str) -> str | None:
    lower = filename.lower()
    if ".plus." in lower or lower.endswith(".plus.bigwig") or lower.endswith(".plus.bw"):
        return "plus"
    if ".minus." in lower or lower.endswith(".minus.bigwig") or lower.endswith(".minus.bw"):
        return "minus"
    return None


def infer_run_id(path: Path, tssr_root: Path) -> str:
    try:
        rel = path.relative_to(tssr_root)
        if len(rel.parts) > 1:
            return rel.parts[0]
    except ValueError:
        pass
    return path.name.split(".", 1)[0]


def find_bigwigs(tssr_root: Path) -> list[Path]:
    if not tssr_root.exists():
        return []
    files = [
        path
        for path in tssr_root.rglob("*")
        if path.is_file() and path.name.lower().endswith(BIGWIG_SUFFIXES)
    ]
    return sorted(files, key=lambda p: (infer_run_id(p, tssr_root), p.name.lower()))


def public_release_url(repository: str, tag: str, filename: str) -> str:
    return (
        f"https://github.com/{repository}/releases/download/"
        f"{quote(tag, safe='')}/{quote(filename, safe='')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--species-id", required=True)
    parser.add_argument("--assembly", required=True)
    parser.add_argument("--bioproject", required=True)
    parser.add_argument("--repository", required=True, help="owner/repo")
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    data_root = Path(args.data_root).expanduser().resolve()
    tssr_root = data_root / args.species_id / "bioprojects" / args.bioproject / "tssr"
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    bigwigs = find_bigwigs(tssr_root)
    if not bigwigs:
        raise SystemExit(f"No BigWig files found under {tssr_root}")

    tracks = []
    checksum_lines = []
    for path in bigwigs:
        filename = path.name
        file_hash = sha256_file(path)
        checksum_lines.append(f"{file_hash}  {filename}\n")
        tracks.append(
            {
                "run_id": infer_run_id(path, tssr_root),
                "strand": infer_strand(filename),
                "filename": filename,
                "local_path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": file_hash,
                "url": public_release_url(args.repository, args.release_tag, filename),
            }
        )

    manifest = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "repository": args.repository,
        "release_tag": args.release_tag,
        "species_id": args.species_id,
        "assembly": args.assembly,
        "bioproject": args.bioproject,
        "data_root": str(data_root),
        "tssr_root": str(tssr_root),
        "track_count": len(tracks),
        "tracks": tracks,
    }

    manifest_path = output_dir / "manifest.json"
    checksums_path = output_dir / "checksums.sha256"
    body_path = output_dir / "release_body.md"
    assets_path = output_dir / "assets.nul"

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    checksums_path.write_text("".join(checksum_lines))
    body_path.write_text(
        "\n".join(
            [
                f"Processed TSSr BigWig tracks for `{args.species_id}` `{args.assembly}` `{args.bioproject}`.",
                "",
                f"- Tracks: {len(tracks)}",
                f"- Generated: {manifest['generated_at']}",
                f"- Source: `{tssr_root}`",
                "",
                "Use `manifest.json` to discover track URLs and checksums.",
                "",
            ]
        )
    )

    with assets_path.open("wb") as handle:
        for path in bigwigs:
            handle.write(os.fsencode(str(path)))
            handle.write(b"\0")
        for path in (manifest_path, checksums_path):
            handle.write(os.fsencode(str(path)))
            handle.write(b"\0")

    print(json.dumps({"track_count": len(tracks), "manifest": str(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

