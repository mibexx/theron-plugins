"""The Trello REST API – the few calls the sync needs (https://developer.atlassian.com/cloud/trello/rest/)."""

from __future__ import annotations

import re

API = "https://api.trello.com/1"


class TrelloError(RuntimeError):
    pass


class TrelloAuthError(TrelloError):
    """Trello doesn't accept the API key or the token."""


def board_id(text: str) -> str:
    """A board's id or short link from what the user pasted: "AbCd1234", "https://trello.com/b/AbCd1234/name"."""
    text = (text or "").strip()
    m = re.search(r"trello\.com/b/([A-Za-z0-9]+)", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{6,32}", text):
        return text
    raise TrelloError("That is no Trello board id or board link.")


class Trello:
    def __init__(self, ctx):
        self.ctx = ctx

    def configured(self) -> bool:
        return bool(self.ctx.settings.get("api_key") and self.ctx.settings.get("token"))

    async def call(self, method: str, path: str, auth: dict | None = None, **params):
        """``auth`` ({"key", "token"}) instead of the saved settings – the settings' “Test” button checks what is in
        the dialog before it's saved."""
        if auth is None:
            if not self.configured():
                raise TrelloError(self.ctx.tr("Enter your Trello API key and token in the plugin settings first."))
            auth = {"key": self.ctx.settings.get("api_key"), "token": self.ctx.settings.get("token")}
        resp = await self.ctx.http.request(method, API + path, params={**auth, **params})
        if resp.status in (401, 403):
            raise TrelloAuthError(self.ctx.tr("Trello refused the access – check the API key and token."))
        if resp.status == 404:
            raise TrelloError(self.ctx.tr("Not found on Trello: {path}", path=path.split("?")[0]))
        if not resp.ok:
            raise TrelloError(f"Trello: HTTP {resp.status} {resp.text[:200]}")
        return resp.json()

    # ---- reading
    async def me(self, auth: dict | None = None) -> dict:
        return await self.call("GET", "/members/me", auth=auth, fields="fullName,username")

    async def my_boards(self, auth: dict | None = None) -> list[dict]:
        """The open boards of the account – for picking one instead of pasting its link."""
        boards = await self.call("GET", "/members/me/boards", auth=auth, filter="open", fields="name,url,closed")
        return sorted((b for b in boards if not b.get("closed")), key=lambda b: (b.get("name") or "").lower())

    async def test(self, api_key: str, token: str) -> tuple[bool, str]:
        """The settings' “Test connection”: does Trello accept the key and token, how many boards are there?"""
        t = self.ctx.tr
        if not (api_key or "").strip() or not (token or "").strip():
            return False, t("Enter the API key and the token first.")
        auth = {"key": api_key.strip(), "token": token.strip()}
        try:
            me = await self.me(auth)
            boards = await self.my_boards(auth)
        except TrelloError as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001 – network errors are shown in the dialog
            return False, t("No connection to Trello: {error}", error=exc)
        return True, t("Connected as {name} · open boards: {boards}",
                       name=me.get("fullName") or me.get("username") or "?", boards=len(boards))

    async def board(self, bid: str) -> dict:
        return await self.call("GET", f"/boards/{bid}", fields="name,closed,url")

    async def lists(self, bid: str) -> list[dict]:
        return await self.call("GET", f"/boards/{bid}/lists", filter="open", fields="name,pos,closed")

    async def cards(self, bid: str) -> list[dict]:
        return await self.call("GET", f"/boards/{bid}/cards", filter="open",
                               fields="name,desc,idList,idLabels,dueComplete,pos,closed")

    async def labels(self, bid: str) -> list[dict]:
        return await self.call("GET", f"/boards/{bid}/labels", fields="name,color")

    # ---- writing
    async def add_list(self, bid: str, name: str) -> dict:
        return await self.call("POST", "/lists", name=name, idBoard=bid, pos="bottom")

    async def update_list(self, list_id: str, **fields) -> dict:
        return await self.call("PUT", f"/lists/{list_id}", **fields)

    async def add_card(self, list_id: str, name: str, desc: str, label_ids: list[str]) -> dict:
        return await self.call("POST", "/cards", idList=list_id, name=name, desc=desc, idLabels=",".join(label_ids),
                               pos="bottom")

    async def update_card(self, card_id: str, **fields) -> dict:
        if "idLabels" in fields and isinstance(fields["idLabels"], list):
            fields["idLabels"] = ",".join(fields["idLabels"])
        return await self.call("PUT", f"/cards/{card_id}", **fields)

    async def add_label(self, bid: str, name: str, color: str | None) -> dict:
        return await self.call("POST", "/labels", idBoard=bid, name=name, **({"color": color} if color else {}))
