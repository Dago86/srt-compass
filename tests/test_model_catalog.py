from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import video_sottotitoli.model_catalog as model_catalog_module
from video_sottotitoli.model_catalog import (
    CatalogError,
    ExchangeRate,
    bundled_catalog,
    discover_models,
    executable_model_ids,
    format_currency,
    is_deepseek_peak,
    model_rates,
    quality_label,
    validate_catalog,
)


class ModelCatalogTests(unittest.TestCase):
    def test_bundled_catalog_only_exposes_reviewed_structured_models(self) -> None:
        catalog = bundled_catalog()
        models = executable_model_ids(catalog, "openai")
        self.assertIn("gpt-6.1-sol", models)
        self.assertNotIn("gpt-6-astra", models)
        self.assertEqual(quality_label(catalog, "openai", "gpt-6.1-sol")[0], "advanced")

    def test_account_availability_filters_the_selectable_models(self) -> None:
        catalog = bundled_catalog()
        self.assertEqual(
            executable_model_ids(catalog, "deepseek", {"deepseek-flash", "other"}),
            ("deepseek-flash",),
        )

    def test_deepseek_price_uses_the_active_time_band(self) -> None:
        catalog = bundled_catalog()
        peak = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)
        off_peak = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
        self.assertTrue(is_deepseek_peak(peak))
        self.assertFalse(is_deepseek_peak(off_peak))
        self.assertEqual(model_rates(catalog, "deepseek", "deepseek-flash", peak), (0.3, 1.2, "peak"))
        self.assertEqual(model_rates(catalog, "deepseek", "deepseek-flash", off_peak), (0.15, 0.6, "off_peak"))

    def test_currency_display_keeps_usd_as_auditable_detail(self) -> None:
        rate = ExchangeRate(1.2, "2026-10-10")
        self.assertEqual(format_currency(1.2, rate), "€1.0000 (US$1.2000; BCE 2026-10-10)")
        self.assertIn("cambio BCE non disponibile", format_currency(1.2, None))

    def test_invalid_catalog_is_rejected_before_it_can_be_saved(self) -> None:
        catalog = bundled_catalog()
        catalog["providers"]["openai"]["models"][0]["pricing"]["input"] = -1
        with self.assertRaises(CatalogError):
            validate_catalog(catalog)

    def test_discovery_never_uses_missing_provider_keys(self) -> None:
        with patch("video_sottotitoli.model_catalog.list_provider_models") as list_models:
            list_models.return_value = []
            available, errors = discover_models({"openai": "", "deepseek": "key"})
        self.assertEqual(available, {"deepseek": set()})
        self.assertEqual(errors, {})
        list_models.assert_called_once_with("key", "deepseek", timeout=10.0)

    def test_offline_refresh_preserves_the_last_valid_catalog(self) -> None:
        catalog = bundled_catalog()
        catalog["downloaded_at"] = datetime.now(UTC).isoformat()
        with TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "model-catalog.json"
            cache_path.write_text(json.dumps(catalog), encoding="utf-8")
            with (
                patch.object(model_catalog_module, "CACHE_PATH", cache_path),
                patch("video_sottotitoli.model_catalog.urlopen", side_effect=OSError("offline")),
            ):
                restored, updated, error = model_catalog_module.refresh_catalog_if_due(force=True)
        self.assertFalse(updated)
        self.assertEqual(restored["catalog_version"], catalog["catalog_version"])
        self.assertIn("offline", error or "")


if __name__ == "__main__":
    unittest.main()
