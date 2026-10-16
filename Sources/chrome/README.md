# Chrome Scraper

Loads web pages in **your own Chrome** and hands on their content – as clean Markdown (the main content, without
menus, footer and cookie banners) or as raw HTML. Put it behind **Google SERP**: search → scrape the hits → an agent
reads and summarises them.

## 🌐 Scrape pages

| Field | |
|---|---|
| **Format** | **Markdown** (default), **raw HTML** or **both** |
| **Content** | **main content** (default) or the **whole page** – Markdown only |
| **Pictures as links** | `![alt](url)` in the Markdown (off by default) |
| **HTML** | **as rendered** (the DOM after JavaScript, default) or **as the server sent it** |
| **URLs** | one per line – empty: the URLs of the input (the `URLS:` list of Google SERP, else every link in it) |
| **At most pages** | default 10, 0 = all |
| **Folder** | default `scraped/` in the project's workspace – one `.md` / `.html` per page; empty = no files |
| **Hand on** | the **content** (cut at *Characters per page*, default 20,000 – the file has everything) or **only titles and file paths** |

Outputs: **Pages** (at least one page loaded – the pages, then *Not scraped:* with the reason for each one that
failed, then `FILES:` one path per line) and **Error** (no page at all). The chat lists the pages as links.

## Like a person

Bot protection looks for automated browsers. The plugin doesn't use WebDriver or Playwright – it starts the installed
Chrome (else Chromium, Edge or Brave) with its own profile and talks to it over the DevTools protocol:

- no automation switches – `navigator.webdriver` is `false`, as in a browser a person opened;
- invisible (headless) Chrome gets the user agent and client hints of the normal Chrome (no “HeadlessChrome”) and a
  screen that fits its window;
- your languages as `Accept-Language`, the machine's real platform, graphics card and time zone;
- its own profile keeps cookies like a normal browser – **Open browser** in the settings opens it, to log in to sites
  or accept cookie banners once;
- mouse moves and scrolling with pauses (this also loads lazy content), one page per site at a time with a pause
  between pages, a few tabs for different sites at once.

**When a site still blocks:** checks like Cloudflare's “Just a moment …” usually let a real browser through after a
few seconds – the plugin waits (*Wait for bot checks*, default 20 s). If the invisible browser stays blocked, the page
is loaded once more in a **real window** off the screen. If that doesn't pass either (an interactive check, a CAPTCHA),
the plugin shows the page in a Chrome window and **asks you in the chat** to get past it – it never solves CAPTCHAs
itself. In AUTO mode, or on a server without a screen, such pages end up in *Not scraped*.

## Settings

| Setting | |
|---|---|
| **Browser** | **invisible** (default), **real window off the screen** (most natural, Chrome shows in the Dock / taskbar), **visible window** |
| **Blocked: try again in a real window** | on |
| **Still blocked: let me solve it** | on |
| **Languages** | `de-DE, de, en` |
| **Pause per site** | 2 s (varied) |
| **Pages at once** | 3 |
| **Wait for bot checks** | 20 s |
| **Browser path** | empty = found by itself |

**Test** starts Chrome invisibly, loads example.com and shows whether it looks like a normal browser.

## On a server

Without a screen Chrome always runs invisibly. The Theron headless Docker image has Chromium on board (from Theron
0.23.0); elsewhere install `chromium` or `google-chrome-stable`. In a container the plugin adds `--no-sandbox` by
itself.

Needs Theron 0.20.0. Permissions: network (the pages), files (the files in the project's folder).
