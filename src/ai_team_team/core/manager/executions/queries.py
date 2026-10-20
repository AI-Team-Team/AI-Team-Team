"""Owner-filtered task metadata and independently authorized, bounded results."""

import secrets

from ai_team_team.core.activity.contracts import AgentTeamScope, PersonalScope
from ai_team_team.core.exceptions import ToolArgumentError, ToolBusinessError
from ai_team_team.core.execution import TaskPage, TaskView
from ai_team_team.database.persistence.records import thaw


class QueryMixin:
    def owned(self, execution_id, owner):
        row = self.manager._records.index.get(("executions", (execution_id,)))
        if row is None or row.values["agent_id"] != owner.agent_id:
            raise PermissionError("The requested execution is not owned by this Agent.")
        return row

    def result_authorized(self, row, owner):
        if self.manager.config.executions.retain_results_after_source_revocation:
            return True
        return self.source_authorized(row, owner)

    def source_authorized(self, row, owner, *, committing=False):
        for source in row.values["source_references"] or ():
            if source["kind"] != "library":
                if committing:
                    continue
                return False
            library = self.manager.libraries.get(source["lib_id"])
            if library is None:
                return False
            if library.library_kind == "agent_private":
                if library.owner_agent_id != owner.agent_id:
                    return False
            else:
                team_id = source["scope_team_id"]
                team = self.manager.teams.get(team_id)
                if (team is None or owner not in team.members
                        or getattr(team, "_lifecycle_state", "active") != "active"
                        or not self.manager.check_library_access(team_id, library.lib_id, source["path"] or "/", "READ")):
                    return False
        return row.values["source_references"] is not None

    def view(self, row, owner):
        values = row.values
        metadata = values["metadata"] or {}
        observations = [item for item in self.manager._records.snapshot() if item.table_name == "execution_observations"
                        and item.values["execution_id"] == values["execution_id"]]
        latest = max(enumerate(observations), key=lambda pair: (pair[1].values["observation_index"] or 0,
            pair[1].values["observed_at"], pair[0]), default=(0, None))[1]
        health = latest.values["health"] if latest else "unknown"
        result = self.manager._records.index.get(("execution_payloads", (f"RESULT-{values['execution_id']}",)))
        job = self.jobs.get(values["execution_id"])
        available = result is not None and self.result_authorized(row, owner) and (
            result.values["content"]["content"] is not None or job is not None and job.result is not None)
        controls = any(item.table_name == "execution_controls" and item.values["execution_id"] == values["execution_id"]
                       for item in self.manager._records.snapshot())
        return TaskView(execution_id=values["execution_id"], owner_agent_id=owner.agent_id,
            scope=AgentTeamScope(team_id=values["scope_team_id"]) if values["scope_kind"] == "agent_team" else PersonalScope(),
            tool_name=values["tool_name"], description=metadata.get("description", ""), labels=tuple(metadata.get("labels", ())),
            execution_state=values["status"], health_state=health, attention_state=values["attention"],
            visibility=values["visibility"], outcome_unconfirmed=bool(values["outcome_unconfirmed"]),
            created_at=values["created_at"], started_at=values["started_at"], finished_at=values["finished_at"],
            cancellation_requested=controls, result_available=bool(available))

    def inspect(self, execution_id, *, actor=None):
        with self.manager._resources.mutation():
            owner = self.actor(actor)
            return self.view(self.owned(execution_id, owner), owner)

    def list(self, *, actor=None, status=None, query=None, limit=50, cursor=None, include_foreground=False):
        with self.manager._resources.mutation():
            owner = self.actor(actor)
            if type(limit) is not int or not 1 <= limit <= 1000 or type(include_foreground) is not bool:
                raise ToolArgumentError("Task pagination requires a limit between 1 and 1000 and a boolean visibility flag.")
            if status not in {None, "queued", "running", "completed", "failed", "cancelled"}:
                raise ToolArgumentError("Unknown execution state filter.")
            if query is not None and (type(query) is not str or not query.strip()):
                raise ToolArgumentError("Task search requires nonblank text.")
            rows = [row for row in self.manager._records.snapshot() if row.table_name == "executions"
                    and row.values["agent_id"] == owner.agent_id
                    and (include_foreground or row.values["visibility"] != "foreground")
                    and (status is None or row.values["status"] == status)]
            if query:
                rows = [row for row in rows if query.casefold() in str((row.values["tool_name"], thaw(row.values["metadata"]))).casefold()]
            rows.sort(key=lambda row: (row.values["created_at"], row.values["execution_id"]))
            filters = (owner.agent_id, status, query, include_foreground)
            start = 0
            if cursor is not None:
                previous = self.cursors.get(cursor)
                if previous is None or previous[0] != filters:
                    raise ToolArgumentError("The task cursor does not belong to this owner and filter.")
                start = previous[1]
            selected = rows[start:start + limit]
            next_cursor = None
            if start + limit < len(rows):
                next_cursor = secrets.token_urlsafe(24)
                self.cursors[next_cursor] = filters, start + limit
            return TaskPage(items=tuple(self.view(row, owner) for row in selected), total_count=len(rows), next_cursor=next_cursor)

    def summary(self, owner):
        records = self.manager._records.snapshot()
        health = {}
        for record in records:
            if record.table_name == "execution_observations":
                key = record.values["execution_id"]
                latest = health.get(key)
                if latest is None or (record.values["observation_index"] or 0) >= (latest.values["observation_index"] or 0):
                    health[key] = record
        rows = [row.values for row in records if row.table_name == "executions"
                and row.values["agent_id"] == owner.agent_id and row.values["visibility"] != "foreground"]
        live = {key: sum(row["status"] == key and not row["outcome_unconfirmed"] for row in rows)
                for key in ("queued", "running")}
        uncertain = sum(row["outcome_unconfirmed"] for row in rows)
        attention = sum(row["attention"] == "required" for row in rows)
        terminal = {key: sum(row["status"] == key and row["attention"] == "required" for row in rows)
                    for key in ("completed", "failed", "cancelled")}
        stalled = sum(row["execution_id"] in health and health[row["execution_id"]].values["health"] == "stalled"
                      and row["attention"] != "acknowledged" for row in rows)
        return ("Background tasks: " + ", ".join(f"{value} {key}" for key, value in {**live, **terminal}.items())
                + f"; {stalled} stalled health, {attention} requiring attention, {uncertain} unconfirmed outcomes.")

    async def read_result(self, execution_id, *, actor=None, start_line=1, end_line=None,
                          start_character=1, character_count=None, expected_file_version=None):
        owner = self.actor(actor)
        row = self.owned(execution_id, owner)
        if not self.result_authorized(row, owner):
            raise PermissionError("Current source authorization is required for this retained result.")
        result = self.manager._records.index.get(("execution_payloads", (f"RESULT-{execution_id}",)))
        if result is None:
            raise ToolBusinessError("No confirmed result is available for this execution.")
        body = result.values["content"]["content"]
        if body is None:
            job = self.jobs.get(execution_id)
            if job is None or job.result is None:
                raise ToolBusinessError("This transient result was not retained across runtime replacement; no source was reread.")
            body = job.result.content
            session = self.manager._activity.current.get()
            job.transient_delivery_invocation = session.invocation_id if session is not None else None
        from ai_team_team.gated_reader import FileReadRangeError, FileSourceSlice, FileVersionChangedError

        def source_reader(_path, **selection):
            if selection["expected_file_version"] not in {None, result.values["digest"]}:
                raise FileVersionChangedError()
            text = body.replace("\r\n", "\n").replace("\r", "\n")
            lines = text.split("\n")
            line, character = selection["start_line"], selection["start_character"]
            if line > len(lines) or character > len(lines[line - 1]) + 1:
                raise FileReadRangeError("The requested range is beyond this execution result.")
            start = sum(len(item) + 1 for item in lines[:line - 1]) + character - 1
            end = len(text)
            if selection["end_line"] is not None:
                end = min(end, sum(len(item) + 1 for item in lines[:selection["end_line"]]))
            if selection["character_count"] is not None:
                end = min(end, start + selection["character_count"])
            stop = min(end, start + selection["maximum_characters"])
            content = text[start:stop]
            for char in content:
                line, character = (line + 1, 1) if char == "\n" else (line, character + 1)
            return FileSourceSlice(content, stop >= end, None if stop >= end else line,
                                   None if stop >= end else character, result.values["digest"])

        delivered = await self.manager._library_service._read_model_file(owner, None, execution_id,
            start_line=start_line, end_line=end_line, start_character=start_character, character_count=character_count,
            expected_file_version=expected_file_version, source_reader=source_reader)
        with self.manager._resources.mutation():
            if self.actor(owner) is not owner or not self.result_authorized(row, owner):
                raise PermissionError("Result authority changed while the content was being read.")
        return delivered
