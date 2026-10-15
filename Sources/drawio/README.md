# draw.io Diagrams

A process node **📐 Draw diagram** that draws **one** diagram per run from a description: the **.drawio** file (opens
in draw.io / diagrams.net) and a **PNG** of it. The picture shows in the chat – a click opens it **large** in a
window of its own (fit, 100 %, zoom with the buttons or Ctrl/⌘ + mouse wheel, **Open in draw.io**).

**Fields of the node**

| Field | |
|---|---|
| Description | What the diagram shows. Empty: the step's assignment and the hand-overs (e.g. one item of a loop). |
| Kind of diagram | **Automatic** (the kind named in the description – or a line `DIAGRAM_TYPE: sequence` – else the AI picks), or fixed: flowchart, sequence, UML class, activity, state, use case, ER, architecture, network, deployment, swimlane process, org chart, mind map, timeline, Venn. |
| Look / Direction | e.g. “black and white”, “our CI: #003366”; top to bottom or left to right. |
| Output folder / File name | Where both files go (relative to the project's workspace); nothing is overwritten. |
| PNG size | 1×, 2× (sharp) or 3× (print). |

**Outputs:** ✔ **Diagram** – the hand-over has the lines `DRAWIO_FILE: <path>` and `PNG_FILE: <path>`;
✖ **Error** – why not.

**Settings → draw.io** – who makes the PNG:

- **Draw it myself** – the plugin's own renderer: nothing to install, works on a slave and in Docker, too.
- **Use the desktop app** – the installed draw.io app. Choosing it checks right away whether draw.io is found; if
  not, a file dialog asks where the program is (a macOS `.app` is fine) and checks it.
- **Load via Docker** – draw.io headless in a container (`rlespinasse/drawio-desktop-headless`). Choosing it checks
  whether Docker is installed and running and whether the image is there; **Load Docker image** fetches it once.

**Test** turns a small test diagram into a PNG the chosen way.

**How:** Claude (your subscription; model in the settings) writes the draw.io XML; the plugin checks it (broken XML,
arrows to nothing, shapes without size, shapes on top of each other) and sends problems back (up to two rounds).

Needs Theron 0.20.
