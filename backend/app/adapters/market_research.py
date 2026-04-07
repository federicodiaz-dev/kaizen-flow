from __future__ import annotations

import html as html_lib
import json
import re
import unicodedata
from typing import Any
from urllib.parse import quote_plus

from app.clients.mercadolibre import MercadoLibreClient
from app.core.exceptions import MercadoLibreAPIError


SITE_WEB_DOMAINS: dict[str, str] = {
    "MLA": "mercadolibre.com.ar",
    "MLB": "mercadolivre.com.br",
    "MLM": "mercadolibre.com.mx",
    "MLC": "mercadolibre.cl",
    "MCO": "mercadolibre.com.co",
    "MLU": "mercadolibre.com.uy",
    "MPE": "mercadolibre.com.pe",
    "MEC": "mercadolibre.com.ec",
}

SITE_LISTING_HOSTS: dict[str, str] = {
    "MLA": "listado.mercadolibre.com.ar",
    "MLB": "lista.mercadolivre.com.br",
    "MLM": "listado.mercadolibre.com.mx",
    "MLC": "listado.mercadolibre.cl",
    "MCO": "listado.mercadolibre.com.co",
    "MLU": "listado.mercadolibre.com.uy",
    "MPE": "listado.mercadolibre.com.pe",
    "MEC": "listado.mercadolibre.com.ec",
}

ITEM_ID_PATTERN = re.compile(r"\b([A-Z]{3})(?:-)?(\d{9,13})\b")
WID_ITEM_ID_PATTERN = re.compile(r"[?&]wid=([A-Z]{3}\d{9,13})\b", re.IGNORECASE)
JSON_LD_PATTERN = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
META_TAG_PATTERN = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
META_ATTR_PATTERN = re.compile(r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)
ANCHOR_PATTERN = re.compile(
    r"<a[^>]+href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<body>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"<[^>]+>")
TITLE_TAG_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H1_PATTERN = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
PRICE_PATTERN = re.compile(r"(?P<value>\d+(?:[\.,]\d+)?)")
IGNORED_PAGE_PATH_PATTERNS = (
    "/jms/",
    "/login",
    "/nav-header",
    "/official-store/",
    "/tienda/",
    "/perfil/",
    "/gz/",
)
IGNORED_ANCHOR_TEXTS = {
    "ingresa",
    "ingresá",
    "mercado libre",
    "ver mas",
    "ver más",
    "comprar",
    "publicidad",
}


def _normalize_text(value: str | None) -> str:
    raw = str(value or "").strip()
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-")
    ascii_text = re.sub(r"-{2,}", "-", ascii_text)
    return ascii_text.lower()


def _site_domain(site_id: str) -> str:
    return SITE_WEB_DOMAINS.get(site_id.upper(), "mercadolibre.com")


def _listing_host(site_id: str) -> str:
    return SITE_LISTING_HOSTS.get(site_id.upper(), f"listado.{_site_domain(site_id)}")


def _search_slug(query: str) -> str:
    slug = _normalize_text(query)
    return slug or quote_plus(query.strip())


def _clean_html_text(value: str | None) -> str:
    if not value:
        return ""
    text = TAG_PATTERN.sub(" ", html_lib.unescape(value))
    return re.sub(r"\s+", " ", text).strip()


def _extract_item_id(value: str | None, site_id: str) -> str | None:
    raw = str(value or "")
    wid_match = WID_ITEM_ID_PATTERN.search(raw.upper())
    if wid_match:
        return wid_match.group(1).upper()
    match = ITEM_ID_PATTERN.search(raw.upper())
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return None


def _looks_like_listing_href(href: str) -> bool:
    lowered = href.lower()
    if any(fragment in lowered for fragment in IGNORED_PAGE_PATH_PATTERNS):
        return False
    return "/mla-" in lowered or "/p/" in lowered or "wid=mla" in lowered


def _looks_like_noise_text(value: str) -> bool:
    cleaned = _normalize_text(value).replace("-", " ").strip()
    if not cleaned:
        return True
    if cleaned in IGNORED_ANCHOR_TEXTS:
        return True
    return len(cleaned) < 8


def _safe_price(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = PRICE_PATTERN.search(str(value))
    if not match:
        return None
    try:
        return float(match.group("value").replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return None


def _extract_meta_map(raw_html: str) -> dict[str, str]:
    meta_map: dict[str, str] = {}
    for tag in META_TAG_PATTERN.findall(raw_html):
        attributes = {
            str(key or "").strip().lower(): html_lib.unescape(str(value or "").strip())
            for key, _, value in META_ATTR_PATTERN.findall(tag)
        }
        content = str(attributes.get("content") or "").strip()
        if not content:
            continue
        for key_name in ("property", "name", "itemprop"):
            meta_key = str(attributes.get(key_name) or "").strip().lower()
            if meta_key and meta_key not in meta_map:
                meta_map[meta_key] = content
    return meta_map


def _meta_content(meta_map: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = meta_map.get(key.lower())
        if value:
            return value
    return None


def _extract_title_from_html(raw_html: str) -> str | None:
    for pattern in (H1_PATTERN, TITLE_TAG_PATTERN):
        match = pattern.search(raw_html)
        if not match:
            continue
        title = _clean_html_text(match.group(1))
        title = re.sub(r"\s+\|\s*Mercado\s*Libre.*$", "", title, flags=re.IGNORECASE).strip()
        if title:
            return title
    return None


class MarketResearchAdapter:
    def __init__(self, client: MercadoLibreClient) -> None:
        self._client = client

    def _browser_headers(self, site_id: str, *, referer: str | None = None) -> dict[str, str]:
        headers = {
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.7",
            "Referer": referer or f"https://www.{_site_domain(site_id)}/",
        }
        return headers

    async def _request_with_fallback(
        self,
        account_key: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        prefer_public: bool = False,
        auth_only: bool = False,
        public_only: bool = False,
    ) -> Any:
        attempt_plan: list[tuple[str, bool]] = []
        if not auth_only:
            attempt_plan.extend(
                [("public", False), ("public", True)] if prefer_public else [("public", False), ("public", True)]
            )
        if not public_only:
            if prefer_public:
                attempt_plan.extend([("auth", False), ("auth", True)])
            else:
                attempt_plan = [("auth", False), ("auth", True), *attempt_plan]

        deduped_plan: list[tuple[str, bool]] = []
        seen: set[tuple[str, bool]] = set()
        for mode, include_caller_id in attempt_plan:
            key = (mode, include_caller_id if self._client.has_caller_id else False)
            if key in seen:
                continue
            seen.add(key)
            deduped_plan.append((mode, include_caller_id))

        attempt_errors: list[str] = []
        last_error: MercadoLibreAPIError | None = None
        for mode, include_caller_id in deduped_plan:
            try:
                if mode == "public":
                    return await self._client.public_request(
                        method,
                        path,
                        params=params,
                        include_caller_id=include_caller_id,
                    )
                return await self._client.request(
                    account_key,
                    method,
                    path,
                    params=params,
                    include_caller_id=include_caller_id,
                )
            except MercadoLibreAPIError as exc:
                last_error = exc
                attempt_errors.append(
                    f"{mode}{' + caller_id' if include_caller_id and self._client.has_caller_id else ''}: "
                    f"{exc.status_code} | {exc.message} | {exc.code}"
                )
                if exc.status_code not in {401, 403}:
                    raise

        if last_error is None:
            raise MercadoLibreAPIError(
                message="No se pudo ejecutar ninguna estrategia de acceso contra Mercado Libre.",
                status_code=500,
                code="market_research_unavailable",
                details={"path": path, "method": method, "params": params},
            )

        raise MercadoLibreAPIError(
            message="Todas las estrategias de acceso fallaron. " + " ; ".join(attempt_errors),
            status_code=last_error.status_code,
            code=last_error.code,
            details={
                "path": path,
                "method": method,
                "params": params,
                "attempt_errors": attempt_errors,
                "last_error": last_error.details,
            },
        )

    async def search_items(
        self,
        account_key: str,
        *,
        site_id: str,
        query: str | None,
        category_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        if query:
            params["q"] = query
        if category_id:
            params["category"] = category_id
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/sites/{site_id}/search",
            params=params,
            prefer_public=True,
        )
        return data if isinstance(data, dict) else {}

    def _extract_products_from_json_ld(self, raw_html: str, site_id: str) -> list[dict[str, Any]]:
        products: list[dict[str, Any]] = []
        for block in JSON_LD_PATTERN.findall(raw_html):
            try:
                payload = json.loads(html_lib.unescape(block.strip()))
            except json.JSONDecodeError:
                continue
            for node in payload if isinstance(payload, list) else [payload]:
                if not isinstance(node, dict):
                    continue
                items = node.get("itemListElement") if isinstance(node.get("itemListElement"), list) else None
                if items:
                    for element in items:
                        item = element.get("item") if isinstance(element, dict) else None
                        if not isinstance(item, dict):
                            continue
                        url = str(item.get("url") or item.get("@id") or "").strip()
                        item_id = _extract_item_id(url, site_id)
                        if not item_id:
                            continue
                        offers = item.get("offers")
                        if isinstance(offers, list):
                            offer = next((entry for entry in offers if isinstance(entry, dict)), {})
                        else:
                            offer = offers if isinstance(offers, dict) else {}
                        products.append(
                            {
                                "id": item_id,
                                "title": str(item.get("name") or "").strip(),
                                "price": _safe_price(offer.get("price")),
                                "currency_id": str(offer.get("priceCurrency") or "").strip() or None,
                                "thumbnail": item.get("image"),
                                "permalink": url or None,
                                "attributes": [],
                            }
                        )
                if node.get("@type") == "Product":
                    url = str(node.get("url") or node.get("@id") or "").strip()
                    item_id = _extract_item_id(url, site_id)
                    if not item_id:
                        continue
                    offers = node.get("offers")
                    if isinstance(offers, list):
                        offer = next((entry for entry in offers if isinstance(entry, dict)), {})
                    else:
                        offer = offers if isinstance(offers, dict) else {}
                    products.append(
                        {
                            "id": item_id,
                            "title": str(node.get("name") or "").strip(),
                            "price": _safe_price(offer.get("price")),
                            "currency_id": str(offer.get("priceCurrency") or "").strip() or None,
                            "thumbnail": node.get("image"),
                            "permalink": url or None,
                            "attributes": [],
                        }
                    )
        deduped: dict[str, dict[str, Any]] = {}
        for product in products:
            item_id = str(product.get("id") or "").strip()
            if not item_id:
                continue
            deduped.setdefault(item_id, product)
        return list(deduped.values())

    def _extract_products_from_anchors(self, raw_html: str, site_id: str) -> list[dict[str, Any]]:
        products: list[dict[str, Any]] = []
        for match in ANCHOR_PATTERN.finditer(raw_html):
            href = html_lib.unescape(match.group("href"))
            if not _looks_like_listing_href(href):
                continue
            item_id = _extract_item_id(href, site_id)
            if not item_id:
                continue
            body = _clean_html_text(match.group("body"))
            if _looks_like_noise_text(body):
                continue
            products.append(
                {
                    "id": item_id,
                    "title": body[:220],
                    "price": None,
                    "currency_id": None,
                    "thumbnail": None,
                    "permalink": href,
                    "attributes": [],
                }
            )
        deduped: dict[str, dict[str, Any]] = {}
        for product in products:
            item_id = str(product.get("id") or "").strip()
            if not item_id:
                continue
            deduped.setdefault(item_id, product)
        return list(deduped.values())

    async def search_items_via_web_listing(
        self,
        *,
        site_id: str,
        query: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        slug = _search_slug(query)
        listing_url = f"https://{_listing_host(site_id)}/{slug}"
        fallback_url = f"https://www.{_site_domain(site_id)}/jm/search?as_word={quote_plus(query)}"
        attempt_errors: list[str] = []
        for url in [listing_url, fallback_url]:
            try:
                html_text = await self._client.public_page_request(
                    url,
                    headers=self._browser_headers(site_id, referer=url),
                )
                items = self._extract_products_from_json_ld(html_text, site_id)
                if not items:
                    items = self._extract_products_from_anchors(html_text, site_id)
                items = items[:limit]
                if items:
                    return {
                        "results": items,
                        "paging": {"total": len(items), "offset": 0, "limit": len(items)},
                        "source_url": url,
                        "source_method": "web_listing",
                    }
                attempt_errors.append(f"{url}: sin items parseables")
            except MercadoLibreAPIError as exc:
                attempt_errors.append(f"{url}: {exc.status_code} | {exc.message} | {exc.code}")
        raise MercadoLibreAPIError(
            message="No se pudieron recuperar listados web de Mercado Libre. " + " ; ".join(attempt_errors),
            status_code=403,
            code="web_listing_search_failed",
            details={"query": query, "site_id": site_id, "attempt_errors": attempt_errors},
        )

    async def browse_category_public(
        self,
        *,
        site_id: str,
        category_name: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not category_name.strip():
            return {}
        return await self.search_items_via_web_listing(site_id=site_id, query=category_name, limit=limit)

    async def extract_related_items_from_public_page(
        self,
        *,
        site_id: str,
        permalink: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        html_text = await self._client.public_page_request(
            permalink,
            headers=self._browser_headers(site_id, referer=permalink),
        )
        items = self._extract_products_from_json_ld(html_text, site_id)
        if not items:
            items = self._extract_products_from_anchors(html_text, site_id)
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        source_item_id = _extract_item_id(permalink, site_id)
        for item in items:
            item_id = str(item.get("id") or "").strip()
            if not item_id or item_id == source_item_id or item_id in seen:
                continue
            seen.add(item_id)
            deduped.append(item)
        return {
            "results": deduped[:limit],
            "paging": {"total": len(deduped), "offset": 0, "limit": min(limit, len(deduped))},
            "source_url": permalink,
            "source_method": "public_item_page",
        }

    async def extract_item_detail_from_public_page(
        self,
        *,
        site_id: str,
        permalink: str,
    ) -> dict[str, Any]:
        html_text = await self._client.public_page_request(
            permalink,
            headers=self._browser_headers(site_id, referer=permalink),
        )
        products = self._extract_products_from_json_ld(html_text, site_id)
        meta_map = _extract_meta_map(html_text)
        page_item_id = _extract_item_id(permalink, site_id)
        selected = None
        if page_item_id:
            selected = next((entry for entry in products if str(entry.get("id") or "") == page_item_id), None)
        if selected is None and products:
            selected = products[0]
        fallback_title = _first_non_empty(
            _meta_content(meta_map, "og:title", "twitter:title", "title"),
            _extract_title_from_html(html_text),
        )
        fallback_price = _safe_price(
            _meta_content(
                meta_map,
                "product:price:amount",
                "og:price:amount",
                "twitter:data1",
                "price",
            )
        )
        fallback_currency = _first_non_empty(
            _meta_content(
                meta_map,
                "product:price:currency",
                "og:price:currency",
                "pricecurrency",
            ),
            "ARS" if site_id.upper() == "MLA" else None,
        )
        fallback_thumbnail = _first_non_empty(
            _meta_content(meta_map, "og:image", "twitter:image"),
        )
        if not isinstance(selected, dict) and not fallback_title:
            raise MercadoLibreAPIError(
                message="La pagina publica del item no expuso metadata estructurada utilizable.",
                status_code=404,
                code="public_item_page_parse_failed",
                details={"permalink": permalink, "site_id": site_id},
            )
        selected = selected if isinstance(selected, dict) else {}
        item_id = str(selected.get("id") or page_item_id or "").strip()
        return {
            "id": item_id or None,
            "title": _first_non_empty(selected.get("title"), fallback_title),
            "price": _safe_price(selected.get("price")) or fallback_price,
            "currency_id": _first_non_empty(selected.get("currency_id"), fallback_currency),
            "thumbnail": _first_non_empty(selected.get("thumbnail"), fallback_thumbnail),
            "permalink": _first_non_empty(selected.get("permalink"), permalink),
            "status": "active",
            "attributes": [],
            "pictures": [_first_non_empty(selected.get("thumbnail"), fallback_thumbnail)]
            if _first_non_empty(selected.get("thumbnail"), fallback_thumbnail)
            else [],
        }

    async def get_item_detail(self, account_key: str, item_id: str) -> dict[str, Any]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/items/{item_id}",
            params={"include_attributes": "all"},
            prefer_public=True,
        )
        return data if isinstance(data, dict) else {}

    async def get_owned_item_detail(self, account_key: str, item_id: str) -> dict[str, Any]:
        data = await self._client.request(
            account_key,
            "GET",
            f"/items/{item_id}",
            params={"include_attributes": "all"},
        )
        return data if isinstance(data, dict) else {}

    async def get_item_description(self, account_key: str, item_id: str) -> dict[str, Any]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/items/{item_id}/description",
            prefer_public=True,
        )
        return data if isinstance(data, dict) else {}

    async def get_category(self, account_key: str, category_id: str) -> dict[str, Any]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/categories/{category_id}",
            prefer_public=True,
        )
        return data if isinstance(data, dict) else {}

    async def get_category_attributes(self, account_key: str, category_id: str) -> list[dict[str, Any]]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/categories/{category_id}/attributes",
            prefer_public=True,
        )
        return data if isinstance(data, list) else []

    async def get_category_technical_specs(
        self,
        account_key: str,
        category_id: str,
    ) -> dict[str, Any]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/categories/{category_id}/technical_specs/input",
            prefer_public=True,
        )
        return data if isinstance(data, dict) else {}

    async def predict_category(
        self,
        account_key: str,
        *,
        site_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            "/marketplace/domain_discovery/search",
            params={"site_id": site_id, "q": query},
            prefer_public=True,
        )
        return data if isinstance(data, list) else []

    async def get_trends(
        self,
        account_key: str,
        *,
        site_id: str,
        category_id: str | None = None,
    ) -> list[dict[str, Any]]:
        path = f"/trends/{site_id}"
        if category_id:
            path = f"{path}/{category_id}"
        data = await self._request_with_fallback(
            account_key,
            "GET",
            path,
            prefer_public=True,
        )
        return data if isinstance(data, list) else []

    async def get_listing_health(self, account_key: str, item_id: str) -> dict[str, Any]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/items/{item_id}/health",
            auth_only=True,
        )
        return data if isinstance(data, dict) else {}

    async def get_listing_health_actions(self, account_key: str, item_id: str) -> list[dict[str, Any]]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/items/{item_id}/health/actions",
            auth_only=True,
        )
        return data if isinstance(data, list) else []

    async def get_listing_exposures(self, account_key: str, *, site_id: str) -> list[dict[str, Any]]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/sites/{site_id}/listing_exposures",
            prefer_public=True,
        )
        return data if isinstance(data, list) else []

    async def get_listing_type_detail(
        self,
        account_key: str,
        *,
        site_id: str,
        listing_type_id: str,
    ) -> dict[str, Any]:
        data = await self._request_with_fallback(
            account_key,
            "GET",
            f"/sites/{site_id}/listing_types/{listing_type_id}",
            prefer_public=True,
        )
        return data if isinstance(data, dict) else {}
