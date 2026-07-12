"""
tests/test_nav_label_consistency.py

Verify the navigation surface contracts across the three chrome
components — sidebar (desktop), bottom-nav (mobile), and top-bar
(header) — by reading the frontend TypeScript source directly.

The navigation model distinguishes three explicit page categories:

1. Primary pages — enumerated in the sidebar's primary ``NAV_GROUPS``
   and the mobile ``TABS``.  The two primary id sets must be identical,
   every primary id must have top-bar ``PAGE_META``, and for each id
   the sidebar, bottom-nav, and top-bar labels must agree.

2. Back-compat alias — ``overview`` resolves to the same surface as
   ``market`` (App.tsx routes both to <MarketOverview>).  It keeps a
   ``PAGE_META`` entry so older deep links still resolve and title
   correctly, but it is never a displayed primary navigation item.

3. Reference route — ``demo`` (Section C Demo) is deliberately demoted
   out of primary navigation.  It stays routable and keeps ``PAGE_META``,
   and is reachable only through the sidebar footer reference link,
   whose collapsed tooltip and expanded label must agree with each
   other and with the top-bar title.

The only page ids allowed in ``PAGE_META`` beyond the primary set are
the documented alias and reference ids — an unexpected extra fails
loudly instead of being silently ignored.

This module tests primary navigation labels, route-metadata coverage,
the alias contract, and the reference-link contract.  It does not
inspect in-page headings.
"""

from __future__ import annotations

import os
import re
import unittest

# Resolve the project root so we can read frontend source files.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND_SRC = os.path.join(_PROJECT, "frontend", "src")
_FRONTEND_LAYOUT = os.path.join(_FRONTEND_SRC, "components", "layout")


def _read_layout(filename: str) -> str:
    with open(os.path.join(_FRONTEND_LAYOUT, filename), encoding="utf-8") as f:
        return f.read()


def _read_app() -> str:
    with open(os.path.join(_FRONTEND_SRC, "App.tsx"), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Documented non-primary page categories
# ---------------------------------------------------------------------------

# ``overview`` — back-compat alias for the ``market`` surface.  App.tsx
# routes both ids to <MarketOverview>; PAGE_META keeps the alias so older
# deep links and setPage("overview") callers still resolve and title
# correctly.  Never displayed in primary navigation.
ALIAS_IDS = frozenset({"overview"})

# ``demo`` — Section C Demo, an artifact-backed reference surface
# deliberately demoted out of primary navigation (sidebar NAV_GROUPS and
# mobile TABS).  It stays routable, keeps PAGE_META so the top bar titles
# it when active, and is reachable via the sidebar footer reference link.
REFERENCE_IDS = frozenset({"demo"})

# Canonical displayed label for the demoted reference route.
DEMO_CANONICAL_LABEL = "Section C Demo"


# ---------------------------------------------------------------------------
# Bounded source extraction (named per surface; each fails loudly when the
# marker or the entries it expects are missing — never silently empty)
# ---------------------------------------------------------------------------

# sidebar.tsx NAV_GROUPS / bottom-nav.tsx TABS — array-of-objects style:
#   { id: "events", label: "Archive", icon: ... }
_ARRAY_ITEM_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)"'
    r',\s*label:\s*"(?P<label>[^"]+)"'
)

# top-bar.tsx PAGE_META — Record<Page, { group, title }> style:
#   events: { group: "Research", title: "Archive" },
# Match any field order before ``title:`` so the regex stays robust if
# the entry shape grows extra fields.
_RECORD_ENTRY_RE = re.compile(
    r'(?P<id>\w+):\s*\{[^}]*?title:\s*"(?P<label>[^"]+)"'
)


def _slice_block(source: str, start_marker: str, end_marker: str, *, what: str) -> str:
    """Return the source slice between two markers, failing loudly."""
    start = source.find(start_marker)
    if start == -1:
        raise AssertionError(f"{what}: start marker {start_marker!r} not found")
    end = source.find(end_marker, start)
    if end == -1:
        raise AssertionError(f"{what}: end marker {end_marker!r} not found after start")
    return source[start:end]


def _extract_primary_nav_array(source: str, const_name: str) -> dict[str, str]:
    """Extract {page_id: label} from a primary nav array (NAV_GROUPS / TABS).

    Scoped to the named ``const`` declaration so unrelated object literals
    elsewhere in the file can never be captured.
    """
    block = _slice_block(
        source, f"const {const_name}", "];", what=f"primary array {const_name}",
    )
    out = {m.group("id"): m.group("label") for m in _ARRAY_ITEM_RE.finditer(block)}
    if not out:
        raise AssertionError(
            f"primary array {const_name}: extraction returned no entries "
            "(regex or source structure drifted)"
        )
    return out


def _extract_page_meta_record(source: str) -> dict[str, str]:
    """Extract {page_id: title} from the top-bar PAGE_META record."""
    block = _slice_block(source, "const PAGE_META", "};", what="PAGE_META record")
    out = {
        m.group("id"): m.group("label") for m in _RECORD_ENTRY_RE.finditer(block)
    }
    if not out:
        raise AssertionError(
            "PAGE_META record: extraction returned no entries "
            "(regex or source structure drifted)"
        )
    return out


def _extract_page_union(source: str) -> list[str]:
    """Extract the canonical ``Page`` union members from sidebar.tsx."""
    block = _slice_block(source, "export type Page", ";", what="Page union")
    ids = re.findall(r'"([^"]+)"', block)
    if len(ids) < 2:
        raise AssertionError(f"Page union: extraction returned too few members: {ids!r}")
    return ids


def _extract_demo_reference(sidebar_source: str) -> dict[str, object]:
    """Extract the sidebar footer Section C Demo reference link.

    Scoped to the region AFTER the primary-nav ``</ScrollArea>`` boundary so
    primary nav items can never satisfy these assertions.  Returns the
    collapsed tooltip label, the expanded footer label, and the
    ``onNavigate("...")`` targets of the reference buttons (collapsed and
    expanded branches).
    """
    marker = "</ScrollArea>"
    idx = sidebar_source.find(marker)
    if idx == -1:
        raise AssertionError("sidebar reference: </ScrollArea> boundary not found")
    footer = sidebar_source[idx + len(marker):]

    # Literal-text captures only ([^<{]) so interpolated {label} JSX in any
    # future footer content cannot be mistaken for a displayed label.
    tooltips = re.findall(
        r'<TooltipContent side="right">([^<{]+)</TooltipContent>', footer,
    )
    expanded = re.findall(r'<span className="truncate">([^<{]+)</span>', footer)
    targets = re.findall(r'onNavigate\("([^"]+)"\)', footer)

    if len(tooltips) != 1:
        raise AssertionError(
            f"sidebar reference: expected exactly 1 collapsed tooltip label, "
            f"found {tooltips!r}"
        )
    if len(expanded) != 1:
        raise AssertionError(
            f"sidebar reference: expected exactly 1 expanded footer label, "
            f"found {expanded!r}"
        )
    if len(targets) != 2:
        raise AssertionError(
            f"sidebar reference: expected onNavigate targets for the collapsed "
            f"and expanded branches, found {targets!r}"
        )
    return {
        "collapsed_label": tooltips[0],
        "expanded_label": expanded[0],
        "targets": targets,
    }


def _primary_label_mismatches(
    primary_ids: set[str],
    sidebar: dict[str, str],
    bottom_nav: dict[str, str],
    top_bar: dict[str, str],
) -> list[str]:
    """Return one problem line per primary id whose three labels disagree."""
    problems: list[str] = []
    for pid in sorted(primary_ids):
        s = sidebar.get(pid)
        b = bottom_nav.get(pid)
        t = top_bar.get(pid)
        if s is None or not (s == b == t):
            problems.append(f"{pid}: sidebar={s!r} bottom-nav={b!r} top-bar={t!r}")
    return problems


class _NavSourceCase(unittest.TestCase):
    """Shared source loading + extraction for all navigation contract tests."""

    @classmethod
    def setUpClass(cls):
        cls.sidebar_src = _read_layout("sidebar.tsx")
        cls.bottom_nav_src = _read_layout("bottom-nav.tsx")
        cls.top_bar_src = _read_layout("top-bar.tsx")
        cls.app_src = _read_app()

        cls.sidebar_primary = _extract_primary_nav_array(cls.sidebar_src, "NAV_GROUPS")
        cls.bottom_nav_primary = _extract_primary_nav_array(cls.bottom_nav_src, "TABS")
        cls.page_meta = _extract_page_meta_record(cls.top_bar_src)
        cls.page_union = _extract_page_union(cls.sidebar_src)

        # Canonical primary ids are DERIVED from the primary sidebar source,
        # never from an independently maintained test list.
        cls.primary_ids = set(cls.sidebar_primary)


# ---------------------------------------------------------------------------
# Primary navigation contract
# ---------------------------------------------------------------------------

class TestNavLabelConsistency(_NavSourceCase):
    """Primary pages must agree across sidebar, bottom nav, and top bar."""

    def test_primary_surfaces_cover_same_pages(self):
        """Sidebar primary ids == bottom-nav primary ids."""
        self.assertEqual(
            set(self.sidebar_primary),
            set(self.bottom_nav_primary),
            "sidebar and bottom-nav primary page ids differ",
        )

    def test_every_primary_page_has_top_bar_metadata(self):
        """Every primary id must exist in PAGE_META (extras checked separately)."""
        missing = sorted(self.primary_ids - set(self.page_meta))
        self.assertEqual(
            missing, [],
            f"primary pages missing top-bar PAGE_META entries: {missing}",
        )

    def test_primary_labels_match_across_all_surfaces(self):
        """For every primary id, sidebar == bottom-nav == top-bar label."""
        problems = _primary_label_mismatches(
            self.primary_ids,
            self.sidebar_primary,
            self.bottom_nav_primary,
            self.page_meta,
        )
        self.assertEqual(
            problems, [],
            "primary label drift:\n" + "\n".join(problems),
        )

    # -- archive-specific check (the original offender) ----------------------

    def test_archive_label_is_consistent(self):
        """The events page must be labeled "Archive" everywhere."""
        labels = {
            "sidebar": self.sidebar_primary.get("events"),
            "bottom-nav": self.bottom_nav_primary.get("events"),
            "top-bar": self.page_meta.get("events"),
        }
        self.assertEqual(
            labels,
            {"sidebar": "Archive", "bottom-nav": "Archive", "top-bar": "Archive"},
            f"Archive page has inconsistent labels: {labels}",
        )


# ---------------------------------------------------------------------------
# Route-metadata reconciliation — no silently ignored extras, no orphans
# ---------------------------------------------------------------------------

class TestTopBarMetadataReconciliation(_NavSourceCase):
    """PAGE_META must cover exactly: primary ids + documented alias/reference."""

    def test_top_bar_extras_are_exactly_the_documented_non_primary_ids(self):
        """top_bar_ids - primary_ids == {alias} | {reference} — no more, no less.

        An unexpected new PAGE_META-only id fails here instead of being
        silently ignored; removing the documented alias or reference entry
        fails here too.
        """
        extras = set(self.page_meta) - self.primary_ids
        self.assertEqual(
            extras,
            set(ALIAS_IDS | REFERENCE_IDS),
            "top-bar PAGE_META extras beyond primary ids must be exactly the "
            f"documented alias {sorted(ALIAS_IDS)} and reference "
            f"{sorted(REFERENCE_IDS)} ids; found extras: {sorted(extras)}",
        )

    def test_every_page_union_member_has_top_bar_metadata(self):
        """Every canonical Page member that can become active must title the top bar."""
        self.assertEqual(
            set(self.page_union),
            set(self.page_meta),
            "Page union and PAGE_META ids must reconcile exactly",
        )

    def test_page_union_partitions_into_categories(self):
        """Every Page member is primary, alias, or reference — no orphans."""
        categorized = self.primary_ids | set(ALIAS_IDS) | set(REFERENCE_IDS)
        self.assertEqual(
            set(self.page_union),
            categorized,
            "Page union must partition exactly into primary/alias/reference "
            f"(orphans: {sorted(set(self.page_union) - categorized)}, "
            f"unknown categorized ids: {sorted(categorized - set(self.page_union))})",
        )
        self.assertTrue(
            self.primary_ids.isdisjoint(ALIAS_IDS | REFERENCE_IDS),
            "alias/reference ids must never also be primary ids",
        )


# ---------------------------------------------------------------------------
# ``overview`` — back-compat alias integrity
# ---------------------------------------------------------------------------

class TestOverviewAliasIntegrity(_NavSourceCase):
    """``overview`` stays a routable alias of ``market``, never displayed."""

    def test_overview_absent_from_primary_navigation(self):
        self.assertNotIn("overview", self.sidebar_primary)
        self.assertNotIn("overview", self.bottom_nav_primary)

    def test_overview_title_matches_market(self):
        """The alias must keep PAGE_META and title exactly like ``market``."""
        self.assertIn("overview", self.page_meta)
        self.assertIn("market", self.page_meta)
        self.assertEqual(
            self.page_meta["overview"],
            self.page_meta["market"],
            "overview is a back-compat alias of market — titles must match",
        )

    def test_overview_routes_to_market_surface(self):
        """App.tsx must route both ids to the same MarketOverview surface."""
        self.assertIn(
            '(page === "market" || page === "overview")',
            self.app_src,
            "App.tsx no longer routes overview and market to the same surface",
        )


# ---------------------------------------------------------------------------
# ``demo`` — demoted Section C Demo reference-route integrity
# ---------------------------------------------------------------------------

class TestDemoReferenceIntegrity(_NavSourceCase):
    """``demo`` stays routable + titled, but demoted out of primary nav."""

    def test_demo_absent_from_primary_navigation(self):
        """Demo must not reappear in the sidebar primary groups or mobile tabs."""
        self.assertNotIn("demo", self.sidebar_primary)
        self.assertNotIn("demo", self.bottom_nav_primary)

    def test_demo_has_top_bar_metadata(self):
        self.assertIn("demo", self.page_meta)

    def test_demo_reference_labels_agree(self):
        """Collapsed tooltip == expanded footer label == top-bar title == canonical."""
        ref = _extract_demo_reference(self.sidebar_src)
        self.assertEqual(
            ref["collapsed_label"], ref["expanded_label"],
            "collapsed tooltip and expanded footer reference labels differ",
        )
        self.assertEqual(
            ref["expanded_label"], self.page_meta.get("demo"),
            "sidebar reference label and top-bar demo title differ",
        )
        self.assertEqual(
            ref["expanded_label"], DEMO_CANONICAL_LABEL,
            f"demo reference label drifted from canonical {DEMO_CANONICAL_LABEL!r}",
        )

    def test_demo_reference_navigates_to_demo(self):
        """Both sidebar reference branches must navigate to the demo page."""
        ref = _extract_demo_reference(self.sidebar_src)
        self.assertEqual(
            ref["targets"], ["demo", "demo"],
            "sidebar reference buttons must both target the demo page",
        )

    def test_demo_route_still_resolves(self):
        """App.tsx must keep rendering the demo route."""
        self.assertIn(
            'page === "demo"',
            self.app_src,
            "App.tsx no longer renders the demo route",
        )


# ---------------------------------------------------------------------------
# Non-vacuousness guards — prove drift would still be detected
# ---------------------------------------------------------------------------

class TestDriftDetectionGuards(_NavSourceCase):
    """The extraction + comparison pipeline must not be vacuous."""

    def test_extraction_fails_visibly_on_empty_source(self):
        """An empty or drifted source block must raise, never return {}."""
        with self.assertRaises(AssertionError):
            _extract_primary_nav_array("const TABS = [\n];", "TABS")
        with self.assertRaises(AssertionError):
            _extract_page_meta_record("const PAGE_META = {\n};")
        with self.assertRaises(AssertionError):
            _extract_demo_reference("no scroll area boundary here")

    def test_primary_label_drift_is_detected(self):
        """Changing one primary label in one surface must surface a mismatch."""
        mutated = self.bottom_nav_src.replace('label: "Archive"', 'label: "Events"')
        self.assertNotEqual(
            mutated, self.bottom_nav_src,
            "drift fixture did not apply — expected bottom-nav Archive label",
        )
        drifted = _extract_primary_nav_array(mutated, "TABS")
        problems = _primary_label_mismatches(
            self.primary_ids, self.sidebar_primary, drifted, self.page_meta,
        )
        self.assertTrue(
            any(p.startswith("events:") for p in problems),
            f"mutated bottom-nav Archive label was not detected: {problems!r}",
        )

    def test_reference_label_drift_is_detected(self):
        """A demo title drift in the top bar must break label agreement."""
        mutated = self.top_bar_src.replace(
            'title: "Section C Demo"', 'title: "Demo Gallery"',
        )
        self.assertNotEqual(
            mutated, self.top_bar_src,
            "drift fixture did not apply — expected top-bar Section C Demo title",
        )
        drifted_meta = _extract_page_meta_record(mutated)
        ref = _extract_demo_reference(self.sidebar_src)
        self.assertNotEqual(
            ref["expanded_label"], drifted_meta["demo"],
            "reference-label drift must be detectable: sidebar reference label "
            "no longer distinguishes a mutated top-bar demo title",
        )


if __name__ == "__main__":
    unittest.main()
