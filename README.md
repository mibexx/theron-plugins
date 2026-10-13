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
