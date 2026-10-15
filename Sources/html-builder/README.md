# HTML Builder

A process node **🧱 Build HTML** that builds **one** clean, self-contained HTML document per run – from a description of
its content, optionally for an **audience**, in a **style / CI** and after a **template**. For several documents put it
behind a loop: every round builds its own file.

**Fields of the node**

| Field | |
|---|---|
| Content | What the document is about. Empty: the step's assignment and the hand-overs (e.g. one item of a loop). |
| Audience (optional) | Who reads it – wording, depth and tone follow. |
| Style / CI (optional) | Colours, fonts, tone – or the path / link of a style guide or CSS (it is read first). |
| Template folder | Your templates (HTML, Markdown, text, PDF, Word, CSS, images). **📂** opens it, **＋** copies files into it. A name is a sub-folder of the plugin's template folder, an absolute path is itself. Empty: the folder of the plugin settings. |
| Template | **Automatic** (the AI takes the best fitting one – or none), **None**, or a fixed file. **👁** opens it. A hand-over may name one: `TEMPLATE: angebot.html`. |
| Output folder / File name | Where it goes (relative to the project's workspace); nothing is overwritten (-2, -3 …). |
| Self-contained | CSS inline, no external scripts or stylesheets – it opens anywhere, also as an e-mail attachment. |

**Outputs:** ✔ **Document** – the hand-over names the file in a line `HTML_FILE: <path>` (plus title and size);
✖ **Error** – why not (no description, no file, HTML that stays broken …).

**How:** a Claude agent of the plugin (your Claude subscription; model in the plugin settings) reads the template and
the style guide and writes the file. Then the plugin checks it: doctype, charset, viewport, title, `lang`, one `<h1>`,
every tag closed, alt texts, no Markdown fences. Problems go back to the same agent (up to two rounds); what is left
is named in the hand-over. In the chat the document shows as a card with **Open in the browser** and **Show folder**.

Needs Theron 0.20.
