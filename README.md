# Theron Plugins

Plugins for [Theron](https://theron.mibexx.de) by mibexx.

| Folder | Content |
|---|---|
| [`Sources/`](Sources) | the source code – one folder per plugin |
| [`Plugins/`](Plugins) | the ready packages – one `.theronplugin` per plugin, signed |

**Install a plugin:** in Theron (0.18+) *Settings → Plugins → “Official plugins …”* – one click installs or updates,
older versions can be picked, too (`theron plugin install <id>[@version]` / `theron plugin update` in the console).
Or download it from the [plugin catalog](https://theron.mibexx.de/plugins.html) (or its file from `Plugins/`) and use
*“Upload plugin …”* / `theron plugin install Plugins/<id>.theronplugin`. Restart Theron afterwards.

**Build:** `python scripts/build.py` packs every plugin of `Sources/` into `Plugins/` (signed with the mibexx key if it
is on the machine). New plugins start from the [plugin skeleton](https://github.com/mibexx/theron-plugin-sekeleton);
the plugin API is documented there in `docs/`.

The [plugin catalog](https://theron.mibexx.de/plugins.html) on the Theron website lists every package in `Plugins/`
with its description and README – it checks this repo every 15 minutes, so a pushed plugin shows up there by itself.
The plugin server [plugins.theron.mibexx.de](https://plugins.theron.mibexx.de/v1/plugins) – where Theron's “Official
plugins” come from – does the same and also keeps every version: each commit that changed a package in `Plugins/` is
a version (the newest commit wins if a version was rebuilt). So: raise the version in `plugin.toml` for every release,
build, commit and push – that's all.

## The plugins

### 👋 Hello World · `hello-world`

The smallest useful plugin – to try out how plugins work.

- **Navigation entry “Hello World”** – a page of its own in Theron's sidebar.
- **Process node “Hello World”** – one input, ✔ and ✖ outputs. It outputs “Hello World” and the process carries on
  via ✔ (whatever came in goes along).

Source: [`Sources/hello-world`](Sources/hello-world) · Package: [`Plugins/hello-world.theronplugin`](Plugins/hello-world.theronplugin)

### 🧱 HTML Builder · `html-builder`

One clean, self-contained HTML document per run of the node **Build HTML** – from a description, optionally for an
audience, in a style / CI and after a template of your template folder (📂 / ＋ right in the node). Checked before it
goes on (✔ Document · ✖ Error); behind a loop for several documents. Needs Theron 0.20.0.

Source: [`Sources/html-builder`](Sources/html-builder) · Package: [`Plugins/html-builder.theronplugin`](Plugins/html-builder.theronplugin)

### 📐 draw.io Diagrams · `drawio`

One diagram per run of the node **Draw diagram** – flowchart, sequence, class, ER, architecture, mind map … (fixed in
the node or taken from the description): the `.drawio` file and a PNG. The picture shows in the chat, a click opens it
large. The PNG comes from the plugin's own renderer, the draw.io desktop app or draw.io in Docker (settings – each
checked when you choose it). Needs Theron 0.20.0.

Source: [`Sources/drawio`](Sources/drawio) · Package: [`Plugins/drawio.theronplugin`](Plugins/drawio.theronplugin)

### 📽 HTML Presentation · `html-presentation`

One presentation per run of the node **Build presentation** – one HTML file: always one 16:9 slide, as large as the
screen allows; multilingual with a switch, light / dark / both with a switch, slide cursor top or bottom, arrow keys –
each fixed in the node or read from the input. Content, style / CI and templates like the HTML Builder. Needs Theron
0.20.0.

Source: [`Sources/html-presentation`](Sources/html-presentation) · Package: [`Plugins/html-presentation.theronplugin`](Plugins/html-presentation.theronplugin)

### 🔎 Google SERP · `google-serp`

The node **Google search** asks Google and hands on the URLs of the hits – the query is written by the AI from the
input, taken as it is or built from a template; the number of results is fixed in the node or read from the input
(“top 20”). Via SerpApi or Serper with your API key (settings, with **Test** and the average cost per 1,000 searches).
Needs Theron 0.20.0.

Source: [`Sources/google-serp`](Sources/google-serp) · Package: [`Plugins/google-serp.theronplugin`](Plugins/google-serp.theronplugin)

### 🌐 Chrome Scraper · `chrome`

The node **Scrape pages** loads the URLs it gets (e.g. the hits of Google SERP) in your own Chrome and hands on their
content as clean Markdown (main content, without menus and cookie banners) or raw HTML – files in the project's folder.
It behaves like a person (no automation switches, a normal user agent even invisible, its own profile with cookies,
mouse and scrolling, pauses per site); a site that stays blocked is tried in a real window and then shown to you – it
never solves CAPTCHAs. Works headless on a server. Needs Theron 0.20.0.

Source: [`Sources/chrome`](Sources/chrome) · Package: [`Plugins/chrome.theronplugin`](Plugins/chrome.theronplugin)

### ▦ Trello Sync · `trello-sync`

Syncs a Theron task list with a Trello board – needs Theron 0.16.0.

- **Settings:** your Trello API key and token – **Test connection** checks them.
- **Task-list page:** select a list, click **Sync with Trello**, pick one of your boards (or paste its id or link). The
  plugin reads the board,
  shows what it found and asks for the direction: **read** (Trello → Theron: lists → epics, cards → requirements) or
  **write** (Theron → Trello). After that the button is **⟳ Sync**; **Unlink Trello** removes the link.
- Status ↔ labels (“Theron: done” …), acceptance criteria in the card description; the first sync matches by name,
  only what the sync linked is ever removed or archived.

Source: [`Sources/trello-sync`](Sources/trello-sync) · Package: [`Plugins/trello-sync.theronplugin`](Plugins/trello-sync.theronplugin)

### 🔊 ElevenLabs · `elevenlabs`

Voices and speech from ElevenLabs as process nodes – needs Theron 0.17.0.

- **Settings:** your ElevenLabs API key – **Test** checks it and shows the credits left.
- **Node “Choose voice”** – manual (the voices with ▶ samples in the chat, you answer with a number, a name or in your
  own words), automatic (by the mood of the text and a preselection like “female, German”) or fixed. Plays a sample
  of the chosen voice in the chat.
- **Node “Generate speech”** – the AI takes the spoken text from the input (e.g. a video script), splits it into parts
  and ElevenLabs speaks them into audio files in the project's folder; **Emotions** adds Eleven v3 tags. Outputs the
  file paths – or **Error** (no key, not enough credits …).
- Every audio file path in the chat gets a ▶.

Source: [`Sources/elevenlabs`](Sources/elevenlabs) · Package: [`Plugins/elevenlabs.theronplugin`](Plugins/elevenlabs.theronplugin)

**Tests:** `PYTHONPATH=<theron source> QT_QPA_PLATFORM=offscreen python -m pytest Sources/*/tests` (with Theron's Python environment).
