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

# Pages propagates asynchronously, and it does not propagate one file at a
# time: index.html can be the new one while events.json is still the old one.
# So every comparison waits the same way, rather than the first check retrying
# for ninety seconds and the rest asking once each -- which is what failed a
# healthy deploy of the v60 rebuild, and taught the rebuild driver to expect
# false alarms from the check that is supposed to stop it.
#
# $1 the path on the site, $2 the file it should match, $3 what to call it.
served_matches() {
  local path="$1" local_file="$2" label="$3" want got i
  want="$(shasum -a 256 "$local_file" | cut -d' ' -f1)"
  for i in $(seq 1 "$ATTEMPTS"); do
    got="$(fetch "$BASE/$path" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"
    if [ "$want" = "$got" ]; then
      echo "  ok    $label matches the uploaded artifact${i:+ (attempt $i)}"
      return 0
    fi
    [ "$i" -lt "$ATTEMPTS" ] && sleep 10
  done
  fail "$label served ${got:0:16}..., expected ${want:0:16}..."
  return 1
}

# Every script and stylesheet the pages ask for, read out of the pages rather
# than listed here -- a list gets forgotten, which is how decks.js reached the
# staging script late and would have gone unchecked here entirely.
assets() {
  grep -ho '\(src\|href\)="[^"]*\.\(js\|css\)"' \
       "$SITE"/*.html "$SITE"/*/index.html 2>/dev/null \
    | sed 's/.*="//; s/"$//; s|^/||' | sort -u
}

EXPECTED="$(shasum -a 256 "$SITE/index.html" | cut -d' ' -f1)"
echo "Smoke testing $BASE"
echo "  expecting index.html sha256 ${EXPECTED:0:16}..."

# --- 1. the page we built is the page being served ---------------------------
served_matches "" "$SITE/index.html" "index.html"

# --- 1b. and so are the files it cannot run without --------------------------
# index.html is markup now; the behaviour is in app.js and the look in
# styles.css. A deploy that shipped a stale app.js would serve a page that
# renders and then does nothing, and the hash above would call it correct.
for asset in $(assets); do
  [ -f "$SITE/$asset" ] || { fail "$asset is asked for but was never staged"; continue; }
  served_matches "$asset" "$SITE/$asset" "$asset"
done

# --- 2. the data we built is the data being served ---------------------------
# Hash-compared like index.html, because that holds however the data was made.
# The age check below cannot do this job alone: real coverage is stamped with the
# event's own times, so a finished event is legitimately days old.
# The manifest first, then the event it names newest -- which is the pair the
# page loads on a cold visit. Checking only the manifest would pass a deploy
# that shipped an index to files it forgot to stage.
# The schedule the sidebar reads. Small, and its absence is silent on the page
# by design -- the card degrades to its link -- which is exactly why a check
# here is worth having: nothing else would notice it had stopped being served.
if ! fetch "$BASE/upcoming.json" > /tmp/smoke-upcoming.json 2>/dev/null; then
  fail "could not fetch upcoming.json"
else
  python3 -c '
import json, sys
d = json.load(open("/tmp/smoke-upcoming.json"))
assert isinstance(d.get("events"), list) and d["events"], "no events in it"
print(f"  ok    upcoming.json serves {len(d["events"])} events")
' || fail "upcoming.json is not usable"
fi

served_matches "events.json" "$SITE/events.json" "events.json"
if ! fetch "$BASE/events.json" > /tmp/smoke-events.json 2>/dev/null; then
  fail "could not fetch events.json"
fi

NEWEST="$(python3 -c '
import json; print(json.load(open("/tmp/smoke-events.json"))["events"][0]["path"])')"
echo "  ..    newest event is $NEWEST"

if served_matches "$NEWEST" "$SITE/$NEWEST" "$NEWEST" \
   && fetch "$BASE/$NEWEST" > /tmp/smoke-rounds.json 2>/dev/null; then

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
  # Rooted here rather than trusting the shape it arrives in. Every reference
  # in the markup was absolute until the styles and the behaviour moved out of
  # the page, and "app.js" concatenated straight onto the host is a request to
  # dueldesk.reizu.devapp.js -- which fails, and had nothing to do with whether
  # the file was there.
  code="$(status "$BASE/${path#/}")"
  # A redirect is not a missing file. /winners is a directory with an index in
  # it, which is how a static host serves a clean URL at all, and every one of
  # them answers the bare name with a 301 to the name with a slash. Requiring a
  # literal 200 failed the deploy on a page that was being served perfectly
  # well -- and the reference check in CI passed, because the file was there.
  #
  # The redirect still has to arrive somewhere real: what is required is that
  # following it ends in 200, so a reference pointing at nothing fails exactly
  # as it did before.
  case "$code" in
    30[1278])
      final="$(curl -sSL -o /dev/null -m 20 -w '%{http_code}' "$BASE/${path#/}" 2>/dev/null || echo 000)"
      if [ "$final" = "200" ]; then
        echo "  ok    $path -> $code -> $final"
      else
        fail "$path -> $code -> $final"; missing=1
      fi
      ;;
    200) ;;
    *) fail "$path -> $code"; missing=1 ;;
  esac
done <<< "$(python3 "$(dirname "$0")/../.github/scripts/check-references.py" --list "$SITE/index.html")"
[ "$checked" -gt 0 ] || fail "could not extract any references from $SITE/index.html"
[ "$missing" -eq 0 ] && [ "$checked" -gt 0 ] && echo "  ok    all $checked referenced files serve 200"

# --- 4. the artifact is the site, not the repository -------------------------
leaked=0
for path in /package.json /package-lock.json /README.md /test/harness.mjs \
            /scripts/build-icons.sh /icons/icon.svg /design/icon.svg; do
  code="$(status "$BASE/${path#/}")"
  [ "$code" = "404" ] || { fail "$path is published ($code); the artifact should be the site only"; leaked=1; }
done
[ "$leaked" -eq 0 ] && echo "  ok    no source files published"

[ "$FAILED" -eq 0 ] || { echo "Smoke test FAILED."; exit 1; }
echo "Smoke test passed."
