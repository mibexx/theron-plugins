# Chrome Scraper

Loads web pages in **your own Chrome** and hands on their content – as clean Markdown (the main content, without
menus, footer and cookie banners) or as raw HTML. Put it behind **Google SERP**: search → scrape the hits → an agent
reads and summarises them.

## 🌐 Scrape pages

| Field | |
|---|---|
| **Browser** | **Own Chrome** (default – the plugin's own Chrome, see below) or **Claude in Chrome** (your Chrome, see below) |
| **Format** | **Markdown** (default), **raw HTML** or **both** |
| **Content** | **main content** (default) or the **whole page** – Markdown only |
| **Pictures as links** | `![alt](url)` in the Markdown (off by default) |
| **HTML** | **as rendered** (the DOM after JavaScript, default) or **as the server sent it** |
| **URLs** | one per line – empty: the URLs of the input (the `URLS:` list of Google SERP, else every link in it) |
| **At most pages** | default 10, 0 = all |
| **Folder** | default `scraped/` in the project's workspace – one `.md` / `.html` per page; empty = no files |
| **Hand on** | the **content** or **only titles and file paths**. Theron hands on about 12,000 characters per step in all: the file list comes first, then each page gets an equal share (or *Characters per page*) – the files always have everything, an agent behind the node can read them |

Outputs: **Pages** (at least one page loaded – first `FILES:` one path per line, then *Not scraped:* with the
reason for each one that failed, then the pages) and **Error** (no page at all). The chat lists the pages as links.

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

## Claude in Chrome

With **Browser → Claude in Chrome** the node loads the pages in **your own Chrome** with the
[Claude extension](https://claude.com/chrome) – your cookies, your logins, a browser you use every day. A small Claude
Code agent (Haiku, on your Claude subscription) opens each page in a new tab, reads it (`get_page_text`, plus the HTML
for *raw HTML*) and closes the tab; the plugin takes the page text verbatim from the tool, the model doesn't retell it.

- **Desktop only** and **Theron 0.25+** – on a server or an older Theron the node goes to **Error** with a hint.
- Chrome must be open with the Claude extension signed in. **Several connected Chrome browsers:** the node asks you
  once which one to use and remembers it (the extension wants you to choose – the agent never picks one itself).
- One page after the other, so slower than the own Chrome – and the page text counts towards your Claude usage.
- The agent never clicks, types, logs in or solves a CAPTCHA. A bot check stays open in a tab of your Chrome and the
  node **asks you in the chat** to get past it (*Still blocked: let me solve it*); then it reads the tab.
- *Content*, *Pictures as links* and *HTML as the server sent it* apply to the own Chrome only – Claude in Chrome
  hands on the page text as Chrome's extension reads it.

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

Needs Theron 0.20.0 (Claude in Chrome: 0.25.0). Permissions: network (the pages), files (the files in the project's folder).
