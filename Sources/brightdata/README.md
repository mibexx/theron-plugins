# Bright Data Scraper

Loads web pages through **Bright Data's Web Unlocker** and hands on their content – as Markdown (converted by Bright
Data) or as raw HTML. Bright Data's proxy network gets past bot protection, CAPTCHAs and geo blocks, so it reaches
shops and price comparison sites that block a normal script or even a real browser. No browser on your machine – it
works the same on a server. Put it behind **Google Search** / **Google SERP**: search → load the hits → an agent reads
them.

Costs money per page: approximately **$1.50 per 1,000 pages** pay as you go, **$1.30** on the Scale plan
($499/month), 5,000 free per month (Bright Data, October 2026 – check their pricing page). Only successful pages are
billed.

## Settings

| Setting | |
|---|---|
| **Bright Data API key** | brightdata.com → Account settings → API keys |
| **Web Unlocker zone** | the name of your Web Unlocker zone (default `web_unlocker1`) |
| **Country** | two letters like `de` – the pages are loaded from that country (prices, language). Empty: Bright Data decides |
| **Run JavaScript** | Bright Data renders the page in a browser first – for shops that show prices only after JavaScript; slower |
| **Pages at once** | requests at the same time, 1–20 (default 5) |
| **Timeout per page** | default 120 s – hard pages take a while |

**Test** loads example.com once through your zone (one billed request) and shows the cost per 1,000 pages.

## 🛰 Scrape pages (Bright Data)

| Field | |
|---|---|
| **Format** | **Markdown** (default) or **raw HTML** |
| **URLs** | one per line – empty: the URLs of the input (the `URLS:` list of Google Search / SERP, else every link in it) |
| **At most pages** | default 10, 0 = all – every page is one billed request |
| **Country** | overrides the setting for this node |
| **Folder** | default `scraped/` in the project's workspace – one `.md` / `.html` per page; empty = no files |
| **Hand on** | the **content** or **only titles and file paths**. Theron hands on about 12,000 characters per step in all: the file list comes first, then each page gets an equal share (or *Characters per page*) – the files always have everything, an agent behind the node can read them |

Outputs: **Pages** (at least one page loaded – first `FILES:` one path per line, then *Not loaded:* with the reason
for each one that failed, then the pages) and **Error** (no page at all, no URLs, or the key / zone is wrong – then
the remaining pages aren't sent). The chat lists the pages as links.

Same contract as the **Chrome Scraper**'s node: you can swap one for the other – Chrome is free and uses your own
browser, Bright Data costs per page and gets through where Chrome is blocked.
