"""
tests/test_nav_label_consistency.py

Verify that navigation labels for every page are consistent across
the sidebar (desktop), bottom-nav (mobile), top-bar (header), and
in-page headings.

Each page id must map to exactly one canonical label in all three
navigation components.  A mismatch means the user sees different
names for the same surface depending on viewport — confusing and
unprofessional.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

# Resolve the project root so we can read frontend source files.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND_LAYOUT = os.path.join(_PROJECT, "frontend", "src", "components", "layout")


def _read(filename: str) -> str:
    with open(os.path.join(_FRONTEND_LAYOUT, filename), encoding="utf-8") as f:
        return f.read()


def _extract_label_map(source: str, *, pattern: str) -> dict[str, str]:
    """Extract {page_id: label} pairs from a TS/TSX source file.

    ``pattern`` is a regex with two named groups: ``id`` and ``label``.
    """
    out: dict[str, str] = {}
    for m in re.finditer(pattern, source):
        out[m.group("id")] = m.group("label")
    return out


# ---------------------------------------------------------------------------
# Regexes for each component's label definition
# ---------------------------------------------------------------------------

# sidebar.tsx / bottom-nav.tsx — array-of-objects style:
#   { id: "events", label: "Archive", icon: ... }
_ARRAY_ITEM_RE = (
    r'\{\s*id:\s*"(?P<id>[^"]+)"'
    r',\s*label:\s*"(?P<label>[^"]+)"'
)

# top-bar.tsx — Record<Page, { group, title }> style:
#   events: { group: "Research", title: "Archive" },
# Match any field order before ``title:`` so the regex stays robust if
# the entry shape grows extra fields.
_RECORD_ENTRY_RE = (
    r'(?P<id>\w+):\s*\{[^}]*?title:\s*"(?P<label>[^"]+)"'
)

# ``overview`` is a documented back-compat alias for the ``market``
# surface (sidebar.tsx::Page).  Sidebar and bottom-nav only enumerate
# the canonical id; top-bar's PAGE_META keeps the alias so deep links
# still resolve.  Drop it from the comparison so consistency checks
# operate on canonical ids only.
_BACKCOMPAT_ALIASES = {"overview"}


class TestNavLabelConsistency(unittest.TestCase):
    """All three navigation surfaces must agree on every page label."""

    def setUp(self):
        self.sidebar_src = _read("sidebar.tsx")
        self.bottom_nav_src = _read("bottom-nav.tsx")
        self.top_bar_src = _read("top-bar.tsx")

        self.sidebar_labels = _extract_label_map(
            self.sidebar_src, pattern=_ARRAY_ITEM_RE,
        )
        self.bottom_nav_labels = _extract_label_map(
            self.bottom_nav_src, pattern=_ARRAY_ITEM_RE,
        )
        self.top_bar_labels = {
            k: v
            for k, v in _extract_label_map(
                self.top_bar_src, pattern=_RECORD_ENTRY_RE,
            ).items()
            if k not in _BACKCOMPAT_ALIASES
        }

    # -- structural checks ---------------------------------------------------

    def test_all_three_surfaces_cover_same_pages(self):
        """Every surface must enumerate the same set of page ids."""
        self.assertEqual(
            set(self.sidebar_labels),
            set(self.bottom_nav_labels),
            "sidebar and bottom-nav page ids differ",
        )
        self.assertEqual(
            set(self.sidebar_labels),
            set(self.top_bar_labels),
            "sidebar and top-bar page ids differ",
        )

    # -- per-page label agreement --------------------------------------------

    def test_labels_match_across_all_surfaces(self):
        """For every page id, sidebar == bottom-nav == top-bar label."""
        for page_id in self.sidebar_labels:
            sidebar = self.sidebar_labels[page_id]
            bottom = self.bottom_nav_labels.get(page_id)
            top = self.top_bar_labels.get(page_id)
            with self.subTest(page=page_id):
                self.assertEqual(
                    sidebar, bottom,
                    f"sidebar ({sidebar!r}) != bottom-nav ({bottom!r})",
                )
                self.assertEqual(
                    sidebar, top,
                    f"sidebar ({sidebar!r}) != top-bar ({top!r})",
                )

    # -- archive-specific check (the original offender) ----------------------

    def test_archive_label_is_consistent(self):
        """The events page must use the same label everywhere."""
        labels = {
            "sidebar": self.sidebar_labels.get("events"),
            "bottom-nav": self.bottom_nav_labels.get("events"),
            "top-bar": self.top_bar_labels.get("events"),
        }
        unique = set(labels.values())
        self.assertEqual(
            len(unique), 1,
            f"Archive page has inconsistent labels: {labels}",
        )


if __name__ == "__main__":
    unittest.main()
