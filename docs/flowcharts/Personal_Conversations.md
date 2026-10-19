# Personal Conversations and Relationship Authority

```mermaid
flowchart TD
    Invocation["Personal invocation: one continuing Agent"] --> Scope{"Explicit publication tool"}
    Scope --> Team["Captured current AgentTeam + active membership"]
    Scope --> Direct["Canonical pair + both endpoint lifecycles"]
    Team --> TeamLock["Shared relationship / team-state lock"]
    Direct --> PairLock["Pair lock: blocks, refusal, friendship, directional allowance"]
    TeamLock --> Commit["One source + views + notices + exact command transaction"]
    PairLock --> Commit
    Commit --> Receipt["Durable or explicit volatile receipt"]
    Receipt --> Notice["Eligible recipient's ordinary personal notification"]
    Notice --> Preview["Bounded unread preview; not reading or consent"]
    Preview --> Read["Explicit authorized token-gated source read"]
    Read --> ReadState["Commit only that person's read state"]
    TeamLock --> Leave["Leave or finalized dissolution"]
    Leave --> Frozen["Freeze exact departure references"]
    Frozen --> Archive["Personal historical inspection only"]
    TeamLock --> Edit["Current-member author edit or withdrawal"]
    Edit --> Live["Update eligible live views; retain personal deletion"]
    Frozen -. "No later shared updates" .-> Archive
```

Ordinary answers, tool observations, personal mail, AT-to-AT Agreements, and DocLib permissions do not implicitly publish chat content or grant conversation authority.

Source withdrawal exposes a marker in the live source while previously captured unread recipient reminders and authorized frozen archives retain their separate historical evidence.

Rejoining opens a new interval without revealing absence-period messages or updating an earlier frozen archive.
