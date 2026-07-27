from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse

from playwright.async_api import Browser, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from .models import SendicoListing

LOGGER = logging.getLogger(__name__)

PRICE_PATTERNS = [
    re.compile(r"(?:¥|JPY|円)\s*([0-9][0-9,]*)", re.IGNORECASE),
    re.compile(r"([0-9][0-9,]*)\s*(?:JPY|円)", re.IGNORECASE),
]
SELLER_PATTERNS = [
    re.compile(r"(?:positive(?:\s+ratings?)?|thumbs?\s*up|good\s+ratings?)\D{0,30}([0-9][0-9,]*)", re.IGNORECASE),
    re.compile(r"([0-9][0-9,]*)\s*(?:positive(?:\s+ratings?)?|thumbs?\s*up|good\s+ratings?)", re.IGNORECASE),
    re.compile(r"(?:良い|高評価)\D{0,20}([0-9][0-9,]*)"),
    re.compile(r"([0-9][0-9,]*)\s*(?:良い|高評価)"),
]


def parse_yen(text: str) -> int | None:
    for pattern in PRICE_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1).replace(",", ""))
    # Sendico cards often show the yen amount before a converted amount in brackets.
    match = re.search(r"(?:^|\s)((?:[0-9]{1,3}(?:,[0-9]{3})+)|(?:[0-9]{3,}))(?=\s*\()", text)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def parse_seller_positive_ratings(text: str) -> int | None:
    candidates: list[int] = []
    for pattern in SELLER_PATTERNS:
        for match in pattern.finditer(text):
            value = int(match.group(1).replace(",", ""))
            if 0 <= value <= 10_000_000:
                candidates.append(value)
    return max(candidates) if candidates else None


def listing_code(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1]


class SendicoMercariScanner:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.playwright = None
        self.browser: Browser | None = None

    async def __aenter__(self) -> "SendicoMercariScanner":
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
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/130 Safari/537.36"
            ),
        )
        page.set_default_timeout(int(self.config.get("page_timeout_ms", 60_000)))
        return page


    async def _goto_resilient(self, page: Page, url: str) -> None:
        """Navigate without requiring every Sendico resource to finish loading."""
        timeout = int(self.config.get("page_timeout_ms", 60_000))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return
        except PlaywrightTimeoutError as exc:
            # Sendico sometimes keeps the document load pending even though the
            # useful HTML has arrived. If navigation committed, continue with it.
            if page.url and page.url != "about:blank":
                LOGGER.warning(
                    "Sendico navigation timed out after %d ms but page committed; "
                    "continuing: %s",
                    timeout,
                    url,
                )
                return
            LOGGER.warning(
                "Sendico DOM navigation timed out; retrying after first response: %s",
                url,
            )
            try:
                await page.goto(url, wait_until="commit", timeout=timeout)
            except PlaywrightTimeoutError:
                raise exc

    async def search(self, term: str) -> list[SendicoListing]:
        page = await self._new_page()
        try:
            await self._goto_resilient(page, self.config["category_url"])
            await self._dismiss_cookies(page)
            await self._submit_search(page, term)
            await page.wait_for_timeout(2500)
            await self._scroll_search_results(page)
            raw = await page.locator('a[href*="/shop/mercari/catalog/"]').evaluate_all(
                """
                (anchors) => anchors.map((a) => {
                  let node = a;
                  for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
                    const txt = (node.innerText || '').trim();
                    const img = node.querySelector && node.querySelector('img');
                    if (txt.length > 3 && img) {
                      return {
                        href: a.href,
                        text: txt,
                        title: (a.innerText || a.getAttribute('title') || '').trim(),
                        image: img.currentSrc || img.src || ''
                      };
                    }
                  }
                  return {href: a.href, text: (a.innerText || '').trim(), title: '', image: ''};
                })
                """
            )
            results: list[SendicoListing] = []
            seen: set[str] = set()
            result_limit = int(self.config.get("max_results_per_search", 20))
            for item in raw:
                url = item.get("href", "")
                if not url or url in seen or "/categories/" in url:
                    continue
                seen.add(url)
                price_yen = parse_yen(item.get("text", ""))
                if price_yen is None:
                    continue
                title = item.get("title") or item.get("text", "").splitlines()[0]
                results.append(
                    SendicoListing(
                        code=listing_code(url),
                        url=url,
                        title=title.strip(),
                        price_yen=price_yen,
                        image_urls=[item["image"]] if item.get("image") else [],
                        raw_text=item.get("text", ""),
                    )
                )
                if result_limit > 0 and len(results) >= result_limit:
                    break
            return results
        finally:
            await page.close()

    async def _scroll_search_results(self, page: Page) -> None:
        """Load search results until the number of unique listing links stabilises.

        ``maximum_scroll_rounds`` and the result limits accept ``0`` as
        unlimited. A stable-result threshold still ends the scan once Sendico
        stops adding unique Mercari listing links.
        """

        maximum_rounds = int(self.config.get("maximum_scroll_rounds", 30))
        stable_rounds_required = max(
            1,
            int(self.config.get("stable_scroll_rounds_before_stop", 3)),
        )
        scroll_pause_ms = max(250, int(self.config.get("scroll_pause_ms", 1500)))

        previous_count = -1
        stable_rounds = 0
        round_number = 0

        while True:
            current_count = await page.locator(
                'a[href*="/shop/mercari/catalog/"]'
            ).evaluate_all(
                """
                (anchors) => new Set(
                  anchors
                    .map((a) => a.href || '')
                    .filter((href) => href && !href.includes('/categories/'))
                ).size
                """
            )

            if current_count <= previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0

            LOGGER.info(
                "Sendico search load round %d: %d unique listing links",
                round_number,
                current_count,
            )

            if stable_rounds >= stable_rounds_required:
                LOGGER.info(
                    "Sendico stopped loading new results at %d unique links",
                    current_count,
                )
                return

            if maximum_rounds > 0 and round_number >= maximum_rounds:
                LOGGER.info(
                    "Reached configured Sendico scroll limit of %d rounds",
                    maximum_rounds,
                )
                return

            previous_count = current_count
            round_number += 1

            # Some versions of the page expose a button instead of relying only
            # on infinite scrolling. Click it when available, then scroll to the
            # current document bottom.
            load_more = page.get_by_role(
                "button",
                name=re.compile(r"load more|show more|more results|もっと見る", re.IGNORECASE),
            ).first
            try:
                if await load_more.count() and await load_more.is_visible():
                    await load_more.click()
            except Exception:  # noqa: BLE001 - scrolling can still continue
                pass

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(scroll_pause_ms)

    async def hydrate(self, listing: SendicoListing) -> SendicoListing:
        page = await self._new_page()
        try:
            await self._goto_resilient(page, listing.url)
            await self._dismiss_cookies(page)
            try:
                await page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                # Some Sendico pages keep background requests open indefinitely.
                pass
            await page.mouse.wheel(0, 900)
            await page.wait_for_timeout(1_800)

            body_text = await page.locator("body").inner_text()
            heading = page.locator("h1").first
            if await heading.count():
                text = (await heading.inner_text()).strip()
                if text:
                    listing.title = text

            meta_images = await page.locator(
                'meta[property="og:image"], meta[name="twitter:image"], '
                'meta[property="twitter:image"]'
            ).evaluate_all(
                r"""
                (nodes) => nodes.map((node) => node.content || '').filter(Boolean)
                """
            )
            images = await page.locator("img").evaluate_all(
                r"""
                (imgs) => imgs.map((img) => {
                  const srcset = (img.getAttribute('srcset') || '')
                    .split(',')
                    .map((part) => part.trim().split(/\s+/)[0])
                    .filter(Boolean);
                  const candidates = [
                    img.currentSrc,
                    img.src,
                    img.getAttribute('data-src'),
                    img.getAttribute('data-original'),
                    img.getAttribute('data-lazy-src'),
                    srcset.length ? srcset[srcset.length - 1] : ''
                  ].filter(Boolean);
                  return {
                    candidates,
                    width: Math.max(
                      img.naturalWidth || 0,
                      img.width || 0,
                      img.clientWidth || 0
                    ),
                    height: Math.max(
                      img.naturalHeight || 0,
                      img.height || 0,
                      img.clientHeight || 0
                    ),
                    alt: img.alt || ''
                  };
                })
                """
            )
            background_images = await page.locator(
                '[style*="background-image"]'
            ).evaluate_all(
                r"""
                (nodes) => nodes.map((node) => {
                  const value = node.style.backgroundImage || '';
                  const match = value.match(/url\(["']?(.*?)["']?\)/i);
                  return match ? match[1] : '';
                }).filter(Boolean)
                """
            )

            selected: list[str] = []

            def add_image(src: str, alt: str = "") -> None:
                src = str(src or "").strip()
                if not src or src.startswith("data:"):
                    return
                low = f"{src} {alt}".lower()
                if any(
                    token in low
                    for token in [
                        "logo",
                        "avatar",
                        "icon",
                        "flag",
                        "favicon",
                        "payment",
                    ]
                ):
                    return
                absolute = urljoin(listing.url, src)
                if absolute not in selected:
                    selected.append(absolute)

            for src in meta_images:
                add_image(src)

            for image in images:
                width = int(image.get("width", 0) or 0)
                height = int(image.get("height", 0) or 0)
                if max(width, height) < 120:
                    continue
                for src in image.get("candidates", []):
                    add_image(src, str(image.get("alt", "")))

            for src in background_images:
                add_image(src)

            # Last-resort extraction for image URLs embedded in page state JSON.
            if not selected:
                html = (await page.content()).replace("\\/", "/")
                for src in re.findall(
                    r'https?://[^"\'\s<>]+?\.(?:jpe?g|png|webp)'
                    r'(?:\?[^"\'\s<>]*)?',
                    html,
                    flags=re.IGNORECASE,
                ):
                    add_image(src)

            listing.image_urls = list(
                dict.fromkeys([*listing.image_urls, *selected])
            )
            listing.description = body_text
            listing.raw_text = body_text
            listing.seller_positive_ratings = parse_seller_positive_ratings(
                body_text
            )
            if listing.seller_positive_ratings is None:
                listing.seller_positive_ratings = await self._seller_rating_from_profile(
                    page
                )
            if listing.price_yen <= 0:
                parsed_price = parse_yen(body_text)
                if parsed_price:
                    listing.price_yen = parsed_price
            return listing
        finally:
            await page.close()

    async def _seller_rating_from_profile(self, page: Page) -> int | None:
        links = await page.locator(
            'a[href*="seller" i], a[href*="profile" i], a[href*="user" i]'
        ).evaluate_all(
            """
            (anchors) => anchors.map((a) => ({href: a.href, text: (a.innerText || '').trim()}))
            """
        )
        for item in links[:5]:
            href = item.get("href", "")
            if not href or "sendico.com" not in href or "/shop/mercari" not in href:
                continue
            profile = await self._new_page()
            try:
                await self._goto_resilient(profile, href)
                await profile.wait_for_timeout(1000)
                value = parse_seller_positive_ratings(await profile.locator("body").inner_text())
                if value is not None:
                    return value
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("Seller profile lookup failed for %s: %s", href, exc)
            finally:
                await profile.close()
        return None

    async def _submit_search(self, page: Page, term: str) -> None:
        selectors = [
            'input[type="search"]',
            'input[placeholder*="Search" i]',
            'input[aria-label*="Search" i]',
            'input[name="search"]',
        ]
        search_input = None
        for selector in selectors:
            locator = page.locator(selector).first
            if await locator.count() and await locator.is_visible():
                search_input = locator
                break
        if search_input is None:
            # Last-resort URL query. This may need adjustment if Sendico changes its UI.
            separator = "&" if "?" in page.url else "?"
            await self._goto_resilient(page, f"{page.url}{separator}search={term}")
            return
        await search_input.fill(term)
        await search_input.press("Enter")

    @staticmethod
    async def _dismiss_cookies(page: Page) -> None:
        for label in ["Accept", "Accept all", "I agree", "Got it"]:
            button = page.get_by_role("button", name=re.compile(label, re.IGNORECASE)).first
            try:
                if await button.count() and await button.is_visible():
                    await button.click()
                    await asyncio.sleep(0.2)
                    return
            except Exception:  # noqa: BLE001
                continue
