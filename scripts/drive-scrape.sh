#!/bin/bash
# Drive scrape.yml in batches, stopping at the first sign of damage.
#
#   scripts/drive-scrape.sh rebuild  [batch]   # events an older builder wrote
#   scripts/drive-scrape.sh backfill [batch]   # events not in the archive yet
#
# Run from the root of a checkout that can push, with `gh` authenticated. Every
# batch is a workflow run that commits to main, so this pulls between batches
# and reads the archive off the files rather than out of a log.
#
# Fifty at a time. A batch costs about 104 seconds of fixed CI overhead -- two
# checkouts, cache restore and save, the artifact upload, the deploy job -- and
# about 0.55 seconds an event on top, so the batch size buys back overhead
# rather than compute. Five batches of forty was ~13 minutes for the archive;
# two of ninety-five should be ~6, and a single batch of everything only ~2
# minutes better than that while removing every checkpoint the halt conditions
# run at.
#
# Halts on: a fresh self-contradicting record, a round carrying nothing, the
# archive losing an event, a batch that makes no progress, or a failed run. The
# point of batches is to have somewhere to stop.
set -u

MODE=${1:-rebuild}
BATCH=${2:-50}
case "$MODE" in
  rebuild|backfill) ;;
  *) echo "usage: $0 <rebuild|backfill> [batch size]" >&2; exit 2 ;;
esac
[ -d events ] && [ -d scraper ] || { echo "run me from the repository root" >&2; exit 2; }

STATE=$(mktemp -d)
trap 'rm -rf "$STATE"' EXIT
state(){ python3 scripts/archive-state.py; }

before=$(state)
echo "$before" > "$STATE/0.json"
echo "start $(date +%H:%M:%S)  behind=$(jq -r .behind <<<"$before")  events=$(jq -r .events <<<"$before")"

n=0
while true; do
  behind=$(jq -r .behind <<<"$before")
  have=$(jq -r .events <<<"$before")
  # A rebuild is finished when nothing is behind. A backfill has no such
  # number -- what is missing from the archive is only known by asking for
  # more and getting none -- so it stops when the archive stops growing.
  if [ "$MODE" = rebuild ] && [ "$behind" -eq 0 ]; then
    echo "DONE: nothing behind"; break
  fi
  n=$((n+1))
  echo "--- batch $n  $(date +%H:%M:%S)  behind=$behind  events=$have"

  # A run already in flight is this batch. Set RESUME_RUN to pick one up
  # rather than dispatching a second one on top of it.
  if [ -n "${RESUME_RUN:-}" ]; then
    id=$RESUME_RUN; RESUME_RUN=""
    echo "    resuming run $id"
  else
    # Both numbers, whichever mode this is: an archive being rebuilt is also an
    # archive that may be missing events, and the run is already paid for.
    gh workflow run scrape.yml -f rebuild="$BATCH" -f backfill="$BATCH" -f force=true \
      || { echo "HALT: dispatch failed"; break; }
    sleep 20
    id=$(gh run list --workflow=scrape.yml --event workflow_dispatch --limit 1 \
           --json databaseId -q '.[0].databaseId')
    echo "    run $id"
  fi

  # Wait for the run itself to say it is finished. `gh run watch` returns early
  # -- it did on the first batch of the version 55 rebuild -- and asking for a
  # conclusion for thirty seconds after that read an empty one off a run that
  # was still going and called it a failed scrape. Only "completed" ends the
  # wait; anything else is still working. Forty minutes is far past a batch
  # that behaves and short of hanging here all night.
  concl=""
  for _ in $(seq 1 240); do
    st=$(gh run view "$id" --json status -q .status 2>/dev/null)
    if [ "$st" = completed ]; then
      concl=$(gh run view "$id" --json conclusion -q .conclusion 2>/dev/null)
      [ -n "$concl" ] && break
    fi
    sleep 10
  done
  [ -n "$concl" ] || { echo "HALT: run $id never reported a conclusion"; break; }
  echo "    $concl  $(date +%H:%M:%S)"

  if [ "$concl" != success ]; then
    # The scrape is what writes the archive; the deploy only publishes it. A
    # deploy that fails on a live-artifact hash is usually Pages' CDN still
    # serving the previous commit, which says nothing about the data. So ask
    # the scrape job first, and let a deploy failure through only once the live
    # bytes have caught up with what was committed.
    scrape=$(gh run view "$id" --json jobs \
      -q '.jobs[] | select(.name|test("Check for new coverage")) | .conclusion')
    [ "$scrape" = success ] || { echo "HALT: scrape job ended ${scrape:-unknown}"; break; }
    git pull -q --rebase
    want=$(git show HEAD:events.json | shasum -a 256 | cut -c1-16)
    # Give the CDN time to catch up before calling it a failed deploy. Asking
    # once, seconds after the run ends, is a race the CDN usually wins: it
    # halted a finished rebuild on its last batch, with the deploy green and
    # the bytes correct forty seconds later.
    live=""
    for _ in $(seq 1 18); do
      live=$(curl -sL https://dueldesk.reizu.dev/events.json | shasum -a 256 | cut -c1-16)
      [ "$want" = "$live" ] && break
      sleep 10
    done
    [ "$want" = "$live" ] || {
      echo "HALT: deploy failed and after 3 minutes the site still serves $live, not $want"; break; }
    echo "    deploy went red but the site serves $live as committed -- CDN lag, continuing"
  fi

  git pull -q --rebase || { echo "HALT: pull failed"; break; }
  after=$(state)
  echo "$after" > "$STATE/$n.json"

  bad=$(jq -r '.badRecords | length' <<<"$after")
  empt=$(jq -r '.emptyRounds | length' <<<"$after")
  lost=$(jq -rn --argjson a "$before" --argjson b "$after" '$a.slugs - $b.slugs | join(", ")')
  nb=$(jq -r .behind <<<"$after")
  na=$(jq -r .events <<<"$after")

  echo "    behind=$nb  events=$na  champions=$(jq -r .champions <<<"$after")"
  # Retried events that failed again. Not a halt -- they were not in the
  # archive to begin with, so nothing was lost -- but worth seeing, because a
  # fresh reason is the whole point of having cleared the old one.
  refused=$(jq -rn --argjson a "$before" --argjson b "$after" '$b.rejected - $a.rejected | join(", ")')
  [ -n "$refused" ] && echo "    rejected again: $refused"

  [ "$bad"  -gt 0 ] && { echo "HALT: contradicting records"; jq -r '.badRecords[]' <<<"$after"; break; }
  [ "$empt" -gt 0 ] && { echo "HALT: empty rounds";          jq -r '.emptyRounds[]' <<<"$after"; break; }
  [ -n "$lost" ]    && { echo "HALT: archive lost $lost"; break; }
  if [ "$MODE" = rebuild ]; then
    [ "$nb" -ge "$behind" ] && { echo "HALT: no progress ($behind -> $nb)"; break; }
  else
    [ "$na" -le "$have" ] && { echo "DONE: the archive stopped growing ($na events)"; break; }
  fi

  before=$after
done
echo "stopped $(date +%H:%M:%S)"
