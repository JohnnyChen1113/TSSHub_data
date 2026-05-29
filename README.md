# TSSHub Data

Public release assets and manifests for processed TSSHub data.

This repository is intentionally separate from the private TSSHub website
source code. GitHub Actions in this repository publish BigWig files from the
self-hosted runner data directory into public GitHub Releases.

Release tags follow this pattern:

```text
{species_id}-{assembly}-{bioproject}-tssr-v1
```

Each release contains:

- `*.BigWig` TSSr signal tracks.
- `manifest.json` with track metadata and public download URLs.
- `checksums.sha256` for asset verification.

