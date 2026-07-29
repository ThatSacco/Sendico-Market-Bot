from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import unquote, urljoin, urlparse

from playwright.async_api import Browser, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from .models import SendicoListing

LOGGER = logging.getLogger(__name__)
PRICE_PATTERNS = [
    re.compile(r"(?:¥|JPY|円)\s*([0-9][0-9,]*)", re.I),
    re.compile(r"([0-9][0-9,]*)\s*(?:JPY|円)", re.I),
]
SELLER_PATTERNS = [
    re.compile(r"(?:positive(?:\s+ratings?)?|thumbs?\s*up|good\s+ratings?)\D{0,30}([0-9][0-9,]*)", re.I),
    re.compile(r"([0-9][0-9,]*)\s*(?:positive(?:\s+ratings?)?|thumbs?\s*up|good\s+ratings?)", re.I),
    re.compile(r"(?:良い|高評価)\D{0,20}([0-9][0-9,]*)"),
]
_MERCARI_ID = re.compile(r"m\d{8,}", re.I)
_IMAGE_EXT = re.compile(r"\.(?:jpe?g|png|webp)(?:$|\?)", re.I)


def parse_yen(text: str) -> int | None:
    for pattern in PRICE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def parse_seller_positive_ratings(text: str) -> int | None:
    values = [int(match.group(1).replace(",", "")) for pattern in SELLER_PATTERNS for match in pattern.finditer(text or "")]
    return max(values) if values else None


def listing_code(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def is_listing_image_url(url: str, code: str) -> bool:
    candidate = unquote(str(url or ""))
    if not candidate or not code or not _IMAGE_EXT.search(candidate):
        return False
    found = {item.lower() for item in _MERCARI_ID.findall(candidate)}
    return code.lower() in candidate.lower() and (not found or found == {code.lower()})


class SendicoScanner:
    def __init__(self, config: dict, limits: dict) -> None:
        self.config = config
        self.limits = limits
        self.playwright = None
        self.browser: Browser | None = None

    async def __aenter__(self) -> "SendicoScanner":
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _new_page(self) -> Page:
        if not self.browser:
            raise RuntimeError("Scanner must be used as an async context manager")
        page = await self.browser.new_page(
            viewport={"width": 1440, "height": 1200},
            locale="en-AU",
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
        )
        page.set_default_timeout(int(self.limits["search"]["page_timeout_ms"]))
        return page

    async def _goto(self, page: Page, url: str) -> None:
        timeout = int(self.limits["search"]["page_timeout_ms"])
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        except PlaywrightTimeoutError:
            if not page.url or page.url == "about:blank":
                raise
            LOGGER.warning("Navigation timed out after commit; continuing: %s", url)

    async def search(self, term: str) -> list[SendicoListing]:
        page = await self._new_page()
        try:
            await self._goto(page, self.config["category_url"])
            await self._dismiss_cookies(page)
            await self._submit_search(page, term)
            await page.wait_for_timeout(2200)
            await self._scroll(page)
            raw = await page.locator('a[href*="/shop/mercari/catalog/"]').evaluate_all(
                """
                (anchors) => anchors.map((a) => {
                  let node = a;
                  for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
                    const txt = (node.innerText || '').trim();
                    const img = node.querySelector && node.querySelector('img');
                    if (txt.length > 3 && img) return {
                      href: a.href, text: txt,
                      title: (a.innerText || a.getAttribute('title') || '').trim(),
                      image: img.currentSrc || img.src || ''
                    };
                  }
                  return {href: a.href, text: (a.innerText || '').trim(), title: '', image: ''};
                })
                """
            )
            results: list[SendicoListing] = []
            seen: set[str] = set()
            limit = int(self.limits["search"]["results_per_term"])
            for item in raw:
                url = str(item.get("href") or "")
                if not url or url in seen or "/categories/" in url:
                    continue
                price = parse_yen(str(item.get("text") or ""))
                if price is None:
                    continue
                seen.add(url)
                results.append(SendicoListing(
                    code=listing_code(url),
                    url=url,
                    title=str(item.get("title") or str(item.get("text") or "").splitlines()[0]).strip(),
                    price_yen=price,
                    image_urls=[str(item["image"])] if item.get("image") else [],
                    raw_text=str(item.get("text") or ""),
                ))
                if len(results) >= limit:
                    break
            return results
        finally:
            await page.close()

    async def _scroll(self, page: Page) -> None:
        maximum = int(self.limits["search"]["max_scroll_rounds"])
        stable_required = int(self.limits["search"]["stable_rounds_before_stop"])
        pause = int(self.limits["search"]["scroll_pause_ms"])
        raw_limit = int(self.limits["search"]["raw_links_per_term"])
        previous = -1
        stable = 0
        for round_number in range(maximum + 1):
            count = await page.locator('a[href*="/shop/mercari/catalog/"]').count()
            LOGGER.info("Search load round %d: %d listing links", round_number, count)
            if count >= raw_limit:
                return
            stable = stable + 1 if count <= previous else 0
            if stable >= stable_required:
                return
            previous = count
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(pause)

    async def hydrate(self, listing: SendicoListing) -> SendicoListing:
        page = await self._new_page()
        try:
            await self._goto(page, listing.url)
            await self._dismiss_cookies(page)
            await page.wait_for_timeout(1300)
            body = await page.locator("body").inner_text()
            heading = page.locator("h1").first
            if await heading.count():
                listing.title = (await heading.inner_text()).strip() or listing.title
            urls = await page.locator("img").evaluate_all(
                """
                (imgs) => imgs.flatMap((img) => [
                  img.currentSrc, img.src, img.getAttribute('data-src'), img.getAttribute('data-original')
                ]).filter(Boolean)
                """
            )
            selected: list[str] = []
            for url in urls:
                absolute = urljoin(listing.url, str(url))
                if is_listing_image_url(absolute, listing.code) and absolute not in selected:
                    selected.append(absolute)
            if not selected:
                html = (await page.content()).replace("\\/", "/")
                for url in re.findall(r"https?://[^\"'\s<>]+?\.(?:jpe?g|png|webp)(?:\?[^\"'\s<>]*)?", html, re.I):
                    if is_listing_image_url(url, listing.code) and url not in selected:
                        selected.append(url)
            listing.image_urls = list(dict.fromkeys([*listing.image_urls, *selected]))
            listing.description = body
            listing.raw_text = body
            listing.seller_positive_ratings = parse_seller_positive_ratings(body)
            if listing.price_yen <= 0:
                listing.price_yen = parse_yen(body) or 0
            return listing
        finally:
            await page.close()

    async def _submit_search(self, page: Page, term: str) -> None:
        for selector in ['input[type="search"]', 'input[placeholder*="Search" i]', 'input[aria-label*="Search" i]', 'input[name="search"]']:
            locator = page.locator(selector).first
            if await locator.count() and await locator.is_visible():
                await locator.fill(term)
                await locator.press("Enter")
                return
        separator = "&" if "?" in page.url else "?"
        await self._goto(page, f"{page.url}{separator}search={term}")

    @staticmethod
    async def _dismiss_cookies(page: Page) -> None:
        for label in ["Accept", "Accept all", "I agree", "Got it"]:
            button = page.get_by_role("button", name=re.compile(label, re.I)).first
            try:
                if await button.count() and await button.is_visible():
                    await button.click()
                    await asyncio.sleep(0.1)
                    return
            except Exception:
                continue
