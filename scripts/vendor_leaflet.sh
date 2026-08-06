#!/bin/sh
set -eu

LEAFLET_VERSION=1.9.4

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dest="$root/web/vendor/leaflet"
base="https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist"

for asset in \
    leaflet.js \
    leaflet.css \
    images/marker-icon.png \
    images/marker-icon-2x.png \
    images/marker-shadow.png \
    images/layers.png \
    images/layers-2x.png
do
    echo "  $asset"
    curl -fsSL --create-dirs -o "$dest/$asset" "$base/$asset"
done

echo "Vendored Leaflet $LEAFLET_VERSION into web/vendor/leaflet"
