# Bright Data Scraper

Three process nodes for **Bright Data**: search Google, load pages past bot protection, open pages in a real browser.
Bright Data's proxy network gets past bot protection, CAPTCHAs and geo blocks, so the nodes reach shops and price
comparison sites that block a normal script or even your own browser. Nothing runs on your machine – it works the same
on a server.

A typical chain: **🔍 Google search** → **🛰 Web Unlocker** (or **🖥 Browser API** for the hard cases) → an agent reads
the pages.

| Node | Bright Data product | Billed | Good for |
|---|---|---|---|
| 🔍 **Google search (Bright Data)** | SERP API | per search (10 results): ≈ $1.50 / 1,000 | the URLs of the hits for a query |
| 🛰 **Web Unlocker (Bright Data)** | Web Unlocker API | per page: ≈ $1.50 / 1,000 | most pages, also with bot protection – fast, as Markdown |
| 🖥 **Browser API (Bright Data)** | Browser API | by traffic: ≈ $8 / GB | pages that need JavaScript, clicks or that block even the Web Unlocker |

Prices pay as you go, October 2026 – the Scale plan ($499/month) is cheaper per unit; 5,000 free credits per month
(check Bright Data's pricing pages). Only successful requests are billed.

## Settings

| Setting | |
|---|---|
| **Bright Data API key** | brightdata.com → Account settings → API keys – SERP API and Web Unlocker |
| **SERP API zone** | the name of your SERP API zone (default `serp_api1`) |
| **Web Unlocker zone** | the name of your Web Unlocker zone (default `web_unlocker1`) |
| **Browser API username / password** | from the Overview tab of your Browser API zone |
| **Country** | two letters like `de` – searches and pages come from that country (prices, language). Empty: Bright Data decides |
| **Search language** | the language of Google's results (default `de`) |
| **Web Unlocker: run JavaScript** | Bright Data renders the page in a browser first – slower |
| **Pages at once** | requests or browser sessions at the same time, 1–20 (default 5) – for all nodes together: parallel loop items share it instead of multiplying it |
| **Timeout per page** | default 120 s – hard pages take a while |

Only fill in what you use. **Test** checks every part that is filled in – one billed request each – and shows the
costs.

## 🔍 Google search (Bright Data)

Same node as in the **Google SERP** plugin, through Bright Data: the query is written by the AI from the input, taken
as it is, or built from a template (`{input} site:geizhals.de`); the number of results is fixed or read from the input
(“top 20”); results can leave out sites. Hands on a `URLS:` block that the scrape nodes read. Outputs: **URLs**, **No
results**, **Error**.

## 🛰 Web Unlocker (Bright Data)

| Field | |
|---|---|
| **Format** | **Markdown** (default, converted by Bright Data) or **raw HTML** |
| **URLs** | one per line – empty: the URLs of the input (the `URLS:` list of Google Search / SERP, else every link in it) |
| **At most pages** | default 10, 0 = all – every page is one billed request |
| **Country** | overrides the setting for this node |
| **Folder** | default `scraped/` in the project's workspace – one `.md` / `.html` per page; empty = no files |
| **Hand on** | the **content** or **only titles and file paths**. Theron hands on about 12,000 characters per step in all: the file list comes first, then each page gets an equal share (or *Characters per page*) – the files always have everything, an agent behind the node can read them |

Under load Bright Data answers now and then with a 502, 429, an empty page or an unparsed Google page – such a request is
asked again (up to 4 times, a Google page up to 5, waiting 2, 4, 8 … seconds), and a refused key or zone is checked once
more before the node stops. Only successful requests are billed.

## 🖥 Browser API (Bright Data)

Every URL in its own Chrome session at Bright Data: the page loads, JavaScript runs, Bright Data solves CAPTCHAs, then
the node takes the **visible text** (default) or the **rendered HTML**. Fields as the Web Unlocker's, plus **Wait
after loading** (default 2 s, for prices that come later) and **Load images and fonts** (off: less traffic, same text).
At most 5 pages by default.

Both scrape nodes: outputs **Pages** (at least one page – first `FILES:` one path per line, then *Not loaded:* with the
reason for each one that failed, then the pages) and **Error** (no page at all, no URLs, or the key / zone / password is
wrong – then the remaining pages aren't sent). Same contract as the **Chrome Scraper**'s node: you can swap them.

**Which one?** Start with the **Web Unlocker** – cheaper per shop page, faster, Markdown. Take the **Browser API** for
the pages where it comes back empty or blocked (prices only after JavaScript, hard Cloudflare checks).
