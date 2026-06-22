#!/usr/bin/env bash
# Vendor third-party JS at build time so it is self-hosted (no third-party CDN at
# runtime - keeps the privacy policy's "no other third-party services" claim true)
# without committing minified blobs to git (the hooks linter rejects them).
# Each lib is pinned and sha256-verified. Outputs are gitignored.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# name | url | dest (relative to repo root) | sha256
VENDORS=(
	"Alpine.js 3.14.9|https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js|assets/js/alpine.min.js|3ed1eed252488921df65e363d6715deb04d7f92aaedb9e52199fdf73cb1e0ad3"
	"Chart.js 4.4.7|https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js|assets/js/chart.min.js|206b6e8bb00fc7bba2c7ee80ca41db3e9e05ba7be0aa35abeba9cfd5357f5d0e"
)

for entry in "${VENDORS[@]}"; do
	IFS='|' read -r name url rel sha <<<"$entry"
	dest="$ROOT/$rel"
	if [[ -f "$dest" ]] && echo "${sha}  ${dest}" | sha256sum --check --status; then
		continue
	fi
	echo "Fetching ${name} -> ${rel}"
	mkdir -p "$(dirname "$dest")"
	curl -fsSL "$url" -o "$dest"
	if ! echo "${sha}  ${dest}" | sha256sum --check --status; then
		echo "ERROR: ${name} sha256 mismatch - refusing to use it." >&2
		rm -f "$dest"
		exit 1
	fi
done
