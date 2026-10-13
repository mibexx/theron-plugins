# Theron Plugins

Plugins for [Theron](https://theron.mibexx.de) by mibexx.

| Folder | Content |
|---|---|
| [`Sources/`](Sources) | the source code – one folder per plugin |
| [`Plugins/`](Plugins) | the ready packages – one `.theronplugin` per plugin, signed |

**Install a plugin:** download it from the [plugin catalog](https://theron.mibexx.de/plugins.html) (or its file from
`Plugins/`), then in Theron *Settings → Plugins → “Upload plugin …”* – or
`theron plugin install Plugins/<id>.theronplugin`. Restart Theron afterwards.

**Build:** `python scripts/build.py` packs every plugin of `Sources/` into `Plugins/` (signed with the mibexx key if it
is on the machine). New plugins start from the [plugin skeleton](https://github.com/mibexx/theron-plugin-sekeleton);
the plugin API is documented there in `docs/`.

The [plugin catalog](https://theron.mibexx.de/plugins.html) on the Theron website lists every package in `Plugins/`
with its description and README – it checks this repo every 15 minutes, so a pushed plugin shows up there by itself.

## The plugins

### 👋 Hello World · `hello-world`

The smallest useful plugin – to try out how plugins work.

- **Navigation entry “Hello World”** – a page of its own in Theron's sidebar.
- **Process node “Hello World”** – one input, ✔ and ✖ outputs. It outputs “Hello World” and the process carries on
  via ✔ (whatever came in goes along).

Source: [`Sources/hello-world`](Sources/hello-world) · Package: [`Plugins/hello-world.theronplugin`](Plugins/hello-world.theronplugin)

### ▦ Trello Sync · `trello-sync`

Syncs a Theron task list with a Trello board – needs Theron 0.16.0.

- **Settings:** your Trello API key and token.
- **Task-list page:** select a list, click **Sync with Trello**, enter the board id or link. The plugin reads the board,
  shows what it found and asks for the direction: **read** (Trello → Theron: lists → epics, cards → requirements) or
  **write** (Theron → Trello). After that the button is **⟳ Sync**; **Unlink Trello** removes the link.
- Status ↔ labels (“Theron: done” …), acceptance criteria in the card description; the first sync matches by name,
  only what the sync linked is ever removed or archived.

Source: [`Sources/trello-sync`](Sources/trello-sync) · Package: [`Plugins/trello-sync.theronplugin`](Plugins/trello-sync.theronplugin)

**Tests:** `PYTHONPATH=<theron source> python -m pytest Sources/trello-sync/tests` (with Theron's Python environment).
