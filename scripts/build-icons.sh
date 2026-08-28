#!/usr/bin/env bash
# Rebuild every shipped icon from the design sources in design/.
#
# The PNGs in icons/ were originally produced by hand with ad-hoc headless
# Chrome commands, which meant editing a source SVG left no way to regenerate
# them. build-favicon.py depends on those PNGs, so the pipeline was only half
# reproducible: the .ico could be rebuilt but its inputs could not.
#
# Chrome is the renderer because it is the same engine that displays the icons,
# so what ships is what a browser draws. Any SVG rasteriser would do; this one
# needs no extra install on a machine that already has Chrome.
set -euo pipefail

cd "$(dirname "$0")/.."

# --- locate a Chrome ------------------------------------------------------
CHROME="${CHROME:-}"
if [ -z "$CHROME" ]; then
  for c in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    google-chrome google-chrome-stable chromium chromium-browser
  do
    if [ -x "$c" ] || command -v "$c" >/dev/null 2>&1; then CHROME="$c"; break; fi
  done
fi
if [ -z "$CHROME" ]; then
  echo "No Chrome or Chromium found. Set CHROME=/path/to/chrome and re-run." >&2
  exit 1
fi
# Validate whatever we ended up with, including an explicit CHROME= that points
# nowhere -- otherwise the first render fails with a rasteriser error instead of
# saying the browser is missing.
if ! "$CHROME" --version >/dev/null 2>&1; then
  echo "Cannot run '$CHROME'. Set CHROME=/path/to/chrome to a working browser." >&2
  exit 1
fi
echo "Renderer: $("$CHROME" --version 2>/dev/null)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# render <source.svg> <size> <output.png>
render() {
  local src="$1" size="$2" out="$3"
  # An <img> sized exactly to the viewport, so the screenshot is the artwork
  # and nothing else. The sources are fully opaque, which keeps the output
  # 8-bit RGB -- build-favicon.py reads that format.
  cat > "$TMP/page.html" <<HTML
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{margin:0;padding:0}
html,body{width:${size}px;height:${size}px;overflow:hidden}
img{width:${size}px;height:${size}px;display:block}
</style></head><body><img src="file://$PWD/$src"></body></html>
HTML
  "$CHROME" --headless --disable-gpu --no-sandbox --force-device-scale-factor=1 \
            --hide-scrollbars --virtual-time-budget=3000 \
            --screenshot="$out" --window-size="${size},${size}" \
            "file://$TMP/page.html" >/dev/null 2>&1
  [ -s "$out" ] || { echo "  FAILED to render $out" >&2; exit 1; }
  printf '  %-32s %sx%s  from %s\n' "$out" "$size" "$size" "$src"
}

echo "Rendering icons..."
# Small tier: one lit chip, for sizes where the full track would be mush.
for s in 16 32 48; do render design/icon-small.svg "$s" "icons/favicon-$s.png"; done

# Large tier: the full round track.
for s in 64 96 128 192 256 512 1024; do render design/icon.svg "$s" "icons/icon-$s.png"; done

# Rendered at 180 rather than copied, so no two shipped files are identical.
render design/icon.svg 180 icons/apple-touch-icon.png

# Android crops hard, so this source insets the artwork into the safe area.
render design/icon-maskable.svg 512 icons/icon-maskable-512.png

echo "Rebuilding favicon.ico from the small tier..."
python3 scripts/build-favicon.py

echo "Verifying..."
python3 .github/scripts/check-icons.py
