from __future__ import annotations

import logging

import planetary_computer
import pystac
import pystac_client

from app.config import settings

logger = logging.getLogger(__name__)

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

_catalog = None


def catalog() -> pystac_client.Client:
    global _catalog
    if _catalog is None:
        if settings.pc_sdk_subscription_key:
            planetary_computer.settings.set_subscription_key(settings.pc_sdk_subscription_key)
        _catalog = pystac_client.Client.open(
            PC_STAC,
            modifier=planetary_computer.sign_inplace,
        )
    return _catalog


def search_items(
    collections: list[str],
    bbox: tuple[float, float, float, float],
    datetime: str | None = None,
    query: dict | None = None,
    max_items: int = 50,
) -> list[pystac.Item]:
    kwargs: dict = {
        "collections": collections,
        "bbox": list(bbox),
        "max_items": max_items,
    }
    if datetime:
        kwargs["datetime"] = datetime
    if query:
        kwargs["query"] = query
    search = catalog().search(**kwargs)
    return list(search.items())


def signed_href(item: pystac.Item, asset_key: str) -> str:
    asset = item.assets[asset_key]
    href = asset.href
    if "sig=" in href or "se=" in href:
        return href
    signed = planetary_computer.sign(asset)
    return signed.href
