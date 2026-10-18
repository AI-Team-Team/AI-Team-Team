"""Track actual writer SQL, including mutations outside snapshot-based writes."""

import re

from sqlalchemy import event

from ai_team_team.database.models import Base


_DML = re.compile(r'^\s*(INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)\s+["`\[]?(\w+)', re.I)

# Only these complete writer statements have a known derived-only effect.
# A mention in a literal, comment, CTE, or lookalike table proves nothing.
_DERIVED_FTS_STATEMENTS = frozenset(" ".join(sql.split()).upper() for sql in (
    "CREATE VIRTUAL TABLE IF NOT EXISTS agent_memory_cards_fts "
    "USING fts5(memory_id UNINDEXED, agent_id UNINDEXED, title, summary, tags)",
    "DROP TABLE agent_memory_cards_fts",
    "DELETE FROM agent_memory_cards_fts",
    "DELETE FROM agent_memory_cards_fts WHERE memory_id = ?",
    "DELETE FROM agent_memory_cards_fts WHERE agent_id = ?",
    "INSERT INTO agent_memory_cards_fts (memory_id, agent_id, title, summary, tags) "
    "VALUES (?, ?, ?, ?, ?)",
))


class MutationTracker:
    """A store-local epoch invalidates reuse after unobserved session writes."""

    def __init__(self, engine):
        self.epoch = 0
        self.active = False
        self.touched = set()
        self.deleted = set()
        self.uncertain = False
        event.listen(engine, "after_cursor_execute", self.observe)

    def start(self):
        self.active = True
        self.touched = set()
        self.deleted = set()
        self.uncertain = False

    def observe(self, connection, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        expression = getattr(compiled, "statement", None)
        table = getattr(expression, "table", None)
        name = getattr(table, "name", None)
        deletion = bool(getattr(context, "isdelete", False))
        mutation = any(bool(getattr(context, field, False)) for field in ("isinsert", "isupdate", "isdelete"))
        if not mutation:
            match = _DML.match(statement)
            if match:
                name = match.group(2)
                mutation = True
                deletion = match.group(1).upper().startswith("DELETE")
            elif statement.lstrip().upper().startswith(("SELECT", "PRAGMA", "BEGIN", "SAVEPOINT", "RELEASE", "ROLLBACK")):
                return
            else:
                mutation = True
                name = None
        if not mutation:
            return
        self.epoch += 1
        if not self.active:
            return
        if name in Base.metadata.tables:
            self.touched.add(name)
            if deletion:
                self.deleted.add(name)
        elif not statement.isascii() or " ".join(statement.split()).upper() not in _DERIVED_FTS_STATEMENTS:
            self.uncertain = True

    def affected_tables(self):
        """Refresh possible native CASCADE/SET NULL effects, not only direct DML."""
        result = set(self.touched)
        pending = list(self.deleted)
        pending.extend(target for target in self.touched if any(
            fk.column.table.name == target and fk.onupdate in {"CASCADE", "SET NULL", "SET DEFAULT"}
            for table in Base.metadata.tables.values() for fk in table.foreign_keys))
        # Unchanged dependants are still checked by the value-only rules.
        # Refresh their SQL values only when native FK actions can change them.
        visited = set()
        while pending:
            target = pending.pop()
            if target in visited:
                continue
            visited.add(target)
            for name, table in Base.metadata.tables.items():
                if any(fk.column.table.name == target for fk in table.foreign_keys):
                    result.add(name)
                    if name not in visited:
                        pending.append(name)
        return result
