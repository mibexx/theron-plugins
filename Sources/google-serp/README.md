# Google SERP

A Google search as a process node: the query comes from the input, the URLs of the hits go on to the next step – e.g.
a research process that searches, then lets an agent read and summarise the pages.

**Setup:** Settings → Plugins → Google SERP → *Settings …*

| Setting | |
|---|---|
| **Provider** | [SerpApi](https://serpapi.com) or [Serper](https://serper.dev). Below it: the average cost per 1,000 searches of both (as of October 2026). |
| **Google SERP API key** | serpapi.com → Dashboard → *Your Private API Key*, or serper.dev → *API Key* |
| **Country / Language** | two letters (`de`, `us` / `de`, `en`) – which Google answers. Default `de` / `de`. |

**Test** checks the key – with SerpApi it also shows your plan and the searches left this month (free, no search used);
Serper has no such call, so it makes one test search.

## 🔎 Google search

| Field | |
|---|---|
| **Query** | **AI writes it from the input** (default – the orchestrator's assignment and the hand-overs, plus the node's instructions), **the input as it is** (the newest hand-over) or a **template** like `{input} site:github.com` |
| **Number of results** | **fixed** (the number below) or **from the input** – “top 20”, “30 URLs”, “Anzahl: 5” … (the AI reads it, too); nothing said → the number below |
| **Results** | 1–100, default 10 |
| **Country / Language** | override the settings for this node |
| **Leave out sites** | e.g. `pinterest.com, youtube.com` |

Outputs:

- **URLs** – the hits as a numbered list (title, URL, snippet) and after `URLS:` one URL per line.
- **No results** – Google found nothing.
- **Error** – no API key, wrong key, no searches left …

The chat shows the query and the hits as links.

**Costs:** Google hands out 10 results per page, so every started 10 results is one search on your plan (25 URLs =
3 searches). Duplicates and left-out sites are skipped; when Google has no more, the node stops paging.

Needs Theron 0.20.0. Permissions: network (SerpApi / Serper), AI (writing the query).
