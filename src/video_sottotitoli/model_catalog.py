"""Verified model metadata, provider availability and local price conversion.

The provider model endpoints deliberately do not act as a pricing API.  This
module therefore keeps the executable list limited to reviewed metadata while
still reporting newly discovered account-visible models to the interface.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .api_client import RemoteAPIError, list_provider_models
from .platform import config_dir

CATALOG_URL = (
    "https://raw.githubusercontent.com/Dago86/srt-compass/main/"
    "src/video_sottotitoli/model_catalog.json"
)
ECB_USD_RATE_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
CATALOG_TTL = timedelta(hours=24)
CACHE_PATH = config_dir() / "model-catalog.json"
EXCHANGE_CACHE_PATH = config_dir() / "usd-eur-rate.json"


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class ExchangeRate:
    usd_per_eur: float
    date: str
    source: str = "ECB"

    def usd_to_eur(self, usd: float) -> float:
        return usd / self.usd_per_eur


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def validate_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("providers"), dict):
        raise CatalogError("Formato del catalogo non valido.")
    for provider, record in catalog["providers"].items():
        if not isinstance(provider, str) or not isinstance(record, dict):
            raise CatalogError("Provider non valido nel catalogo.")
        models = record.get("models")
        if not isinstance(models, list):
            raise CatalogError("Elenco modelli non valido.")
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                raise CatalogError("Modello non valido nel catalogo.")
            price = model.get("pricing")
            if not (model.get("responses") and model.get("structured_output")
                    and isinstance(price, dict)):
                raise CatalogError("Metadati incompleti per il modello.")
            for field in ("input", "output"):
                value = price.get(field)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise CatalogError("Tariffa non valida nel catalogo.")
    return catalog


def bundled_catalog() -> dict[str, Any]:
    data = json.loads(files("video_sottotitoli").joinpath("model_catalog.json").read_text("utf-8"))
    return validate_catalog(data)


def catalog_from_disk() -> tuple[dict[str, Any], bool]:
    cached = _read_json(CACHE_PATH)
    if cached:
        try:
            return validate_catalog(cached), True
        except CatalogError:
            pass
    return bundled_catalog(), False


def catalog_is_stale(catalog: dict[str, Any], now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    try:
        updated = datetime.fromisoformat(str(catalog.get("downloaded_at", "")))
    except ValueError:
        return True
    return updated.tzinfo is None or now - updated.astimezone(UTC) >= CATALOG_TTL


def download_catalog(timeout: float = 10.0) -> dict[str, Any]:
    request = Request(CATALOG_URL, headers={"User-Agent": "srt-compass/0.17.0"})
    with urlopen(request, timeout=timeout) as response:
        catalog = json.loads(response.read().decode("utf-8"))
    catalog = validate_catalog(catalog)
    catalog["downloaded_at"] = datetime.now(UTC).isoformat()
    _atomic_json(CACHE_PATH, catalog)
    return catalog


def refresh_catalog_if_due(force: bool = False) -> tuple[dict[str, Any], bool, str | None]:
    catalog, cached = catalog_from_disk()
    if not force and cached and not catalog_is_stale(catalog):
        return catalog, False, None
    try:
        return download_catalog(), True, None
    except (OSError, ValueError, CatalogError) as exc:
        return catalog, False, str(exc)


def verified_models(catalog: dict[str, Any], provider: str) -> tuple[dict[str, Any], ...]:
    provider_data = catalog.get("providers", {}).get(provider, {})
    models = provider_data.get("models", []) if isinstance(provider_data, dict) else []
    return tuple(dict(model) for model in models if isinstance(model, dict))


def model_metadata(catalog: dict[str, Any], provider: str, model_id: str) -> dict[str, Any] | None:
    return next((model for model in verified_models(catalog, provider) if model["id"] == model_id), None)


def executable_model_ids(catalog: dict[str, Any], provider: str, available: set[str] | None = None) -> tuple[str, ...]:
    models = verified_models(catalog, provider)
    return tuple(model["id"] for model in models if available is None or model["id"] in available)


def is_deepseek_peak(now: datetime | None = None) -> bool:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return moment.weekday() < 5 and (1 <= moment.hour < 4 or 6 <= moment.hour < 10)


def model_rates(catalog: dict[str, Any], provider: str, model_id: str, now: datetime | None = None) -> tuple[float, float, str]:
    model = model_metadata(catalog, provider, model_id)
    if not model:
        raise CatalogError("Modello non verificato: prezzo o compatibilità mancanti.")
    pricing = model["pricing"]
    if provider == "deepseek" and not is_deepseek_peak(now) and "off_peak_input" in pricing:
        return float(pricing["off_peak_input"]), float(pricing["off_peak_output"]), "off_peak"
    return float(pricing["input"]), float(pricing["output"]), "peak" if provider == "deepseek" else "standard"


def quality_label(catalog: dict[str, Any], provider: str, model_id: str) -> tuple[str, dict[str, Any] | None]:
    model = model_metadata(catalog, provider, model_id)
    if not model or not model.get("quality_evidence"):
        return "unrated", None
    return str(model.get("quality", "unrated")), dict(model["quality_evidence"])


def discover_models(api_keys: dict[str, str], timeout: float = 10.0) -> tuple[dict[str, set[str]], dict[str, str]]:
    available: dict[str, set[str]] = {}
    errors: dict[str, str] = {}
    for provider, api_key in api_keys.items():
        if not api_key:
            continue
        try:
            available[provider] = set(list_provider_models(api_key, provider, timeout=timeout))
        except RemoteAPIError as exc:
            errors[provider] = str(exc)
    return available, errors


def refresh_in_background(
    api_keys: dict[str, str], callback: Callable[[dict[str, Any], dict[str, set[str]], dict[str, str], bool], None],
    *, force: bool = False,
) -> threading.Thread:
    def work() -> None:
        catalog, updated, catalog_error = refresh_catalog_if_due(force)
        available, errors = discover_models(api_keys)
        if catalog_error:
            errors["catalog"] = catalog_error
        callback(catalog, available, errors, updated)
    thread = threading.Thread(target=work, daemon=True, name="srt-compass-model-catalog")
    thread.start()
    return thread


def load_exchange_rate() -> ExchangeRate | None:
    data = _read_json(EXCHANGE_CACHE_PATH)
    try:
        return ExchangeRate(float(data["usd_per_eur"]), str(data["date"]), str(data.get("source", "ECB"))) if data else None
    except (KeyError, TypeError, ValueError):
        return None


def refresh_exchange_rate(timeout: float = 10.0) -> ExchangeRate:
    request = Request(ECB_USD_RATE_URL, headers={"User-Agent": "srt-compass/0.17.0"})
    with urlopen(request, timeout=timeout) as response:
        root = ElementTree.fromstring(response.read())
    cube = next((element for element in root.iter() if element.attrib.get("currency") == "USD"), None)
    if cube is None:
        raise CatalogError("Il cambio USD/EUR non è disponibile nel riferimento BCE.")
    date_cube = next((element for element in root.iter() if "time" in element.attrib), None)
    rate = ExchangeRate(float(cube.attrib["rate"]), str(date_cube.attrib.get("time", "")))
    if not math.isfinite(rate.usd_per_eur) or rate.usd_per_eur <= 0:
        raise CatalogError("Il cambio BCE non è valido.")
    _atomic_json(EXCHANGE_CACHE_PATH, {"usd_per_eur": rate.usd_per_eur, "date": rate.date, "source": rate.source, "downloaded_at": datetime.now(UTC).isoformat()})
    return rate


def exchange_is_stale(now: datetime | None = None) -> bool:
    data = _read_json(EXCHANGE_CACHE_PATH)
    if not data:
        return True
    try:
        updated = datetime.fromisoformat(str(data["downloaded_at"]))
    except (KeyError, ValueError):
        return True
    return updated.tzinfo is None or (now or datetime.now(UTC)) - updated.astimezone(UTC) >= CATALOG_TTL


def refresh_exchange_if_due(force: bool = False) -> tuple[ExchangeRate | None, str | None]:
    current = load_exchange_rate()
    if current and not force and not exchange_is_stale():
        return current, None
    try:
        return refresh_exchange_rate(), None
    except (OSError, ValueError, CatalogError) as exc:
        return current, str(exc)


def format_currency(usd: float, rate: ExchangeRate | None, *, decimals: int = 4) -> str:
    if rate:
        return f"€{rate.usd_to_eur(usd):.{decimals}f} (US${usd:.{decimals}f}; BCE {rate.date})"
    return f"US${usd:.{decimals}f} (cambio BCE non disponibile)"
