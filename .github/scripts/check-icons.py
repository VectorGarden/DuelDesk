#!/usr/bin/env python3
"""Guard the favicon setup, including the parts that broke Safari.

Two failures here are invisible to every other check: an ICO whose entries are
PNG-encoded (Safari does not reliably decode those, and silently shows its
generic globe instead), and an oversized rel="icon" that a browser may pick and
squeeze down to 16px. Neither shows up in HTML validation or the test suite.
"""
import json
import re
import struct
import sys
from pathlib import Path

MAX_FAVICON_PX = 48   # anything larger belongs in the manifest, not rel="icon"


def check_ico(path, problems):
    p = Path(path)
    if not p.exists():
        problems.append(f"{path} is missing")
        return
    d = p.read_bytes()
    if len(d) < 6:
        problems.append(f"{path} is truncated")
        return
    reserved, kind, count = struct.unpack("<HHH", d[:6])
    if (reserved, kind) != (0, 1):
        problems.append(f"{path}: bad ICONDIR header")
        return
    if count == 0:
        problems.append(f"{path}: contains no entries")
        return

    for i in range(count):
        entry = d[6 + 16 * i:22 + 16 * i]
        if len(entry) < 16:
            problems.append(f"{path}: entry {i} directory is truncated")
            continue
        w, h, _, _, _, bits, size, off = struct.unpack("<BBBBHHII", entry)
        blob = d[off:off + size]
        if len(blob) != size:
            problems.append(f"{path}: entry {i} data is truncated")
            continue
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            problems.append(
                f"{path}: entry {i} ({w or 256}px) is PNG-encoded. Safari does not "
                "reliably decode PNG-in-ICO and falls back to a generic icon. "
                "Rebuild with scripts/build-favicon.py")
            continue
        (bi_size,) = struct.unpack("<I", blob[:4])
        if bi_size != 40:
            problems.append(f"{path}: entry {i} is neither PNG nor a 40-byte-header BMP")
            continue
        bi_w, bi_h = struct.unpack("<ii", blob[4:12])
        if bi_w != (w or 256) or bi_h != (h or 256) * 2:
            problems.append(f"{path}: entry {i} DIB is {bi_w}x{bi_h // 2}, "
                            f"directory says {w or 256}x{h or 256}")
    if not problems:
        print(f"  ok    {path}: {count} BMP entries, readable by Safari")


def check_declarations(path, problems):
    html = Path(path).read_text(encoding="utf-8")
    head = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", "", html, flags=re.S | re.I)

    icons = re.findall(r'<link\s+rel="icon"[^>]*>', head)
    if not icons:
        problems.append(f"{path}: declares no rel=\"icon\"")

    for tag in icons:
        m = re.search(r'sizes="([^"]+)"', tag)
        if not m or m.group(1).strip() == "any":
            continue
        for token in m.group(1).split():
            side = token.lower().split("x")[0]
            if side.isdigit() and int(side) > MAX_FAVICON_PX:
                problems.append(
                    f"{path}: rel=\"icon\" offers {token}. A browser may pick the "
                    f"largest candidate and render it at 16px. Keep rel=\"icon\" at "
                    f"{MAX_FAVICON_PX}px or below and put install icons in the manifest.")

    for rel, why in (("mask-icon", "Safari pinned tabs"),
                     ("apple-touch-icon", "iOS home screen")):
        if f'rel="{rel}"' not in head:
            problems.append(f"{path}: no rel=\"{rel}\" ({why})")

    mask = re.search(r'<link\s+rel="mask-icon"[^>]*href="([^"]+)"', head)
    if mask:
        f = Path(mask.group(1).lstrip("/"))
        if not f.exists():
            problems.append(f"mask-icon target {f} is missing")
        else:
            svg = f.read_text(encoding="utf-8")
            if re.search(r'fill="(?!none)[^"]+"', svg):
                problems.append(f"{f}: mask-icon must be monochrome; Safari applies "
                                "the colour from the link's color attribute")
    if not problems:
        print(f"  ok    {path}: favicon declarations capped at {MAX_FAVICON_PX}px, "
              "mask-icon and apple-touch-icon present")


def check_shipped_icons(icon_dir, html, manifest, problems):
    """Everything in icons/ ships, so everything in icons/ must be used and real.

    Two failures this catches: an icon nobody references (dead weight, published
    and unverified -- there were six, plus a byte-identical duplicate), and a
    file whose pixels do not match the size its name and the manifest claim,
    which a browser would silently scale.
    """
    d = Path(icon_dir)
    if not d.is_dir():
        problems.append(f"{icon_dir}/ is missing")
        return

    haystack = Path(html).read_text(encoding="utf-8")
    if Path(manifest).exists():
        haystack += Path(manifest).read_text(encoding="utf-8")

    seen = {}
    for f in sorted(d.iterdir()):
        if f.name.startswith("."):
            continue
        # Match on the path, not the bare filename: "icon.svg" is a substring of
        # "mask-icon.svg", so a bare-name search reports an unused source as used.
        if f"icons/{f.name}" not in haystack:
            problems.append(f"{f} is shipped but referenced by nothing. Reference it "
                            "or move it out of icons/, which is the published directory.")
        if f.suffix == ".svg":
            continue
        if f.suffix != ".png":
            problems.append(f"{f}: unexpected file type in the published icon directory")
            continue

        data = f.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            problems.append(f"{f} is not a PNG")
            continue
        w, h = struct.unpack(">II", data[16:24])
        if w != h:
            problems.append(f"{f} is {w}x{h}; icons must be square")
        m = re.search(r"-(\d+)\.png$", f.name)
        if m and int(m.group(1)) != w:
            problems.append(f"{f} is {w}x{w} but its name says {m.group(1)}")

        digest = hash(data)
        if digest in seen:
            problems.append(f"{f} is byte-identical to {seen[digest]}; ship one of them")
        else:
            seen[digest] = f

    # Manifest entries must agree with the files on disk.
    if Path(manifest).exists():
        try:
            for icon in json.loads(Path(manifest).read_text(encoding="utf-8")).get("icons", []):
                src = Path(str(icon.get("src", "")).lstrip("/"))
                declared = str(icon.get("sizes", "")).split("x")[0]
                if not src.exists():
                    continue                      # check-references.py reports this
                data = src.read_bytes()
                if data[:8] != b"\x89PNG\r\n\x1a\n":
                    continue
                w, _ = struct.unpack(">II", data[16:24])
                if declared.isdigit() and int(declared) != w:
                    problems.append(f"{manifest}: {src} declared {icon.get('sizes')} "
                                    f"but the file is {w}x{w}")
        except json.JSONDecodeError:
            problems.append(f"{manifest} is not valid JSON")

    if not problems:
        pngs = [f for f in d.iterdir() if f.suffix == ".png"]
        print(f"  ok    {icon_dir}/: {len(pngs)} icons, all referenced, "
              "sizes match their names, no duplicates")


def main(ico="favicon.ico", html="index.html"):
    problems = []
    check_ico(ico, problems)
    check_declarations(html, problems)
    check_shipped_icons("icons", html, "site.webmanifest", problems)
    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
