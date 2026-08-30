#!/usr/bin/env bash
# Stage exactly the files the site serves into _site/.
#
# An include list rather than an exclude list: the legacy branch build published
# the whole repository, so package.json, the test harness and the data generator
# were all reachable over HTTP. Nothing here is secret -- the repo is public --
# but serving source from the site is sloppy and it is not what a deploy is for.
#
# check-references.py is then run against the staged tree, so a file the page
# needs but this script forgot fails the build instead of 404ing in production.
set -euo pipefail

OUT="${1:-_site}"
rm -rf "$OUT"
mkdir -p "$OUT"

FILES=(index.html winners.html styles.css common.js app.js winners.js
       feed.xml events.json upcoming.json og.png
       favicon.ico site.webmanifest CNAME robots.txt)
# events/ is the archive: one directory per event, fetched on demand rather than
# all at once. Staged whole, because which event a reader opens is their choice
# and every one of them has to be there when they make it.
DIRS=(icons events)

for f in "${FILES[@]}"; do
  [ -f "$f" ] || { echo "  MISSING $f"; exit 1; }
  cp "$f" "$OUT/"
  echo "  staged  $f"
done
for d in "${DIRS[@]}"; do
  [ -d "$d" ] || { echo "  MISSING $d/"; exit 1; }
  cp -R "$d" "$OUT/"
  echo "  staged  $d/ ($(find "$d" -type f | wc -l | tr -d ' ') files)"
done

echo "  total   $(find "$OUT" -type f | wc -l | tr -d ' ') files, $(du -sh "$OUT" | cut -f1)"
