"""Token-bounded model-facing text file reading."""

import asyncio
import hashlib
import inspect
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Optional, TextIO, Union

from pydantic import BaseModel, ConfigDict, Field


class FileReadStatus(str, Enum):
    """Completion state for one requested source range."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class TokenCountResult(BaseModel):
    """Describes one exact or conservative content token count."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    count: int = Field(ge=0)
    method: str
    estimated: bool
    model_alias: str


class FileReadResult(BaseModel):
    """A token-bounded source range and its continuation coordinates."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: FileReadStatus
    content: str
    start_line: int = Field(ge=1)
    start_character: int = Field(ge=1)
    next_line: Optional[int] = Field(default=None, ge=1)
    next_character: Optional[int] = Field(default=None, ge=1)
    file_version: str
    model_alias: str
    content_token_count: int = Field(ge=0)
    max_read_tokens: int = Field(ge=1)
    token_count_method: str
    estimated: bool


class FileReadError(Exception):
    """Base error with a stable classification and privacy-safe message."""

    def __init__(self, message: str, *, error_kind: str) -> None:
        self.error_kind = error_kind
        super().__init__(message)


class FileReadRangeError(FileReadError):
    """Raised when requested source coordinates are invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_kind="invalid_file_range")


class FileDecodingError(FileReadError):
    """Raised when managed text is not valid UTF-8."""

    def __init__(self) -> None:
        super().__init__(
            "The requested file is not valid UTF-8 text.",
            error_kind="file_decoding_error",
        )


class FileVersionChangedError(FileReadError):
    """Raised when a continuation no longer addresses the same file version."""

    def __init__(self) -> None:
        super().__init__(
            "The file changed after the read cursor was created.",
            error_kind="file_version_changed",
        )


class TokenCounterUnavailableError(FileReadError):
    """Raised when strict token counting has no usable counter."""

    def __init__(
        self,
        message: str = "No token counter is available for the effective model.",
    ) -> None:
        super().__init__(message, error_kind="token_counter_unavailable")


@dataclass(frozen=True)
class FileSourceSlice:
    """Internal decoded source prefix returned by a secure storage reader."""

    content: str
    request_complete: bool
    next_line: Optional[int]
    next_character: Optional[int]
    file_version: str


TokenCounterValue = Union[int, TokenCountResult]
TokenCounter = Callable[
    [str], Union[TokenCounterValue, Awaitable[TokenCounterValue]]
]
SourceReader = Callable[
    ..., Union[FileSourceSlice, Awaitable[FileSourceSlice]]
]


def _validate_range(
    start_line: int,
    end_line: Optional[int],
    start_character: int,
    character_count: Optional[int],
) -> None:
    for name, value in {
        "start_line": start_line,
        "start_character": start_character,
    }.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise FileReadRangeError(f"{name} must be a positive integer.")
    if end_line is not None and (
        not isinstance(end_line, int)
        or isinstance(end_line, bool)
        or end_line < start_line
    ):
        raise FileReadRangeError(
            "end_line must be greater than or equal to start_line."
        )
    if character_count is not None and (
        not isinstance(character_count, int)
        or isinstance(character_count, bool)
        or character_count < 1
    ):
        raise FileReadRangeError("character_count must be a positive integer.")
    if end_line is not None and character_count is not None:
        raise FileReadRangeError(
            "end_line and character_count are mutually exclusive."
        )


def validate_file_read_range(
    start_line: int,
    end_line: Optional[int],
    start_character: int,
    character_count: Optional[int],
    expected_file_version: Optional[str] = None,
) -> None:
    """Validates public file coordinates before storage or counter access."""

    _validate_range(start_line, end_line, start_character, character_count)
    if expected_file_version is not None and (
        not isinstance(expected_file_version, str)
        or not expected_file_version
    ):
        raise FileReadRangeError(
            "expected_file_version must be a non-empty string when provided."
        )


def file_version_from_stat(stat_result: os.stat_result) -> str:
    """Returns an opaque operational version for one open file identity."""

    identity = ":".join(
        str(value)
        for value in (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_size,
            stat_result.st_mtime_ns,
            stat_result.st_ctime_ns,
        )
    )
    return hashlib.sha256(identity.encode("ascii")).hexdigest()


def read_text_stream_selection(
    stream: TextIO,
    *,
    start_line: int = 1,
    end_line: Optional[int] = None,
    start_character: int = 1,
    character_count: Optional[int] = None,
    maximum_characters: Optional[int] = None,
    expected_file_version: Optional[str] = None,
) -> FileSourceSlice:
    """Reads one normalized Unicode prefix without loading an unbounded line."""

    validate_file_read_range(
        start_line,
        end_line,
        start_character,
        character_count,
        expected_file_version,
    )
    if maximum_characters is not None and (
        not isinstance(maximum_characters, int)
        or isinstance(maximum_characters, bool)
        or maximum_characters < 0
    ):
        raise ValueError("maximum_characters must be a non-negative integer.")

    before = os.fstat(stream.fileno())
    version = file_version_from_stat(before)
    if expected_file_version is not None and expected_file_version != version:
        raise FileVersionChangedError()

    line_number = 1
    character_number = 1
    started = False
    selected: list[str] = []
    request_complete = False
    next_line: Optional[int] = None
    next_character: Optional[int] = None
    stop = False

    try:
        while not stop:
            chunk = stream.read(8192)
            if not chunk:
                break
            for source_character in chunk:
                if not started:
                    if line_number > start_line:
                        raise FileReadRangeError(
                            "start_character is beyond the requested start line."
                        )
                    if line_number == start_line:
                        if character_number == start_character:
                            started = True
                        elif source_character == "\n":
                            raise FileReadRangeError(
                                "start_character is beyond the requested start line."
                            )
                    if not started:
                        if source_character == "\n":
                            line_number += 1
                            character_number = 1
                        else:
                            character_number += 1
                        continue

                if end_line is not None and line_number > end_line:
                    request_complete = True
                    stop = True
                    break
                if character_count is not None and len(selected) >= character_count:
                    request_complete = True
                    stop = True
                    break
                if (
                    maximum_characters is not None
                    and len(selected) >= maximum_characters
                ):
                    next_line = line_number
                    next_character = character_number
                    stop = True
                    break

                selected.append(source_character)
                previous_line = line_number
                if source_character == "\n":
                    line_number += 1
                    character_number = 1
                else:
                    character_number += 1

                if character_count is not None and len(selected) >= character_count:
                    request_complete = True
                    stop = True
                    break
                if (
                    end_line is not None
                    and source_character == "\n"
                    and previous_line == end_line
                ):
                    request_complete = True
                    stop = True
                    break
    except UnicodeDecodeError as exc:
        raise FileDecodingError() from exc

    if not started:
        if line_number == start_line and character_number == start_character:
            started = True
        elif line_number < start_line:
            raise FileReadRangeError("start_line is beyond the end of the file.")
        else:
            raise FileReadRangeError(
                "start_character is beyond the requested start line."
            )

    if not stop:
        request_complete = True
    if request_complete:
        next_line = None
        next_character = None

    after = os.fstat(stream.fileno())
    if file_version_from_stat(after) != version:
        raise FileVersionChangedError()
    return FileSourceSlice(
        content="".join(selected),
        request_complete=request_complete,
        next_line=next_line,
        next_character=next_character,
        file_version=version,
    )


def _advance_position(
    start_line: int, start_character: int, text: str
) -> tuple[int, int]:
    line_number = start_line
    character_number = start_character
    for character in text:
        if character == "\n":
            line_number += 1
            character_number = 1
        else:
            character_number += 1
    return line_number, character_number


class GatedFileReader:
    """Returns the largest requested text prefix within a content-token budget."""

    def __init__(
        self,
        max_read_tokens: int = 4_000,
        tokenizer_fallback: Literal["conservative", "strict"] = "conservative",
        *,
        token_counter: Optional[TokenCounter] = None,
        model_alias: str = "unscoped",
        source_reader: Optional[SourceReader] = None,
    ) -> None:
        if (
            not isinstance(max_read_tokens, int)
            or isinstance(max_read_tokens, bool)
            or max_read_tokens < 1
        ):
            raise ValueError("max_read_tokens must be a positive integer.")
        if tokenizer_fallback not in {"conservative", "strict"}:
            raise ValueError(
                "tokenizer_fallback must be conservative or strict."
            )
        if not isinstance(model_alias, str) or not model_alias:
            raise ValueError("model_alias must be a non-empty string.")
        self.max_read_tokens = max_read_tokens
        self.tokenizer_fallback = tokenizer_fallback
        self.token_counter = token_counter
        self.model_alias = model_alias
        self.source_reader = source_reader
        self._counter_baseline: Optional[TokenCountResult] = None

    async def _count_raw(self, text: str) -> TokenCountResult:
        if self.token_counter is None:
            if self.tokenizer_fallback == "strict":
                raise TokenCounterUnavailableError()
            return TokenCountResult(
                count=len(text.encode("utf-8")),
                method="utf8_bytes_upper_bound",
                estimated=True,
                model_alias=self.model_alias,
            )
        try:
            if inspect.iscoroutinefunction(self.token_counter):
                result = self.token_counter(text)
            else:
                result = await asyncio.to_thread(self.token_counter, text)
            if inspect.isawaitable(result):
                result = await result
        except FileReadError:
            raise
        except Exception as exc:
            raise TokenCounterUnavailableError(
                "The selected token counter failed."
            ) from exc
        if isinstance(result, TokenCountResult):
            return result
        if not isinstance(result, int) or isinstance(result, bool) or result < 0:
            raise TokenCounterUnavailableError(
                "The selected token counter returned an invalid result."
            )
        return TokenCountResult(
            count=result,
            method="host_counter",
            estimated=False,
            model_alias=self.model_alias,
        )

    async def _count(self, text: str) -> TokenCountResult:
        """Counts content tokens after removing fixed counter framing."""

        raw = await self._count_raw(text)
        if not text:
            return raw.model_copy(update={"count": 0})
        if self._counter_baseline is None:
            baseline = await self._count_raw("")
            if (
                baseline.method != raw.method
                or baseline.model_alias != raw.model_alias
                or baseline.estimated != raw.estimated
            ):
                raise TokenCounterUnavailableError(
                    "The selected token counter returned inconsistent metadata."
                )
            self._counter_baseline = baseline
        return raw.model_copy(
            update={"count": max(0, raw.count - self._counter_baseline.count)}
        )

    async def _read_source(self, path: str, **kwargs: Any) -> FileSourceSlice:
        if self.source_reader is not None:
            if inspect.iscoroutinefunction(self.source_reader):
                result = self.source_reader(path, **kwargs)
            else:
                result = await asyncio.to_thread(
                    self.source_reader, path, **kwargs
                )
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, FileSourceSlice):
                raise TypeError("source_reader must return FileSourceSlice.")
            return result
        return await asyncio.to_thread(self._read_path, path, **kwargs)

    @staticmethod
    def _read_path(path: str, **kwargs: Any) -> FileSourceSlice:
        with open(
            path,
            "r",
            encoding="utf-8",
            errors="strict",
            newline=None,
        ) as stream:
            return read_text_stream_selection(stream, **kwargs)

    async def _validate_source_version(self, path: str, file_version: str) -> None:
        """Rechecks the addressed path after token counting completes."""

        try:
            await self._read_source(
                path,
                start_line=1,
                end_line=None,
                start_character=1,
                character_count=None,
                maximum_characters=0,
                expected_file_version=file_version,
            )
        except FileNotFoundError as exc:
            raise FileVersionChangedError() from exc

    async def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
        start_character: int = 1,
        character_count: Optional[int] = None,
        expected_file_version: Optional[str] = None,
    ) -> FileReadResult:
        """Reads a selected range and returns a token-safe continuation."""

        validate_file_read_range(
            start_line,
            end_line,
            start_character,
            character_count,
            expected_file_version,
        )
        if self.token_counter is None and self.tokenizer_fallback == "strict":
            raise TokenCounterUnavailableError()

        probe_characters = max(256, self.max_read_tokens * 4)
        version = expected_file_version
        source: Optional[FileSourceSlice] = None
        count: Optional[TokenCountResult] = None
        while True:
            source = await self._read_source(
                path,
                start_line=start_line,
                end_line=end_line,
                start_character=start_character,
                character_count=character_count,
                maximum_characters=probe_characters,
                expected_file_version=version,
            )
            if version is None:
                version = source.file_version
            count = await self._count(source.content)
            if count.count > self.max_read_tokens or source.request_complete:
                break
            probe_characters *= 2

        if source is None or count is None:
            raise RuntimeError("File reading did not produce a source candidate.")
        if count.count <= self.max_read_tokens:
            await self._validate_source_version(path, source.file_version)
            return FileReadResult(
                status=FileReadStatus.COMPLETE,
                content=source.content,
                start_line=start_line,
                start_character=start_character,
                file_version=source.file_version,
                model_alias=count.model_alias,
                content_token_count=count.count,
                max_read_tokens=self.max_read_tokens,
                token_count_method=count.method,
                estimated=count.estimated,
            )

        lower = 0
        upper = len(source.content)
        best_count = await self._count("")
        while lower < upper:
            midpoint = (lower + upper + 1) // 2
            candidate_count = await self._count(source.content[:midpoint])
            if candidate_count.count <= self.max_read_tokens:
                lower = midpoint
                best_count = candidate_count
            else:
                upper = midpoint - 1
        content = source.content[:lower]
        if lower == 0:
            best_count = await self._count("")
        next_line, next_character = _advance_position(
            start_line, start_character, content
        )
        await self._validate_source_version(path, source.file_version)
        return FileReadResult(
            status=FileReadStatus.PARTIAL,
            content=content,
            start_line=start_line,
            start_character=start_character,
            next_line=next_line,
            next_character=next_character,
            file_version=source.file_version,
            model_alias=best_count.model_alias,
            content_token_count=best_count.count,
            max_read_tokens=self.max_read_tokens,
            token_count_method=best_count.method,
            estimated=best_count.estimated,
        )


__all__ = [
    "FileDecodingError",
    "FileReadError",
    "FileReadRangeError",
    "FileReadResult",
    "FileReadStatus",
    "FileSourceSlice",
    "FileVersionChangedError",
    "GatedFileReader",
    "TokenCountResult",
    "TokenCounterUnavailableError",
    "file_version_from_stat",
    "read_text_stream_selection",
    "validate_file_read_range",
]
