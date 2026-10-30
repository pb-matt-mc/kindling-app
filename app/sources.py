"""Listing sources: ScrapeCreators (real Facebook Marketplace data) and a mock generator.

Both expose the same async interface:
  search(profile, query, cursor=None) -> (listings, next_cursor, credits)
  item(fb_id) -> (detail, credits)
  locate(text) -> (locations, credits)
  image_bytes(url) -> (bytes, extension)
"""
import hashlib
import random

import httpx

from . import config

SC_BASE = "https://api.scrapecreators.com/v1/facebook/marketplace"


class SourceError(Exception):
    pass


# --------------------------------------------------------------------------- ScrapeCreators

class ScrapeCreators:
    name = "scrapecreators"

    def __init__(self, api_key):
        self.client = httpx.AsyncClient(timeout=60, headers={"x-api-key": api_key})

    async def _get(self, path, params):
        params = {k: v for k, v in params.items() if v not in (None, "")}
        last = None
        for _ in range(2):
            try:
                r = await self.client.get(f"{SC_BASE}{path}", params=params)
            except httpx.HTTPError as e:
                last = str(e)
                continue
            if r.status_code == 200:
                body = r.json()
                return body, int(body.get("credits_charged") or 0)
            if r.status_code in (401, 403):
                raise SourceError("ScrapeCreators rejected the API key (or credits ran out).")
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        raise SourceError(f"ScrapeCreators request failed: {last}")

    async def search(self, profile, query, cursor=None):
        body, credits = await self._get("/search", {
            "query": query,
            "lat": profile["lat"],
            "lng": profile["lng"],
            "radius_km": profile["radius_km"],
            "min_price": int(profile["min_price"]) if profile.get("min_price") else None,
            "max_price": int(profile["max_price"]) if profile.get("max_price") else None,
            "availability": "available",
            "sort_by": "creation_time_descend",
            "cursor": cursor,
        })
        out = []
        for l in body.get("listings") or []:
            if l.get("is_sold") or l.get("is_hidden") or l.get("is_pending"):
                continue
            price = (l.get("price") or {})
            loc = (l.get("location") or {})
            out.append({
                "fb_id": str(l.get("id")),
                "url": l.get("url"),
                "title": l.get("title") or "",
                "price": price.get("amount"),
                "price_text": price.get("formatted_amount") or "",
                "location_text": loc.get("display_name") or ", ".join(
                    x for x in [loc.get("city"), loc.get("state")] if x),
                "thumb_url": (l.get("primary_photo") or {}).get("url"),
            })
        nxt = body.get("cursor") if body.get("has_next_page") else None
        return out, nxt, credits

    async def item(self, fb_id):
        body, credits = await self._get("/item", {"id": fb_id})
        attrs = body.get("attributes") or []
        condition = next((a.get("label") for a in attrs if a.get("attribute_name") == "Condition"), None)
        price = body.get("price") or {}
        return {
            "title": body.get("title"),
            "description": body.get("description") or "",
            "condition": condition,
            "fb_attributes": [{"name": a.get("attribute_name"), "value": a.get("label") or a.get("value")}
                              for a in attrs],
            "photo_urls": [p.get("url") for p in (body.get("photos") or []) if p.get("url")],
            "price": price.get("amount"),
            "price_text": price.get("formatted_amount_zeros_stripped"),
            "location_text": body.get("location_text"),
            "is_live": body.get("is_live", True) and not body.get("is_sold"),
        }, credits

    async def items(self, fb_ids):
        import asyncio
        sem = asyncio.Semaphore(4)

        async def one(i):
            async with sem:
                try:
                    return i, *(await self.item(i))
                except SourceError:
                    return i, None, 0
        res = await asyncio.gather(*(one(i) for i in fb_ids))
        return {i: d for i, d, _ in res if d}, sum(c for _, _, c in res)

    async def locate(self, text):
        body, credits = await self._get("/location/search", {"query": text})
        return [{"name": l.get("name"), "subtitle": l.get("subtitle"),
                 "lat": l.get("latitude"), "lng": l.get("longitude")}
                for l in body.get("locations") or []], credits

    async def image_bytes(self, url):
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            ext = "png" if "png" in ctype else "webp" if "webp" in ctype else "jpg"
            return r.content, ext


# --------------------------------------------------------------------------- Apify

def _dig(obj, *paths):
    """Return the first non-empty value found at any dotted path."""
    for path in paths:
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return None


def _num(v):
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


class Apify:
    """Apify's Facebook Marketplace actor. Billed per listing returned (plus a details add-on),
    so searches are capped by APIFY_RESULTS_PER_QUERY and details are fetched only for batch picks,
    all in one actor run."""
    name = "apify"

    def __init__(self, token, actor):
        self.token = token
        self.actor = actor.replace("/", "~")
        self.client = httpx.AsyncClient(timeout=330)

    async def _run(self, payload):
        url = f"https://api.apify.com/v2/acts/{self.actor}/run-sync-get-dataset-items"
        try:
            r = await self.client.post(url, params={"token": self.token}, json=payload)
        except httpx.HTTPError as e:
            raise SourceError(f"Apify request failed: {e}")
        if r.status_code in (401, 403):
            raise SourceError("Apify rejected the token (or the account is out of credit).")
        if r.status_code >= 400:
            raise SourceError(f"Apify run failed: HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data if isinstance(data, list) else []

    def _search_url(self, profile, query):
        from urllib.parse import urlencode
        params = {"query": query, "sortBy": "creation_time_descend", "exact": "false",
                  "radius": int(profile["radius_km"])}
        if profile.get("min_price"):
            params["minPrice"] = int(profile["min_price"])
        if profile.get("max_price"):
            params["maxPrice"] = int(profile["max_price"])
        slug = (profile.get("location_slug") or "philly").strip("/ ")
        return f"https://www.facebook.com/marketplace/{slug}/search/?{urlencode(params)}"

    @staticmethod
    def _basic(l):
        loc = _dig(l, "location.reverse_geocode") or {}
        price = _dig(l, "listing_price") or {}
        fb_id = str(l.get("id") or "")
        return {
            "fb_id": fb_id,
            "url": l.get("listingUrl") or f"https://www.facebook.com/marketplace/item/{fb_id}/",
            "title": l.get("custom_title") or l.get("marketplace_listing_title") or l.get("title") or "",
            "price": _num(price.get("amount")) if isinstance(price, dict) else _num(price),
            "price_text": price.get("formatted_amount", "") if isinstance(price, dict) else str(price or ""),
            "location_text": _dig(loc, "city_page.display_name") or ", ".join(
                x for x in [loc.get("city"), loc.get("state")] if x),
            "thumb_url": _dig(l, "primary_listing_photo.image.uri", "primary_listing_photo.photo_image_url"),
        }

    async def search(self, profile, query, cursor=None):
        if cursor:  # one page per query keeps per-listing billing predictable
            return [], None, 0
        n = int(config.APIFY_RESULTS_PER_QUERY)
        items = await self._run({"startUrls": [{"url": self._search_url(profile, query)}],
                                 "resultsLimit": n, "includeListingDetails": False})
        out = []
        for l in items:
            if l.get("is_sold") or l.get("is_hidden") or l.get("is_pending") or not l.get("id"):
                continue
            out.append(self._basic(l))
        return out, None, len(items)

    async def items(self, fb_ids):
        urls = [{"url": f"https://www.facebook.com/marketplace/item/{i}/"} for i in fb_ids]
        rows = await self._run({"startUrls": urls, "resultsLimit": len(urls), "includeListingDetails": True})
        out = {}
        for l in rows:
            fb_id = str(l.get("id") or "")
            if not fb_id:
                continue
            attrs = _dig(l, "attribute_data", "attributes", "listingAttributes") or []
            attrs = [{"name": a.get("attribute_name") or a.get("name"),
                      "value": a.get("label") or a.get("value")} for a in attrs if isinstance(a, dict)]
            condition = _dig(l, "condition", "condition_label") or next(
                (a["value"] for a in attrs if (a["name"] or "").lower() == "condition"), None)
            photos = _dig(l, "listing_photos", "photos", "images") or []
            photo_urls = []
            for p in photos:
                u = p if isinstance(p, str) else _dig(p, "image.uri", "uri", "url")
                if u:
                    photo_urls.append(u)
            if not photo_urls:
                thumb = _dig(l, "primary_listing_photo.image.uri")
                photo_urls = [thumb] if thumb else []
            b = self._basic(l)
            out[fb_id] = {
                "title": b["title"],
                "description": _dig(l, "redacted_description.text", "description.text", "description",
                                    "listing_description") or "",
                "condition": condition,
                "fb_attributes": attrs,
                "photo_urls": photo_urls,
                "price": b["price"],
                "price_text": b["price_text"],
                "location_text": b["location_text"],
                "is_live": l.get("is_live", True) and not l.get("is_sold"),
            }
        # each detailed listing is billed as a listing plus the details add-on
        return out, len(rows) * 2

    async def locate(self, text):
        # Apify searches by Facebook city slug, so there's nothing to look up.
        slug = "".join(ch for ch in text.lower().split(",")[0] if ch.isalnum())
        return [{"name": text, "subtitle": f"Facebook city slug guess: {slug}", "lat": None, "lng": None,
                 "slug": slug}], 0

    async def image_bytes(self, url):
        return await ScrapeCreators.image_bytes(self, url)


# --------------------------------------------------------------------------- Mock

COLORS = {
    "green": "#5f8a5a", "sage": "#9caf88", "olive": "#6b6b3a", "navy": "#2c3e66", "blue": "#4a74b8",
    "grey": "#8a8d91", "charcoal": "#3d3f43", "cream": "#e9dfc8", "beige": "#cdb994", "tan": "#b8865b",
    "brown": "#6b4430", "rust": "#b5532e", "mustard": "#c99a2e", "pink": "#d98a9b", "black": "#222222",
    "white": "#f1f1ee", "teal": "#2f7f7a", "burgundy": "#7a2335",
}
STYLES = ["mid-century", "modern", "traditional", "chesterfield", "farmhouse", "scandinavian",
          "industrial", "boho", "contemporary", "retro"]
MATERIALS = {"couch": ["velvet", "linen", "leather", "boucle", "microfiber", "corduroy", "tweed"],
             "table": ["walnut", "oak", "glass", "marble", "pine", "teak", "metal", "travertine"],
             "item": ["wood", "metal", "plastic", "fabric", "glass"]}
SHAPES = {"couch": ["sofa", "couch", "loveseat", "sectional", "sleeper sofa"],
          "table": ["coffee table", "round coffee table", "oval coffee table", "nesting tables"],
          "item": ["piece", "item"]}
EXTRAS = {"couch": ["track arms", "rolled arms", "tight back", "loose cushions", "tufted", "low profile",
                    "tapered legs", "skirted", "deep seat"],
          "table": ["hairpin legs", "pedestal base", "lower shelf", "rounded edges", "live edge",
                    "drawer", "tiled top", "slatted"],
          "item": ["vintage", "like new", "scratches", "barely used"]}


def _kind(query):
    q = query.lower()
    if any(w in q for w in ["couch", "sofa", "loveseat", "sectional", "settee"]):
        return "couch"
    if "table" in q:
        return "table"
    return "item"


class Mock:
    """Fake Marketplace. Deterministic per (query, cursor) so reruns look stable."""
    name = "mock"

    def __init__(self):
        self.cache = {}

    def _make(self, rng, kind, query, i):
        color = rng.choice(list(COLORS))
        style = rng.choice(STYLES)
        mat = rng.choice(MATERIALS[kind])
        shape = rng.choice(SHAPES[kind])
        extra = rng.sample(EXTRAS[kind], 2)
        width = rng.choice([54, 60, 66, 72, 76, 80, 84, 88, 96]) if kind == "couch" else rng.choice([30, 36, 42, 48, 54])
        price = rng.choice([40, 60, 75, 90, 120, 150, 180, 220, 260, 300, 350, 420, 500, 650, 800])
        title = f"{color.title()} {mat} {style} {shape}"
        if rng.random() < 0.5:
            title += f" {width}\""
        say_dims = rng.random() < 0.65
        desc = (f"Selling my {color} {mat} {shape}. {style.title()} style with {extra[0]} and {extra[1]}. "
                + (f"Measures {width}\" wide. " if say_dims else "")
                + rng.choice(["Smoke free, pet free home.", "Has a small stain, see pics.", "Must pick up.",
                              "Barely used, moving sale.", "Some wear on the edges.", "Like new."]))
        fb_id = hashlib.md5(f"{query}|{i}|{title}".encode()).hexdigest()[:15]
        return {
            "fb_id": "mock" + fb_id,
            "url": f"https://www.facebook.com/marketplace/item/mock{fb_id}/",
            "title": title,
            "price": price,
            "price_text": f"${price}",
            "location_text": rng.choice(["Philadelphia, PA", "Cherry Hill, NJ", "Camden, NJ", "Media, PA",
                                         "Conshohocken, PA", "Fishtown, Philadelphia"]),
            "thumb_url": f"mock://{kind}/{color}/{fb_id}",
            "_detail": {
                "title": title,
                "description": desc,
                "condition": rng.choice(["Used - Like New", "Used - Good", "Used - Fair", "New"]),
                "fb_attributes": [{"name": "Material", "value": mat.title()}],
                "photo_urls": [f"mock://{kind}/{color}/{fb_id}/{n}" for n in range(3)],
                "price": price,
                "price_text": f"${price}",
                "location_text": None,
                "is_live": True,
            },
        }

    async def search(self, profile, query, cursor=None):
        page = int(cursor or 0)
        rng = random.Random(f"{query}|{page}")
        kind = _kind(query + " " + (profile.get("hunt") or ""))
        items = [self._make(rng, kind, query, page * 100 + i) for i in range(24)]
        # real Marketplace search mixes in unrelated listings; so does the mock
        for i in range(3, 24, 6):
            junk = self._make(rng, "item", query, page * 100 + 50 + i)
            junk_title = rng.choice(["Long tube headers g35", "Kids bike 16 inch", "Slipcover stretch fit",
                                     "Mini fridge works great", "Box of vinyl records", "Car seat cover set"])
            junk["title"] = junk["_detail"]["title"] = junk_title
            junk["_detail"]["description"] = f"{junk_title}. Pickup only."
            items[i] = junk
        lo, hi = profile.get("min_price"), profile.get("max_price")
        items = [x for x in items if (not lo or x["price"] >= lo) and (not hi or x["price"] <= hi)]
        for x in items:
            self.cache[x["fb_id"]] = x["_detail"]
        return [{k: v for k, v in x.items() if k != "_detail"} for x in items], str(page + 1), 0

    async def item(self, fb_id):
        return self.cache.get(fb_id) or {"title": "Unknown", "description": "", "condition": None,
                                         "fb_attributes": [], "photo_urls": [], "is_live": True}, 0

    async def items(self, fb_ids):
        return {i: self.cache[i] for i in fb_ids if i in self.cache}, 0

    async def locate(self, text):
        return [{"name": text, "subtitle": "Mock location (Philadelphia coords)", "slug": "philly",
                 "lat": 39.9526, "lng": -75.1652}], 0

    async def image_bytes(self, url):
        _, _, rest = url.partition("mock://")
        parts = rest.split("/")
        kind, color, seed = parts[0], parts[1], "/".join(parts[2:])
        return _mock_svg(kind, COLORS.get(color, "#888"), seed).encode(), "svg"


def _mock_svg(kind, fill, seed):
    rng = random.Random(seed)
    bg = rng.choice(["#efe7da", "#e3e6e8", "#f3efe6", "#dde3d6", "#ece2d8"])
    floor = rng.choice(["#c9b79c", "#b59f82", "#d6cbb8"])
    leg = rng.choice(["#5a3d2b", "#2b2b2b", "#a0866a"])
    if kind == "couch":
        w = rng.randint(250, 330)
        x = (400 - w) // 2
        body = (f'<rect x="{x}" y="200" width="{w}" height="90" rx="16" fill="{fill}"/>'
                f'<rect x="{x+18}" y="140" width="{w-36}" height="80" rx="18" fill="{fill}" opacity=".9"/>'
                f'<rect x="{x-12}" y="170" width="40" height="110" rx="14" fill="{fill}"/>'
                f'<rect x="{x+w-28}" y="170" width="40" height="110" rx="14" fill="{fill}"/>'
                f'<rect x="{x+30}" y="205" width="{w//2-34}" height="30" rx="8" fill="#000" opacity=".08"/>'
                f'<rect x="{x+w//2+4}" y="205" width="{w//2-34}" height="30" rx="8" fill="#000" opacity=".08"/>'
                f'<rect x="{x+10}" y="288" width="8" height="26" fill="{leg}"/>'
                f'<rect x="{x+w-18}" y="288" width="8" height="26" fill="{leg}"/>')
    elif kind == "table":
        w = rng.randint(200, 300)
        x = (400 - w) // 2
        round_ = rng.random() < 0.5
        top = (f'<ellipse cx="200" cy="230" rx="{w//2}" ry="34" fill="{fill}"/>' if round_ else
               f'<rect x="{x}" y="215" width="{w}" height="26" rx="6" fill="{fill}"/>')
        body = (top + f'<rect x="{x+20}" y="240" width="10" height="70" fill="{leg}"/>'
                f'<rect x="{x+w-30}" y="240" width="10" height="70" fill="{leg}"/>')
    else:
        body = f'<rect x="120" y="140" width="160" height="170" rx="20" fill="{fill}"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="800" height="800">'
            f'<rect width="400" height="400" fill="{bg}"/><rect y="310" width="400" height="90" fill="{floor}"/>'
            f'<ellipse cx="200" cy="318" rx="170" ry="10" fill="#000" opacity=".12"/>{body}</svg>')


_REAL = {}


def get_source():
    mode = config.source_mode()
    if mode == "mock":
        return MOCK
    if mode not in _REAL:
        _REAL[mode] = (ScrapeCreators(config.SCRAPECREATORS_API_KEY) if mode == "scrapecreators"
                       else Apify(config.APIFY_TOKEN, config.APIFY_ACTOR))
    return _REAL[mode]


MOCK = Mock()
