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

### ▦ Trello Sync · `trello-sync`

Syncs a Theron task list with a Trello board – needs Theron 0.16.0.

- **Settings:** your Trello API key and token.
- **Task-list page:** select a list, click **Sync with Trello**, enter the board id or link. The plugin reads the board,
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
