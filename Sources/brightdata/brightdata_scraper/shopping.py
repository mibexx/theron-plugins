"""The process node 🛒 Google Shopping (Bright Data SERP API): products from the input → the offers Google Shopping shows
for them – the price as Google shows it (what customers see first), the shop, the old price – and, if wanted, every
shop's offer from the product's page (item price, shipping, total, the link into the shop).

One product can be searched with several queries (its name, a distinctive part of it, the EAN, the article number);
the offers of all its queries are put together without doubles and sorted by price. Every query and every opened
product page is one billed search."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from .api import Client, NotParsed, UnlockError
from .node import slug, unique
from .search import HANDOVER, json_in, material_of, one_line, raw_input

MAX_PRODUCTS = 100
MAX_QUERIES = 6
MAX_OPEN = 10
SPLIT = re.compile(r"\s+\|\s+|\s*;\s*|\t")


def products_from_lines(text: str, template: str = "") -> list[dict]:
    """One product per line; several queries in a line apart with “ | ”, “;” or a tab – the first one names it."""
    out = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip()
        if not line or line.endswith(":"):
            continue
        queries = [q.strip() for q in SPLIT.split(line) if q.strip()]
        if template:
            queries = [template.replace("{input}", q) for q in queries]
        out.append({"name": queries[0] if not template else line, "queries": queries})
    return out


def key_of(offer: dict) -> tuple:
    """The same shop at the same price is one offer – Google lists it once per query, and again on the product page."""
    if offer["value"] is None:
        return (offer["shop"].lower(), re.sub(r"\W+", " ", offer["title"].lower())[:60])
    return (re.sub(r"\W+", "", offer["shop"].lower()), offer["value"])


def merge(offers: list[dict]) -> list[dict]:
    """Without doubles (the first one stays – so the product page's offer with its shop link), the cheapest first."""
    seen, out = set(), []
    for o in offers:
        k = key_of(o)
        if k in seen:
            continue
        seen.add(k)
        out.append(o)
    return sorted(out, key=lambda o: (o["value"] is None, o["value"] or 0))


def line_of(o: dict) -> str:
    bits = [o["price"] or "–", o["shop"] or "?", o["title"]]
    if o["old_price"]:
        bits.append(o["old_price"])
    if o["shipping"]:
        bits.append(o["shipping"] + (f" → {o['total']}" if o["total"] and o["total"] != o["price"] else ""))
    return "- " + " · ".join(bits) + (f" · {o['shop_link']}" if o["shop_link"] else "")


class ShoppingNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "shopping", label="Google Shopping (Bright Data)", icon="🛒", run=self.run,
            description="Searches Google Shopping through Bright Data's SERP API for every product in the input – by "
                        "name, parts of it, EAN or article number – and hands on the offers with the prices Google "
                        "shows, the shops and old prices; optionally every shop's offer from the product page.",
            ai_hint="Google Shopping via Bright Data SERP API: for each product in the input (name, EAN, article "
                    "number – the AI writes up to N queries per product, or one product per line with queries apart "
                    "by ' | ') it hands on the offers: price as shown by Google (gross), shop, old price; with "
                    "'every shop's offer' also item price, shipping, total and the shop's link. Offers are not "
                    "checked for being the same product – put an agent after it to match them. Full results as JSON "
                    "and Markdown files in the folder. Outputs: offers, empty (nothing found), error.",
            outputs=[{"id": "offers", "label": tr("Offers"), "color": "success"},
                     {"id": "empty", "label": tr("No offers"), "color": "neutral"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "query_mode", "type": "choice", "label": "Products and queries", "default": "ai",
                 "options": [{"value": "ai", "label": "AI finds the products and writes the queries"},
                             {"value": "input", "label": "One product per line (queries apart by “ | ”)"},
                             {"value": "template", "label": "One product per line, through the template below"}]},
                {"key": "template", "type": "text", "label": "Template", "default": "{input}",
                 "show_if": {"query_mode": "template"},
                 "description": "{input} is replaced by each query of a line, e.g. “{input} kaufen”."},
                {"key": "queries", "type": "number", "label": "Queries per product", "default": 3,
                 "show_if": {"query_mode": "ai"},
                 "description": "1–6 – e.g. the full name, a distinctive part of it, the EAN. Each is one billed "
                                "search."},
                {"key": "max_products", "type": "number", "label": "Products at most", "default": 20,
                 "description": "1–100 – the rest is listed as not searched."},
                {"key": "open", "type": "number", "label": "Every shop's offer: product pages per product",
                 "default": 0,
                 "description": "0–10. Google's list shows ONE shop for a product sold by several (“& more "
                                "prices”) – this many of those products are opened per product for every shop's "
                                "offer with item price, shipping, total and the link into the shop. One billed search "
                                "each."},
                {"key": "check", "type": "bool", "label": "AI keeps only offers of the product", "default": True,
                 "description": "Google Shopping also shows similar products – and for an EAN Google doesn't know, "
                                "anything. The AI compares every offer's title with the product (brand, model, "
                                "variant such as 3 kW / 400 V) and drops the others; they stay in the files."},
                {"key": "keep", "type": "number", "label": "Offers per product", "default": 20,
                 "description": "In the hand-over, the cheapest first – the files keep all of them."},
                {"key": "country", "type": "text", "label": "Country (optional)",
                 "description": "Two letters like de, at. Empty: the setting."},
                {"key": "language", "type": "text", "label": "Language (optional)",
                 "description": "Two letters like de or en. Empty: the setting."},
                {"key": "folder", "type": "text", "label": "Folder", "default": "shopping",
                 "description": "In the project's working folder – one JSON and one Markdown file per run with every "
                                "offer. Empty: no files."},
            ])

    # ------------------------------------------------------------------ what to search
    async def products(self, node) -> list[dict]:
        cfg = node.config
        mode = cfg.get("query_mode") or "ai"
        if mode == "input":
            return products_from_lines(raw_input(node))
        if mode == "template":
            return products_from_lines(raw_input(node), cfg.get("template") or "{input}")
        try:
            per = max(1, min(int(cfg.get("queries") or 3), MAX_QUERIES))
        except (TypeError, ValueError):
            per = 3
        return await self.ask_ai(node, material_of(node), per)

    async def ask_ai(self, node, material: str, per: int) -> list[dict]:
        prompt = (f"List the products this step is about and write up to {per} Google Shopping queries for each – "
                  "each query alone must find exactly this product: the full product name, a shorter distinctive "
                  "part of the name (brand + model + the values that tell variants apart, e.g. 3 kW / 400 V), the "
                  "EAN/GTIN as digits only, the manufacturer's article number with the brand. Use only what the "
                  "text gives – never invent an EAN or a number. Leave out queries that would find other products "
                  "as well.\n"
                  + (f"\nINSTRUCTIONS FROM THE USER:\n{node.instructions}\n" if node.instructions else "")
                  + f"\nTEXT:\n{material[:20000]}\n\n"
                  'Answer only JSON: {"products": [{"name": "…", "queries": ["…", "…"]}]}')
        try:
            data = json_in(await self.ctx.ai.ask(prompt, system="You write Google Shopping search queries.",
                                                 model="haiku")) or {}
        except Exception as exc:  # noqa: BLE001 – no AI: one product per line
            self.ctx.log.error(f"queries: {exc}")
            data = {}
        out = []
        for p in data.get("products") or []:
            if not isinstance(p, dict):
                continue
            queries = [one_line(str(q)) for q in p.get("queries") or [] if str(q).strip()][:per]
            name = one_line(str(p.get("name") or "")) or (queries[0] if queries else "")
            if name and not queries:
                queries = [name]
            if queries:
                out.append({"name": name, "queries": list(dict.fromkeys(queries))})
        return out or products_from_lines(raw_input(node))

    # ------------------------------------------------------------------ the run
    async def run(self, node):
        tr = self.ctx.tr
        s, cfg = self.ctx.settings, node.config
        try:
            client = Client(self.ctx.http, s.get("api_key") or "", s.get("serp_zone") or "",
                            timeout=float(s.get("timeout") or 120), what="SERP API zone",
                            limit=int(s.get("parallel") or 5))
        except UnlockError as exc:
            return node.route("error", str(exc))
        node.progress(tr("finds the products …"))
        products = await self.products(node)
        if not products:
            return node.route("error", tr("No products to search for – the input is empty."))
        limit = self._int(cfg.get("max_products"), 20, 1, MAX_PRODUCTS)
        products, left = products[:limit], products[limit:]
        opens = self._int(cfg.get("open"), 0, 0, MAX_OPEN)
        keep = self._int(cfg.get("keep"), 20, 1, 200)
        check = cfg.get("check", True) not in (False, "false", 0, "0")
        country = (cfg.get("country") or s.get("country") or "").strip().lower()
        language = (cfg.get("language") or s.get("language") or "").strip().lower()
        searches, fatal, done = [0], [], [0]
        total = sum(len(p["queries"]) for p in products)

        async def one_query(query: str) -> tuple[list[dict], str]:
            if fatal:
                return [], str(fatal[0])
            try:
                got = await client.shopping(query, country=country, language=language)
                return got, ""
            except NotParsed:
                return [], tr("no parsed Google Shopping page")
            except UnlockError as exc:
                if exc.kind in ("invalid_key", "no_zone", "quota"):
                    fatal.append(exc)
                return [], str(exc)
            finally:
                searches[0] += 1
                done[0] += 1
                node.progress(tr("🛒 {n} of {total} searches", n=done[0], total=total))

        async def one_product(p: dict) -> dict:
            found = await asyncio.gather(*(one_query(q) for q in p["queries"]))
            offers = [o for got, _ in found for o in got]
            errors = [f"{q}: {err}" for q, (_, err) in zip(p["queries"], found) if err]
            listed, dropped = merge(offers), []
            if check and listed:   # first the AI drops other products – then only this product's pages are opened
                kept = await self.matching(node, p, listed)
                listed, dropped = ([o for i, o in enumerate(listed) if i in kept],
                                   [o for i, o in enumerate(listed) if i not in kept])
            opened = []
            if opens and not fatal:
                ok = {id(o) for o in listed}
                seen, links = set(), []
                for o in offers:   # products several shops sell – in the order Google shows them
                    if id(o) in ok and o["more"] and o["link"] and (o["product"] or o["link"]) not in seen:
                        seen.add(o["product"] or o["link"])
                        links.append(o["link"])
                for got in await asyncio.gather(*(self._open(client, link, country, searches)
                                                  for link in links[:opens])):
                    opened += got
            return {"name": p["name"], "queries": p["queries"], "offers": merge(opened + listed),
                    "shops": merge(opened), "errors": errors, "dropped": dropped}

        results = await asyncio.gather(*(one_product(p) for p in products))
        return self.hand_on(node, results, left, keep, searches[0], check)

    async def matching(self, node, product: dict, offers: list[dict]) -> set[int]:
        """The offers that are this very product (its variant), by the AI – all of them if the AI can't answer."""
        lines = "\n".join(f"{i}. {o['title']} – {o['shop']} – {o['price']}" for i, o in enumerate(offers))
        prompt = ("Which of these Google Shopping offers are exactly this product – the same brand, model and variant "
                  "(e.g. power, voltage, size, colour, set size)? Accessories, spare parts, other variants and other "
                  "products are not. When the title leaves the variant open but nothing contradicts it, keep it.\n"
                  + (f"\nINSTRUCTIONS FROM THE USER:\n{node.instructions}\n" if node.instructions else "")
                  + f"\nPRODUCT: {product['name']}\nSEARCHED AS: {' · '.join(product['queries'])}\n\nOFFERS:\n"
                  + lines[:30000] + '\n\nAnswer only JSON: {"keep": [numbers]}')
        try:
            data = json_in(await self.ctx.ai.ask(prompt, system="You match shop offers to a product.",
                                                 model="haiku")) or {}
            keep = {int(i) for i in data.get("keep") or [] if str(i).strip().lstrip("-").isdigit()}
        except Exception as exc:  # noqa: BLE001 – no AI: nothing dropped
            self.ctx.log.error(f"check: {exc}")
            return set(range(len(offers)))
        return {i for i in keep if 0 <= i < len(offers)} if "keep" in data else set(range(len(offers)))

    async def _open(self, client, link: str, country: str, searches: list) -> list[dict]:
        try:
            return await client.product_offers(link, country=country)
        except (NotParsed, UnlockError) as exc:
            self.ctx.log.error(f"product page: {exc}")
            return []
        finally:
            searches[0] += 1

    @staticmethod
    def _int(value, default: int, low: int, high: int) -> int:
        try:
            return max(low, min(int(value if value not in (None, "") else default), high))
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------ results
    def folder(self, node) -> Path | None:
        sub = (node.config.get("folder") or "").strip()
        if not sub:
            return None
        ws = (node.project or {}).get("workspace") or ""
        base = Path(ws).expanduser() if ws else Path(self.ctx.data_dir)
        target = Path(sub).expanduser() if Path(sub).expanduser().is_absolute() else base / sub
        target.mkdir(parents=True, exist_ok=True)
        return target

    def hand_on(self, node, results: list[dict], left: list[dict], keep: int, searches: int, check: bool = False):
        tr = self.ctx.tr
        hits = [r for r in results if r["offers"]]   # after the check
        errors = [e for r in results for e in r["errors"]]
        files = []
        folder = self.folder(node)
        if folder:
            stem = f"{node.run_id:04d}-google-shopping"
            data = unique(folder / f"{stem}.json")
            data.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
            doc = unique(folder / f"{stem}.md")
            doc.write_text("\n\n".join(f"# {r['name']}\n\n" + tr("Queries: {q}", q=" · ".join(r["queries"])) + "\n\n"
                                       + ("\n".join(line_of(o) for o in r["offers"]) or tr("No offers."))
                                       + ("\n\n" + tr("Left out (other products):") + "\n"
                                          + "\n".join(line_of(o) for o in r["dropped"]) if r["dropped"] else "")
                                       for r in results), encoding="utf-8")
            files = [str(data), str(doc)]
        summary = [f"- **{r['name']}** – " + (tr("{n} offers, from {price}", n=len(r["offers"]),
                                                  price=r["offers"][0]["price"] or "?") if r["offers"]
                                             else tr("nothing found"))
                   + (" " + tr("({n} other products left out)", n=len(r["dropped"])) if r["dropped"] else "")
                   for r in results]
        node.say(text=tr("🛒 **Google Shopping** – {ok} of {n} products with offers ({s} searches through Bright Data)",
                         ok=len(hits), n=len(results), s=searches) + "\n\n" + "\n".join(summary)
                 + ("\n\n" + tr("Not searched (over the limit): {names}", names=", ".join(p["name"] for p in left))
                    if left else "")
                 + ("\n\n" + tr("Errors:") + "\n" + "\n".join(f"- {e}" for e in errors[:10]) if errors else ""))
        if not hits:
            why = "\n".join(f"- {e}" for e in errors[:10])
            port = "error" if errors and len(errors) >= sum(len(r["queries"]) for r in results) else "empty"
            return node.route(port, tr("Google Shopping found no offers.") + (f"\n{why}" if why else ""))
        head = tr("Google Shopping – offers per product, the cheapest first. Prices as Google shows them (gross).")
        head += " " + (tr("The AI kept only offers whose title is this product – the EAN isn't checked.") if check
                       else tr("Not checked for being exactly the product – compare title, variant and EAN."))
        if files:
            head += "\n\nFILES:\n" + "\n".join(files)
        if left:
            head += "\n\n" + tr("Not searched (over the limit): {names}", names=", ".join(p["name"] for p in left))
        if errors:
            head += "\n\n" + tr("Errors:") + "\n" + "\n".join(f"- {e}" for e in errors[:10])
        blocks = []
        for r in results:
            lines = [line_of(o) for o in r["offers"][:keep]]
            more = len(r["offers"]) - len(lines)
            blocks.append((f"## {r['name']}\n" + tr("Queries: {q}", q=" · ".join(r["queries"]))
                           + ("\n" + tr("{n} offers of other products left out (in the files).", n=len(r["dropped"]))
                              if r["dropped"] else ""),
                           lines or [tr("No offers.")], more))
        # Theron passes at most HANDOVER characters on: every product gets its share of the room
        room = HANDOVER - len(head) - sum(len(h) + 40 for h, _, _ in blocks)
        share = max(300, room // max(len(blocks), 1))
        text = head
        for h, lines, more in blocks:
            body, used = [], 0
            for ln in lines:
                if used + len(ln) + 1 > share:
                    more += len(lines) - len(body)
                    break
                body.append(ln)
                used += len(ln) + 1
            text += f"\n\n{h}\n" + "\n".join(body)
            if more > 0:
                text += "\n" + tr("… {n} more in the files", n=more)
        return node.route("offers", text[:HANDOVER])
