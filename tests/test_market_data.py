"""
tests/test_market_data.py

D2C — provider-identity resolution for source_provider stamping.

Covers the "smallest reliable identity" contract:
  * each real provider self-declares a ``provider_name``
    (``yfinance`` / ``polygon`` / ``fallback:<arm>``);
  * ``resolve_provider_identity`` returns that name, normalized, or
    ``None`` for any provider that declares no usable name — we never
    guess from the class, so an unrecognized provider is recorded as
    unknown (NULL → ``legacy_unknown``) rather than mislabelled.

No network: PolygonProvider is constructed with a dummy key and never
fetched; YFinanceProvider is never asked to download.
"""
from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")

from market_data import (
    FallbackProvider,
    PolygonProvider,
    YFinanceProvider,
    resolve_provider_identity,
)


class _NamelessProvider:
    """A Protocol-shaped provider with no ``provider_name`` attribute."""

    def fetch_daily(self, ticker, *, period=None, start=None, end=None, auto_adjust=True):
        return None

    def fetch_info(self, ticker):
        return {}


class _NamedProvider(_NamelessProvider):
    def __init__(self, name):
        self.provider_name = name


class TestProviderNameDeclared(unittest.TestCase):
    def test_yfinance_declares_yfinance(self) -> None:
        self.assertEqual(YFinanceProvider().provider_name, "yfinance")

    def test_polygon_declares_polygon(self) -> None:
        # Construction does not call the network.
        self.assertEqual(PolygonProvider("dummy-key").provider_name, "polygon")


class TestResolveProviderIdentity(unittest.TestCase):
    def test_yfinance(self) -> None:
        self.assertEqual(resolve_provider_identity(YFinanceProvider()), "yfinance")

    def test_polygon(self) -> None:
        self.assertEqual(
            resolve_provider_identity(PolygonProvider("dummy-key")), "polygon",
        )

    def test_named_fake(self) -> None:
        self.assertEqual(
            resolve_provider_identity(_NamedProvider("test_provider")),
            "test_provider",
        )

    def test_nameless_provider_is_unknown(self) -> None:
        self.assertIsNone(resolve_provider_identity(_NamelessProvider()))

    def test_blank_name_is_unknown(self) -> None:
        self.assertIsNone(resolve_provider_identity(_NamedProvider("   ")))

    def test_non_string_name_is_unknown(self) -> None:
        self.assertIsNone(resolve_provider_identity(_NamedProvider(123)))

    def test_none_is_unknown(self) -> None:
        self.assertIsNone(resolve_provider_identity(None))

    def test_name_is_stripped(self) -> None:
        self.assertEqual(
            resolve_provider_identity(_NamedProvider("  polygon  ")), "polygon",
        )


class TestFallbackProviderIdentity(unittest.TestCase):
    def test_fallback_primary_arm(self) -> None:
        fp = FallbackProvider(
            primary=PolygonProvider("dummy-key"), secondary=YFinanceProvider(),
        )
        self.assertEqual(fp.last_source, "primary")  # default before any fetch
        self.assertEqual(resolve_provider_identity(fp), "fallback:polygon")

    def test_fallback_secondary_arm(self) -> None:
        fp = FallbackProvider(
            primary=PolygonProvider("dummy-key"), secondary=YFinanceProvider(),
        )
        fp.last_source = "fallback"
        self.assertEqual(resolve_provider_identity(fp), "fallback:yfinance")

    def test_fallback_nameless_arm_is_unknown(self) -> None:
        fp = FallbackProvider(
            primary=_NamelessProvider(), secondary=YFinanceProvider(),
        )
        # Active arm (primary) declares no name → no reliable identity.
        self.assertIsNone(resolve_provider_identity(fp))

    def test_fallback_secondary_none(self) -> None:
        fp = FallbackProvider(primary=YFinanceProvider(), secondary=None)
        self.assertEqual(resolve_provider_identity(fp), "fallback:yfinance")


if __name__ == "__main__":
    unittest.main()
