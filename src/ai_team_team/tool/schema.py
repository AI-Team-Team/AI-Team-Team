"""JSON Schema generation for provider-neutral tools."""

import inspect
import typing
from typing import Any, Callable, Dict, Optional, get_type_hints

from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model


def _schema_from_typeddict(tp: Any, description: str) -> Dict[str, Any]:
    schema = TypeAdapter(tp).json_schema()
    schema["additionalProperties"] = False
    schema["description"] = description
    return schema


def _schema_from_function(func: Callable[..., Any], description: str) -> Dict[str, Any]:
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)
    fields = {}
    for param_name, param in sig.parameters.items():
        if param_name in ('self', 'cls'):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
            
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (type_hints.get(param_name, Any), default)
    model = create_model(
        f"{getattr(func, '__name__', 'Tool')}Arguments",
        __config__=ConfigDict(extra="forbid", strict=True),
        **fields,
    )
    schema = model.model_json_schema()
    schema["description"] = description
    return schema

def _schema_from_pydantic(model: Any, description: str) -> Dict[str, Any]:
    if hasattr(model, "model_json_schema"):
        schema = model.model_json_schema()
    else:
        schema = model.schema()
    if "description" not in schema or not schema["description"]:
        schema["description"] = description
    return schema

def _resolve_schema(func: Callable[..., Any], description: str, schema_source: Optional[Any] = None) -> Dict[str, Any]:
    if isinstance(schema_source, dict):
        return schema_source
        
    is_pydantic = False
    try:
        from pydantic import BaseModel
        if isinstance(schema_source, type) and issubclass(schema_source, BaseModel):
            is_pydantic = True
    except ImportError:
        pass
        
    if is_pydantic:
        return _schema_from_pydantic(schema_source, description)
        
    is_td = False
    try:
        from typing import is_typeddict as _is_td
        is_td = _is_td(schema_source)
    except ImportError:
        pass
    if not is_td:
        is_td = isinstance(schema_source, type) and hasattr(schema_source, "__annotations__") and hasattr(schema_source, "__total__")
        
    if is_td:
        return _schema_from_typeddict(schema_source, description)
        
    return _schema_from_function(func, description)
