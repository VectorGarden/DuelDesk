#!/usr/bin/env bash
# Verify the live site is serving what we just uploaded.
#
# Deploys were silently broken once for two merges: CI stayed green because it
# validated the code, and nothing ever asked whether the code reached
# production. This closes that loop.
#
# Every check runs before the script exits, so a bad deploy reports the whole
# picture rather than one symptom at a time.
set -uo pipefail

BASE="${1:-https://dueldesk.reizu.dev}"
BASE="${BASE%/}"
SITE="${2:-_site}"
MAX_DATA_AGE_MIN="${MAX_DATA_AGE_MIN:-30}"
ATTEMPTS="${ATTEMPTS:-10}"

[ -f "$SITE/index.html" ] || { echo "No $SITE/index.html to compare against" >&2; exit 1; }

FAILED=0
fail() { echo "  FAIL  $*"; FAILED=1; }

# Cache-busted, so a CDN edge cannot answer on the origin's behalf.
fetch() { curl -fsSL -m 20 -H 'Cache-Control: no-cache' "$1?_=$(date +%s)$RANDOM"; }
status() { curl -sS -o /dev/null -m 20 -w '%{http_code}' "$1" 2>/dev/null || echo 000; }

EXPECTED="$(shasum -a 256 "$SITE/index.html" | cut -d' ' -f1)"
echo "Smoke testing $BASE"
echo "  expecting index.html sha256 ${EXPECTED:0:16}..."

# --- 1. the page we built is the page being served ---------------------------
# Pages propagates asynchronously, so retry rather than assuming it is instant.
for i in $(seq 1 "$ATTEMPTS"); do
  served="$(fetch "$BASE/" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"
  if [ "$served" = "$EXPECTED" ]; then
    echo "  ok    index.html matches the uploaded artifact (attempt $i)"
    break
  fi
  if [ "$i" -eq "$ATTEMPTS" ]; then
    fail "after $ATTEMPTS attempts the site serves ${served:0:16}..., expected ${EXPECTED:0:16}..."
  else
    sleep 10
  fi
done

# --- 1b. and so are the files it cannot run without --------------------------
# index.html is markup now; the behaviour is in app.js and the look in
# styles.css. A deploy that shipped a stale app.js would serve a page that
# renders and then does nothing, and the hash above would call it correct.
for asset in styles.css app.js; do
  want="$(shasum -a 256 "$SITE/$asset" | cut -d' ' -f1)"
  got="$(fetch "$BASE/$asset" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"
  if [ "$want" = "$got" ]; then
    echo "  ok    $asset matches the uploaded artifact"
  else
    fail "$asset served ${got:0:16}..., expected ${want:0:16}..."
  fi
done

# --- 2. the data we built is the data being served ---------------------------
# Hash-compared like index.html, because that holds however the data was made.
# The age check below cannot do this job alone: real coverage is stamped with the
# event's own times, so a finished event is legitimately days old.
# The manifest first, then the event it names newest -- which is the pair the
# page loads on a cold visit. Checking only the manifest would pass a deploy
# that shipped an index to files it forgot to stage.
if ! fetch "$BASE/events.json" > /tmp/smoke-events.json 2>/dev/null; then
  fail "could not fetch events.json"
fi
want="$(shasum -a 256 "$SITE/events.json" | cut -d' ' -f1)"
got="$(shasum -a 256 /tmp/smoke-events.json | cut -d' ' -f1)"
[ "$want" = "$got" ] \
  && echo "  ok    events.json matches the uploaded artifact" \
  || fail "events.json served ${got:0:16}..., expected ${want:0:16}..."

NEWEST="$(python3 -c '
import json; print(json.load(open("/tmp/smoke-events.json"))["events"][0]["path"])')"
echo "  ..    newest event is $NEWEST"

if fetch "$BASE/$NEWEST" > /tmp/smoke-rounds.json 2>/dev/null; then
  want="$(shasum -a 256 "$SITE/$NEWEST" | cut -d' ' -f1)"
  got="$(shasum -a 256 /tmp/smoke-rounds.json | cut -d' ' -f1)"
  if [ "$want" = "$got" ]; then
    echo "  ok    $NEWEST matches the uploaded artifact"
  else
    fail "$NEWEST served ${got:0:16}..., expected ${want:0:16}..."
  fi

  # The freshness rule applies only to the simulation, which is regenerated on
  # every deploy and so has no excuse for being stale. A timestamp in the future
  # is wrong either way.
  python3 -c '
import json, sys, datetime as dt
limit = float(sys.argv[1])
d = json.load(open("/tmp/smoke-rounds.json"))
u = dt.datetime.fromisoformat(str(d["updated"]).replace("Z", "+00:00"))
if not u.tzinfo:
    u = u.replace(tzinfo=dt.timezone.utc)
age = (dt.datetime.now(dt.timezone.utc) - u).total_seconds() / 60
live = [r["label"] for f in d["formats"] for r in f["rounds"] if r["state"] == "live"]
if "sample" not in d:
    print("  the served data does not say whether it is sample or real coverage")
    sys.exit(1)
sample = d["sample"] is True
kind = "sample" if sample else "coverage"
if age < -1:
    print(f"  {kind} data is stamped {abs(age):.0f} min in the FUTURE; the timestamp is wrong")
    sys.exit(1)
if sample and age > limit:
    print(f"  sample data is {age:.0f} min old (limit {limit:.0f}); this deploy did not regenerate it")
    sys.exit(1)
print(f"  ok    {kind} data is {age:.0f} min old, live round {live or chr(40)+chr(41)}")
' "$MAX_DATA_AGE_MIN" || fail "the served event's timestamp is wrong"
else
  fail "could not fetch $NEWEST"
fi

# --- 3. everything the page needs is reachable -------------------------------
# The list comes from check-references.py rather than a grep here, so the
# smoke test and the build check agree on what counts as a reference. A grep for
# href/src alone missed og.png, which og:image points at with an absolute URL.
missing=0
checked=0
while read -r path; do
  [ -z "$path" ] && continue
  checked=$((checked + 1))
  code="$(status "$BASE$path")"
  [ "$code" = "200" ] || { fail "$path -> $code"; missing=1; }
done <<< "$(python3 "$(dirname "$0")/../.github/scripts/check-references.py" --list "$SITE/index.html")"
[ "$checked" -gt 0 ] || fail "could not extract any references from $SITE/index.html"
[ "$missing" -eq 0 ] && [ "$checked" -gt 0 ] && echo "  ok    all $checked referenced files serve 200"

# --- 4. the artifact is the site, not the repository -------------------------
leaked=0
for path in /package.json /package-lock.json /README.md /test/harness.mjs \
            /scripts/build-icons.sh /icons/icon.svg /design/icon.svg; do
  code="$(status "$BASE$path")"
  [ "$code" = "404" ] || { fail "$path is published ($code); the artifact should be the site only"; leaked=1; }
done
[ "$leaked" -eq 0 ] && echo "  ok    no source files published"

[ "$FAILED" -eq 0 ] || { echo "Smoke test FAILED."; exit 1; }
echo "Smoke test passed."
