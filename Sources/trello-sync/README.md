# Trello Sync

Syncs a Theron task list with a Trello board – in the direction you choose.

**Setup:** Settings → Plugins → Trello Sync → *Settings …*: your Trello **API key** and **token**
(https://trello.com/power-ups/admin → your Power-Up → API key, then “Token” on that page). **Test connection** checks
them right there – also before saving – and shows the account and how many open boards it has.

**Use:** on the TASKS page select a task list and click **Sync with Trello**. Pick one of your boards from the list
(▼) – or paste a board's id or link (`https://trello.com/b/AbCd1234/…`). The plugin reads the board, shows what it
found and asks:

- **Read (Trello → Theron)** – every list of the board becomes an epic, every card a requirement.
- **Write (Theron → Trello)** – every epic becomes a list, every requirement a card.

From then on the button is **⟳ Sync** and syncs again in that direction. **Unlink Trello** removes the link (nothing is
deleted).

| Trello | Theron |
|---|---|
| list | epic |
| card name | requirement title |
| card description | description, then a bold **Acceptance criteria** heading and the acceptance criteria |
| label “Theron: done”, “Theron: in progress” … (also “Done”, “Doing”, “Blocked” … when reading; a completed due date = done) | status |

The first sync matches by name, so nothing is duplicated. Only what the sync linked is ever removed: requirements whose
card is gone (read), cards and lists whose requirement or epic was deleted are archived (write). Other lists, cards and
labels of the board stay untouched.
