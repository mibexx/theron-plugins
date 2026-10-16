# Google Search

A Google search as a process node with **Google's own API** – the [Custom Search JSON API](https://developers.google.com/custom-search/v1/overview)
of Google Cloud: the query comes from the input, the URLs of the hits go on to the next step (e.g. the Chrome
Scraper). Works like the *Google SERP* plugin, which uses SerpApi / Serper instead.

> **Note:** Google takes no new customers for the Custom Search JSON API and switches it off on **1 January 2027**
> (“Search the entire web” ends then). Without an existing key, use the *Google SERP* plugin.

**Setup:** Settings → Plugins → Google Search → *Settings …*

| Setting | |
|---|---|
| **Google API key** | Google Cloud console → APIs & Services → Credentials, in a project with the *Custom Search API* enabled |
| **Search engine ID (cx)** | [programmablesearchengine.google.com](https://programmablesearchengine.google.com) → your search engine → *Search engine ID*; for the whole web switch on *Search the entire web* |
| **Country / Language** | two letters (`de` / `de` by default) – boost a country, results in a language |

**Cost (Google):** 100 queries per day free, then $5 per 1,000 – at most 10,000 per day. One query = up to 10
results (25 URLs = 3 queries); at most 100 results per search. **Test** makes one query.

## 🔎 Google Search

| Field | |
|---|---|
| **Query** | **AI writes it from the input** (default), **the input as it is** or a **template** like `{input} site:github.com` |
| **Number of results** | **fixed** or **from the input** (“top 20”, “30 URLs” …), else the number below |
| **Results** | 1–100, default 10 |
| **Country / Language** | override the settings for this node |
| **Leave out sites** | e.g. `pinterest.com, youtube.com` |

Outputs: **URLs** (first `URLS:` one per line, then title and snippet of each), **No results**, **Error** (wrong
key or search engine id, daily quota used up …). The chat shows the query and the hits as links.

Needs Theron 0.20.0. Permissions: network (Google), AI (writing the query).
