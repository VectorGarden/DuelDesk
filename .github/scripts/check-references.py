#!/usr/bin/env python3
"""Every local file the page references must actually exist in the repo.

Derived from the HTML rather than a hardcoded list, so a newly added
reference is covered automatically. External URLs, data: URIs, in-page
fragments and mailto: links are out of scope.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

SKIP_PREFIXES = ("http://", "https://", "//", "data:", "mailto:", "tel:", "#")

# og:image and twitter:image must be absolute URLs, so they would otherwise be
# skipped as external. Anything on our own domain is really a local file.
SELF_ORIGIN = "https://dueldesk.reizu.dev"


def collect(path):
    """The reference paths a page depends on. Shared with the smoke test, so
    both agree on what "referenced" means -- href/src, plus same-origin
    absolute URLs in content=, which is how og:image points at og.png."""
    return _main(path, list_only=True)


def every_page(paths):
    """Check each page given, and fail if any of them does.

    index.html was the only one checked for a long time, which is how a
    tombstone that refreshed to itself reached production: nothing ever read
    winners.html, because nothing links to it -- that is the point of it.
    """
    worst = 0
    for one in paths:
        print(f"-- {one}")
        worst = max(worst, _main(one))
    return worst


def main(path="index.html"):
    if path == "--list":
        raise SystemExit("usage: check-references.py [--list] <html>")
    return _main(path, list_only=False)


def _main(path="index.html", list_only=False):
    html = Path(path).read_text(encoding="utf-8")

    # Strip <script> and <style> *bodies* before scanning. Their contents are
    # code, not markup: a template literal like href="${esc(p.url)}" would
    # otherwise be read as a filename and reported missing.
    #
    # The opening tag is kept, because that is where a reference lives once the
    # code moves out of the page: this dropped the whole element, so
    # <script src="app.js"> was stripped along with its body and the file the
    # site cannot run without was never checked for at all.
    markup = re.sub(
        r"(<(script|style)\b[^>]*>).*?</\2\s*>", r"\1", html, flags=re.S | re.I
    )

    refs = set()

    def add(value):
        local = urlsplit(value).path              # drop ?query and #fragment
        if local and local != "/":                # "/" is the page itself
            refs.add(local)

    # href/src are always references.
    for attr in ("href", "src"):
        for m in re.finditer(rf'\b{attr}="([^"]+)"', markup):
            value = m.group(1).strip()
            if value.startswith(SELF_ORIGIN):
                add(value[len(SELF_ORIGIN):])
            elif value and not value.startswith(SKIP_PREFIXES):
                add(value)

    # content= is mostly prose (descriptions, titles). Only a same-origin URL
    # in there is a file reference -- that is how og:image points at og.png.
    for m in re.finditer(r'\bcontent="([^"]+)"', markup):
        value = m.group(1).strip()
        if value.startswith(SELF_ORIGIN):
            add(value[len(SELF_ORIGIN):])

    # A web manifest's icons are referenced from JSON, not from the HTML, so
    # they would otherwise be invisible to this check.
    for manifest in sorted(p for p in refs if p.endswith(".webmanifest") or p.endswith("manifest.json")):
        mpath = Path(manifest.lstrip("/"))
        if not mpath.exists():
            continue
        try:
            data = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  FAIL    {manifest} is not valid JSON: {exc}")
            return 1
        for icon in data.get("icons", []):
            src = (icon.get("src") or "").strip()
            if src and not src.startswith(SKIP_PREFIXES):
                add(src)

    # A meta refresh that lands back on the page it is on. GitHub Pages
    # resolves an extensionless /winners to winners.html before it looks at
    # winners/, so a tombstone there aimed at /winners redirected to itself and
    # the winners page could not be opened in a browser at all.
    #
    # Invisible to everything else that checks this site: the response is an
    # ordinary 200 with a well-formed body, and following the refresh is the
    # browser's job. Only the file can say where it is sending people.
    # The trailing slash is the whole difference and must not be normalised
    # away: Pages serves winners.html at /winners.html and at /winners, and
    # serves winners/index.html at /winners/. Aiming the refresh at the first
    # two is a loop; aiming it at the third is the fix.
    here = "/" + str(Path(path).name)
    stem = here[:-len(".html")] if here.endswith(".html") else None
    for m in re.finditer(r'http-equiv="refresh"[^>]*content="[^"]*url=([^"\s]+)', markup, re.I):
        if m.group(1) in {here, stem}:
            print(f"  FAIL    {path} refreshes to {m.group(1)}, which is itself")
            return 1

    if list_only:
        for ref in sorted(refs):
            print(ref)
        return 0

    missing = []
    for ref in sorted(refs):
        target = Path(ref.lstrip("/"))
        # A directory is a reference to the index inside it -- /winners is
        # winners/index.html, which is how a static host serves a clean URL.
        # The index has to be there: an empty directory answers a local
        # http.server with a file listing and GitHub Pages with a 404, so the
        # rehearsal would pass and the deploy would serve nothing.
        if target.is_dir():
            index = target / "index.html"
            if index.is_file():
                print(f"  ok      {ref} ({index})")
            else:
                missing.append(ref)
                print(f"  MISSING {ref} is a directory with no index.html")
        elif target.exists():
            print(f"  ok      {ref}")
        else:
            missing.append(ref)
            print(f"  MISSING {ref}")

    if not refs:
        print(f"  FAIL    no local references found in {path} - is the parser broken?")
        return 1
    print(f"{len(refs)} local reference(s) checked, {len(missing)} missing")
    return 1 if missing else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) > 1 and "--list" not in args:
        sys.exit(every_page(args))
    if args and args[0] == "--list":
        sys.exit(_main(*(args[1:] or ["index.html"]), list_only=True))
    sys.exit(main(*args))
