"""Provider-neutral Tool contract and argument validation."""

import asyncio
import inspect
import json
import logging
import typing
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JSONSchemaValidationError
from pydantic import BaseModel, PydanticUserError, TypeAdapter, ValidationError

from ..core.exceptions import ATTException, ToolArgumentError, ToolError
from .schema import _resolve_schema


logger = logging.getLogger("ATT.Tools")


class Tool:
    """Encapsulates an AI tool with name, description, and execution logic."""

    name: str
    description: str
    func: Callable[..., Any]
    schema_source: Optional[Any]
    json_schema: Dict[str, Any]
    prompt_schema_mode: Optional[str]
    examples: List[Dict[str, Any]]
    retry_safe: bool

    def __init__(
        self,
        name: Any = None,
        description: Optional[str] = None,
        func: Optional[Callable[..., Any]] = None,
        schema: Optional[Any] = None,
        *,
        prompt_schema_mode: Optional[str] = None,
        examples: Optional[List[Dict[str, Any]]] = None,
        retry_safe: bool = False,
    ):
        # Resolve positional arguments vs keyword arguments
        if callable(name):
            func = name
            name = getattr(func, "__name__", "custom_tool")
            
        if func is None:
            raise ValueError("A callable function must be provided to create a Tool.")

        if not name:
            name = getattr(func, "__name__", "custom_tool")

        if not description:
            doc = getattr(func, "__doc__", None)
            if doc:
                description = doc.strip().split("\n")[0].strip()
            else:
                description = f"Execute function {name}"

        self.name = name
        self.description = description
        self.func = func
        self.schema_source = schema
        try:
            self.json_schema = _resolve_schema(func, description, schema)
        except PydanticUserError as exc:
            if exc.code == "typed-dict-version":
                raise ValueError(
                    f"Tool {name!r} uses typing.TypedDict, which Pydantic does not support "
                    "before Python 3.12. Import TypedDict, Required, and NotRequired "
                    "from typing_extensions."
                ) from exc
            raise
        try:
            Draft202012Validator.check_schema(self.json_schema)
        except SchemaError as exc:
            raise ValueError(f"Invalid JSON Schema for tool {name!r}: {exc}") from exc
        if prompt_schema_mode not in {
            None,
            "compact",
            "full",
            "compact_with_examples",
        }:
            raise ValueError("Invalid tool prompt schema mode.")
        if not isinstance(retry_safe, bool):
            raise ValueError("retry_safe must be a boolean.")
        self.prompt_schema_mode = prompt_schema_mode
        self.examples = list(examples or [])
        self.retry_safe = retry_safe
        self._signature = inspect.signature(func)
        try:
            self._type_hints = get_type_hints(func)
        except (NameError, TypeError):
            self._type_hints = {}
        self._json_validator = Draft202012Validator(self.json_schema)

    def validate_arguments(
        self, args: List[Any], kwargs: Dict[str, Any]
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """Strictly validates one invocation before any tool code runs."""
        try:
            bound = self._signature.bind(*args, **kwargs)
        except TypeError as exc:
            raise ToolArgumentError(str(exc)) from exc

        mapping = dict(bound.arguments)
        raw_mapping = dict(mapping)
        try:
            if isinstance(self.schema_source, type) and issubclass(
                self.schema_source, BaseModel
            ):
                validated = self.schema_source.model_validate_json(
                    json.dumps(mapping), strict=True
                )
                mapping = validated.model_dump(
                    mode="python", exclude_unset=True
                )
            elif self.schema_source is not None and typing.is_typeddict(
                self.schema_source
            ):
                mapping = TypeAdapter(self.schema_source).validate_json(
                    json.dumps(mapping), strict=True
                )
            else:
                for name, value in list(mapping.items()):
                    hint = self._type_hints.get(name, Any)
                    if hint is not Any:
                        mapping[name] = TypeAdapter(hint).validate_json(
                            json.dumps(value), strict=True
                        )
            self._json_validator.validate(raw_mapping)
        except (
            ValidationError,
            JSONSchemaValidationError,
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise ToolArgumentError(str(exc)) from exc

        for name, value in mapping.items():
            bound.arguments[name] = value
        return list(bound.args), dict(bound.kwargs)

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        checked_args, checked_kwargs = self.validate_arguments(
            list(args), dict(kwargs)
        )
        return await self.invoke_validated(*checked_args, **checked_kwargs)

    async def invoke_validated(self, *args: Any, **kwargs: Any) -> Any:
        """Invokes a callable after the shared executor has validated input."""
        if inspect.iscoroutinefunction(self.func):
            return await self.func(*args, **kwargs)
        return await asyncio.to_thread(
            self.func, *args, **kwargs
        )

    @staticmethod
    def serialize_result(res: Any) -> str:
        if isinstance(res, BaseModel):
            return res.model_dump_json()
        if isinstance(res, Mapping):
            return json.dumps(dict(res), sort_keys=True)
        return str(res)

    async def __call__(self, *args, **kwargs) -> str:
        try:
            return self.serialize_result(await self.invoke(*args, **kwargs))
        except ToolError as exc:
            return f"Error: {exc}"
        except Exception as e:
            if isinstance(e, ATTException):
                raise e
            logger.error(f"Error executing tool '{self.name}': {e}")
            return f"Error executing tool '{self.name}': {e}"

