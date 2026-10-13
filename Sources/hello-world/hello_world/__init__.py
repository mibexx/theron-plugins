"""Hello World – the smallest useful Theron plugin: a page in the navigation and a process node."""


def register(ctx):
    # --- the node: one input, ✔ and ✖ outputs; it only says Hello World and the process carries on via ✔
    async def hello(node):
        node.progress("Hello World")
        return node.success("Hello World")

    ctx.nodes.register(
        "hello-world", label="Hello World", icon="👋", run=hello, outputs="success_failure",
        description=ctx.tr("Says Hello World and carries on."),
        ai_hint="A greeting step without any work – only for trying out plugins")

    # --- the page: a navigation entry of its own (desktop app only – no PySide6 on a slave)
    if ctx.ui.available:
        from .page import HelloPage
        ctx.ui.add_page("Hello World", HelloPage, icon="👋")
