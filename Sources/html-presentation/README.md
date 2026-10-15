# HTML Presentation

A process node **📽 Build presentation** that builds **one** presentation per run as **one HTML file** – it runs in any
browser, offline, without anything to install:

- always **one slide** on the screen, always **16:9**, as large as the window allows (black bars around it)
- **slide cursor** at the top or bottom: progress bar, number (3 / 12) and a dot per slide to jump
- ‹ › buttons, swiping on touch screens, `#3` in the address keeps the slide – and the **arrow keys** (also Page ↑/↓,
  Space, Home, End) if switched on
- **light**, **dark** or **both with a switch** ☀/☾ (starting with the system's setting)
- **multilingual** with a language switch (`?lang=en` in the address picks one)
- a slide with too much content is shrunk until it fits – nothing is cut off; printing gives one page per slide

**Input:** the content (field or the step's assignment / hand-overs), optionally a **style / CI** and a **template**
from the template folder – like the HTML Builder (📂 / ＋ / 👁 right in the node, `TEMPLATE: file` in a hand-over).

**Options – fixed in the node or “From the input”:**

| Option | Values | From the input |
|---|---|---|
| Multilingual | yes / no | `MULTILINGUAL: yes` – or several languages named |
| Language(s) | e.g. `de, en` (the first is the start language) | `LANGUAGES: de, en` (also `SPRACHEN: Deutsch und Englisch`) |
| Light / dark | light / dark / both with a switch | `THEME: both` |
| Slide cursor | top / bottom | `CURSOR: top` |
| Arrow keys | yes / no | `ARROW_KEYS: no` |

Without such a line the AI decides from the content (“in German and English”, “dark slides”); otherwise:
one language (the content's), light, cursor at the bottom, arrow keys on.

**Outputs:** ✔ **Presentation** – the file in a line `HTML_FILE: <path>` with slides, languages and options;
✖ **Error** – why not.

**How:** a Claude agent of the plugin (your subscription; model in the settings) writes the slides as JSON – per slide
the HTML in every language, the light and dark colours and the CSS of its layouts; it may read the template and the
style guide. The plugin checks it (every slide in every language, tags closed, no scripts or event handlers, not too
much text) and sends problems back (up to two rounds). The frame – stage, navigation, switches – is the plugin's own,
so it always works the same. In the chat: a card with **Present** and **Show folder**.

Needs Theron 0.20.
