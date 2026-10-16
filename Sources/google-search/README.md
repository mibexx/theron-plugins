# Google Search

Google's own APIs as process nodes:

- **🔎 Google Search** – the [Custom Search JSON API](https://developers.google.com/custom-search/v1/overview) of
  Google Cloud: the query comes from the input, the URLs of the hits go on to the next step (e.g. the Chrome
  Scraper). Works like the *Google SERP* plugin, which uses SerpApi / Serper instead.
- **✦ Google research (Gemini)** – [Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search):
  Gemini researches the question with Google Search and answers with its sources – or hands on only the source URLs.
  Google's official way to search the whole web after the Custom Search API.

> **Note:** Google takes no new customers for the Custom Search JSON API and switches it off on **1 January 2027**
> (“Search the entire web” ends then). Without an existing key, use the *Google SERP* plugin.

**Setup:** Settings → Plugins → Google Search → *Settings …*

| Setting | |
|---|---|
| **Google API key** | Google Cloud console → APIs & Services → Credentials, in a project with the *Custom Search API* enabled |
| **Search engine ID (cx)** | [programmablesearchengine.google.com](https://programmablesearchengine.google.com) → your search engine → *Search engine ID*; for the whole web switch on *Search the entire web* |
| **Gemini API key** | for *Google research*: [aistudio.google.com](https://aistudio.google.com) → *Get API key* (or a Google Cloud key with the *Generative Language API*); empty = the Google API key above |
| **Country / Language** | two letters (`de` / `de` by default) – boost a country, results in a language |

**Cost (Google):** 100 queries per day free, then $5 per 1,000 – at most 10,000 per day. One query = up to 10
results (25 URLs = 3 queries); at most 100 results per search. *Google research*: grounded requests have a free amount
per month (Gemini 3) or day (older models), then about $14–35 per 1,000 depending on the model, plus the model's
tokens ([pricing](https://ai.google.dev/pricing)). **Test** checks what is filled in: one Custom Search query, and the
Gemini key (lists its models – free; the node's model list fills from it).

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

## ✦ Google research (Gemini)

| Field | |
|---|---|
| **Hand on** | **the answer with its sources** (default) or **only the source URLs** (like a search) |
| **Model** | `gemini-flash-latest` (default, follows Google's newest Flash), `gemini-pro-latest` … – the list fills after *Test* |
| **At most sources** | Gemini decides how many sources it uses (often 3–10); this caps them (default 10) |
| **Real page addresses** | Google hands out redirect links – on: followed to the real pages (needed for the Chrome Scraper) |
| **Answer language** | e.g. `German` – empty: the language of the question |

Outputs: **Answer** – first `URLS:` (one per line), then what Google was searched for, then `ANSWER:` and
`SOURCES:` with numbers – and **Error** (no key, quota used up …). The chat shows the answer, the sources as links and
the Google searches Gemini made (as links to Google – Google's terms want the search suggestions shown with grounded
answers). Unlike a search you can't ask for 50 or 100 results: Gemini picks its sources.

Needs Theron 0.20.0. Permissions: network (Google), AI (writing the query).
