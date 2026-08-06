#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

"$root/scripts/vendor_leaflet.sh"
uv run "$root/scripts/build_data.py" "$@"
