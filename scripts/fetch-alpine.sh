#!/usr/bin/env bash
# Vendor Alpine.js at build time so it is self-hosted (no third-party CDN at
# runtime - keeps the privacy policy's "no other third-party services" claim
# true) without committing a minified blob to git. Pinned + integrity-checked.
set -euo pipefail

VERSION="3.14.9"
SHA256="3ed1eed252488921df65e363d6715deb04d7f92aaedb9e52199fdf73cb1e0ad3"
URL="https://cdn.jsdelivr.net/npm/alpinejs@${VERSION}/dist/cdn.min.js"
DEST="$(cd "$(dirname "$0")/.." && pwd)/assets/js/alpine.min.js"

verify() { echo "${SHA256}  ${DEST}" | sha256sum --check --status; }

if [[ -f "$DEST" ]] && verify; then
	exit 0
fi

echo "Fetching Alpine.js ${VERSION} -> assets/js/alpine.min.js"
mkdir -p "$(dirname "$DEST")"
curl -fsSL "$URL" -o "$DEST"

if ! verify; then
	echo "ERROR: Alpine.js ${VERSION} sha256 mismatch - refusing to use it." >&2
	rm -f "$DEST"
	exit 1
fi
