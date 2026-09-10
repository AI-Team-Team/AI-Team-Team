"""Token-bounded model-facing reads for LibraryService."""

import asyncio
import inspect
from typing import Any, Callable, Optional

from ai_team_team.doc_library import DocumentLibrary
from ai_team_team.gated_reader import (
    FileReadResult,
    GatedFileReader,
    validate_file_read_range,
)


class ModelReadMixin:
    async def _read_model_file(
        self,
        agent,
        library: DocumentLibrary,
        path: str,
        *,
        start_line: int = 1,
        end_line: Optional[int] = None,
        start_character: int = 1,
        character_count: Optional[int] = None,
        expected_file_version: Optional[str] = None,
        source_reader: Optional[Callable[..., Any]] = None,
        final_validator: Optional[Callable[[FileReadResult], Any]] = None,
    ) -> FileReadResult:
        """Reads one secure DocLib range using the current Agent model."""

        validate_file_read_range(
            start_line,
            end_line,
            start_character,
            character_count,
            expected_file_version,
        )
        config = self.manager.config.file_read
        max_read_tokens = config.max_read_tokens
        tokenizer_fallback = config.tokenizer_fallback
        alias, counter = await self.manager._runtime.resolve_file_token_counter(
            agent,
            tokenizer_fallback,
        )

        if source_reader is None:
            async def read_source(source_path: str, **kwargs):
                return await asyncio.to_thread(
                    library.read_file_slice,
                    source_path,
                    **kwargs,
                )
        else:
            read_source = source_reader

        reader = GatedFileReader(
            max_read_tokens=max_read_tokens,
            tokenizer_fallback=tokenizer_fallback,
            token_counter=counter,
            model_alias=alias,
            source_reader=read_source,
        )
        result = await reader.read_file(
            path,
            start_line=start_line,
            end_line=end_line,
            start_character=start_character,
            character_count=character_count,
            expected_file_version=expected_file_version,
        )
        if final_validator is not None:
            validated = final_validator(result)
            if inspect.isawaitable(validated):
                await validated
        return result

    def _require_team_model_read_context(self, team_id: str):
        agent = self.manager._active_tool_agent.get()
        team = self.manager._active_team.get()
        if agent is None or team is None:
            raise PermissionError(
                "Model-facing DocLib reads require an active AgentTeam invocation."
            )
        if (
            team.team_id != team_id
            or self.manager.teams.get(team_id) is not team
            or agent not in team.members
            or self.manager._agents_by_id.get(agent.agent_id) is not agent
            or agent.lifecycle_state != "active"
        ):
            raise PermissionError(
                "The active Agent is not a member of the requested AgentTeam."
            )
        return agent
