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

    if list_only:
        for ref in sorted(refs):
            print(ref)
        return 0

    missing = []
    for ref in sorted(refs):
        target = Path(ref.lstrip("/"))
        if target.exists():
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
    if args and args[0] == "--list":
        sys.exit(_main(*(args[1:] or ["index.html"]), list_only=True))
    sys.exit(main(*args))
