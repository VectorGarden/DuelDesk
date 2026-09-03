"""A post's prose, as blocks the page can render without trusting its markup.

The coverage list links out: reading a post means leaving the archive for
yugiohblog.konami.com and coming back. Issue #189 asks for the posts to be
readable here, without images.

Images are not a detail skipped for convenience. The page forbids remote ones
by policy -- the event picker's chevron is drawn in CSS rather than linked,
because a CSS strict enough to forbid remote images is the same one that keeps
the page self-contained -- so hosting Konami's photographs is not an option and
inlining them would be worse. They are dropped here, at the scraper, so the
bytes are never stored in the first place.

What is stored is not HTML. Every headline and name the page renders goes
through `esc` first, because all of it came out of somebody else's markup by
way of a scraper, and an article is the largest piece of somebody else's markup
the archive has ever held. Handing a body to innerHTML would make that
invariant a matter of what Konami's CMS happens to emit -- there are already 14
iframes in the cache. So a block carries *runs* of text and which of them are
emphasised, and the page builds the elements itself:

    {"t": "p", "r": ["His build runs ", {"b": "Trade-In"}, " and six Malefic
                     monsters."]}

Emphasis is kept because it is doing work. A feature match bolds card names --
166,794 of them across the archive -- and stripped of that a match write-up is
a wall of prose in which nothing is a card.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Blocks, and what each becomes. A heading is a heading whatever its level:
# the archive renders one size of them.
_BLOCKS = {"p": "p", "h1": "h", "h2": "h", "h3": "h", "h4": "h", "h5": "h",
           "h6": "h", "li": "li", "blockquote": "q"}
# Emphasis worth keeping, and what it is called in the file. Short keys: there
# are tens of thousands of these and they are the bulk of what runs cost.
_EMPHASIS = {"strong": "b", "b": "b", "em": "i", "i": "i",
             "u": "u", "sup": "s", "mark": "b"}
# Taken out whole, contents and all. A figure is an image and its caption, and
# a caption without its photograph -- "Selig considers his options" -- is not
# prose, it is a label for something the reader cannot see.
_DROPPED = {"script", "style", "iframe", "figure", "noscript", "form", "svg",
            "video", "audio", "object", "embed"}
# Tags that never close. Counting one as an open tag inside a dropped figure
# leaves the depth stuck above zero and swallows the rest of the post -- and
# an image inside a figure is the commonest markup in the archive.
_VOID = {"img", "br", "hr", "input", "meta", "link", "source", "col", "area",
         "base", "embed", "param", "track", "wbr"}
# How much of a post may be the text of links to other posts. A table of
# contents is a page of links and nothing else -- "2026 North America WCQ Event
# Table of Contents!" is 7,489 characters of prose, 95% of it the headlines of
# other posts -- and stripped of the links it is a list of titles that go
# nowhere. Sixty posts in the archive are over this line and every one of them
# is a table of contents.
LINKS = 0.6

# How little prose is not worth an article. A quarter of result posts and a
# twelfth of news posts are a headline over a photograph, and stripped of the
# photograph they render as a headline and a caption -- which is worse than the
# link they replace. Measured: 200 characters is where that kind stops.
THIN = 200


class _Reader(HTMLParser):
    """Blocks out of a post body, keeping only text and which of it is bold."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self._runs: list[dict] = []      # the open block's runs, unmerged
        self._kind = "p"
        self._emphasis: list[str] = []
        self._dropping = 0
        self.linked = 0                  # characters that were inside an <a>
        self._in_link = 0
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    # -- blocks ---------------------------------------------------------
    def _close(self) -> None:
        runs = _merge(self._runs)
        if runs:
            self.blocks.append({"t": self._kind, "r": runs})
        self._runs, self._kind = [], "p"

    def handle_starttag(self, tag, attrs):
        if self._dropping or tag in _DROPPED:
            if tag not in _VOID:
                self._dropping += 1
            return
        if tag == "a":
            self._in_link += 1
        if tag == "br":
            # A break inside a paragraph is a space, not nothing: "Sky<br>
            # Striker" is one name written across two lines.
            self._write(" ")
        elif tag == "table":
            self._close()
            self._table, self._row, self._cell = [], None, None
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in _BLOCKS:
            self._close()
            self._kind = _BLOCKS[tag]
        elif tag == "hr":
            self._close()
            self.blocks.append({"t": "hr"})
        elif tag in _EMPHASIS:
            self._emphasis.append(_EMPHASIS[tag])

    def handle_endtag(self, tag):
        if self._dropping:
            self._dropping -= 1
            return
        if tag == "a" and self._in_link:
            self._in_link -= 1
        if tag == "table" and self._table is not None:
            rows = [r for r in self._table if any(c for c in r)]
            if rows:
                self.blocks.append({"t": "table", "rows": rows})
            self._table = self._row = self._cell = None
        elif tag == "tr" and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(_flatten("".join(self._cell)))
            self._cell = None
        elif tag in _BLOCKS:
            self._close()
        elif tag in _EMPHASIS and self._emphasis:
            # By name, not by position: Konami's CMS leaves tags unclosed and
            # closes them out of order, and popping blindly would carry one
            # paragraph's bold into the next.
            want = _EMPHASIS[tag]
            for i in range(len(self._emphasis) - 1, -1, -1):
                if self._emphasis[i] == want:
                    del self._emphasis[i]
                    break

    # -- text -----------------------------------------------------------
    def handle_data(self, data):
        if self._dropping:
            return
        if self._in_link:
            self.linked += len(data.strip())
        if self._cell is not None:
            self._cell.append(data)
        else:
            self._write(data)

    def _write(self, text: str) -> None:
        if self._row is not None:          # between cells, in no cell
            return
        self._runs.append({"e": self._emphasis[-1] if self._emphasis else None,
                           "t": text})

    def close(self):
        super().close()
        self._close()
        return self.blocks


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _merge(runs: list[dict]) -> list:
    """Runs into the shortest list that says the same thing.

    Konami's editor bolds word by word -- "<strong>Ancient</strong>
    <strong>Gear</strong> <strong>Gadjiltron</strong> <strong>Dragon</strong>"
    is one card name written as four runs and three spaces -- so adjacent runs
    of the same emphasis, and the whitespace between them, are one run.
    """
    out: list[dict] = []
    for run in runs:
        if out and out[-1]["e"] == run["e"]:
            out[-1] = {"e": run["e"], "t": out[-1]["t"] + run["t"]}
        elif not run["t"].strip() and out:
            # Whitespace belongs to whatever came before it, not to the
            # emphasis that happens to be open across it.
            out[-1] = {"e": out[-1]["e"], "t": out[-1]["t"] + run["t"]}
        else:
            out.append(run)
    # Flattening a run strips the space at its edges, and that space is the
    # only thing between "Selig runs" and a bolded "Trade-In". Whether there
    # was one is remembered before it goes.
    seen = [(_flatten(r["t"]), r["e"], r["t"][:1].isspace(), r["t"][-1:].isspace())
            for r in out]
    seen = [s for s in seen if s[0]]
    # The space goes on the end of the run before, never on the front of the
    # emphasised one: a bold card name starts at the C of "Cyber Dragon".
    texts = [s[0] for s in seen]
    for i in range(1, len(seen)):
        if not (seen[i][2] or seen[i - 1][3]):
            continue
        if seen[i][1] is None:              # the plain run after it
            texts[i] = " " + texts[i]
        else:                               # or the one before, emphasised or not
            texts[i - 1] += " "
    return [t if seen[i][1] is None else {seen[i][1]: t}
            for i, t in enumerate(texts)]


def read(body: str) -> tuple[list[dict], float]:
    """The blocks of a post body, and how much of it was the text of links."""
    reader = _Reader()
    reader.feed(body)
    blocks = reader.close()
    said = len(prose(blocks))
    return blocks, (reader.linked / said if said else 0.0)


def article(body: str) -> list[dict]:
    """The blocks of a post body, images and markup dropped."""
    return read(body)[0]


def prose(blocks: list[dict]) -> str:
    """The sentences in the blocks. Not the tables.

    A table is not writing, and counting its cells would make every standings
    post an article: forty characters of prose over five hundred rows reads as
    half a megabyte of text, and it is a table this archive already stores and
    already draws.
    """
    out = ["".join(run if isinstance(run, str) else next(iter(run.values()))
                   for run in b.get("r", ())) for b in blocks]
    return " ".join(t for t in out if t)


def readable(blocks: list[dict], linked: float = 0.0) -> bool:
    """Whether this is an article, or the remains of something else.

    Two ways it is not. A photo gallery leaves a headline and a caption, and a
    table of contents leaves the titles of other posts with nothing to click.
    """
    return len(prose(blocks)) > THIN and linked <= LINKS
