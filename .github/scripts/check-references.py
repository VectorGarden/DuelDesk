#!/usr/bin/env python3
"""Every local file the page references must actually exist in the repo.

Derived from the HTML rather than a hardcoded list, so a newly added
reference is covered automatically. External URLs, data: URIs, in-page
fragments and mailto: links are out of scope.
"""
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

SKIP_PREFIXES = ("http://", "https://", "//", "data:", "mailto:", "tel:", "#")

# og:image and twitter:image must be absolute URLs, so they would otherwise be
# skipped as external. Anything on our own domain is really a local file.
SELF_ORIGIN = "https://dueldesk.reizu.dev"


def main(path="index.html"):
    html = Path(path).read_text(encoding="utf-8")
    refs = set()

    def add(value):
        local = urlsplit(value).path              # drop ?query and #fragment
        if local and local != "/":                # "/" is the page itself
            refs.add(local)

    # href/src are always references.
    for attr in ("href", "src"):
        for m in re.finditer(rf'\b{attr}="([^"]+)"', html):
            value = m.group(1).strip()
            if value.startswith(SELF_ORIGIN):
                add(value[len(SELF_ORIGIN):])
            elif value and not value.startswith(SKIP_PREFIXES):
                add(value)

    # content= is mostly prose (descriptions, titles). Only a same-origin URL
    # in there is a file reference -- that is how og:image points at og.png.
    for m in re.finditer(r'\bcontent="([^"]+)"', html):
        value = m.group(1).strip()
        if value.startswith(SELF_ORIGIN):
            add(value[len(SELF_ORIGIN):])

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
    sys.exit(main(*sys.argv[1:]))
