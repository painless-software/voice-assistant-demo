"""
Decorator-based tool registry.

Tools self-register via the ``@tool`` decorator which auto-generates a
Gemini ``FunctionDeclaration`` from the function's name, docstring, and
``Annotated`` type hints.

Usage::

    from voice_assistant.tools import tool, registry

    @tool
    def get_current_weather(
        city: Annotated[str, "City name, e.g. 'Zürich'"],
    ) -> dict:
        \"\"\"Get the current weather for a given city.\"\"\"
        return {"city": city, "temperature_celsius": 18}

    # At session setup time:
    declarations = registry.get_declarations()       # list[types.Tool]
    result       = registry.execute("get_current_weather", {"city": "Bern"})
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import time
from typing import Annotated, Any, Callable, get_type_hints

from google.genai import types

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Python type -> Gemini Schema type mapping
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[type, types.Type] = {
    str: types.Type.STRING,
    int: types.Type.INTEGER,
    float: types.Type.NUMBER,
    bool: types.Type.BOOLEAN,
}


def _python_type_to_schema(hint: Any, description: str | None = None) -> types.Schema:
    """Convert a Python type hint to a ``types.Schema``."""
    origin = getattr(hint, "__origin__", None)

    # list[X] -> ARRAY of X
    if origin is list:
        args = getattr(hint, "__args__", (str,))
        return types.Schema(
            type=types.Type.ARRAY,
            items=_python_type_to_schema(args[0]),
            description=description,
        )

    # dict -> OBJECT (untyped)
    if hint is dict or origin is dict:
        return types.Schema(type=types.Type.OBJECT, description=description)

    gemini_type = _TYPE_MAP.get(hint, types.Type.STRING)
    return types.Schema(type=gemini_type, description=description)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Holds registered tools and provides declaration / dispatch helpers."""

    def __init__(self) -> None:
        self._tools: dict[str, _RegisteredTool] = {}

    # -- registration -------------------------------------------------------

    def register(
        self,
        fn: Callable[..., dict],
        *,
        name: str | None = None,
        tags: set[str] | None = None,
    ) -> None:
        tool_name = name or fn.__name__
        hints = get_type_hints(fn, include_extras=True)
        hints.pop("return", None)

        sig = inspect.signature(fn)
        properties: dict[str, types.Schema] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            hint = hints.get(param_name, str)
            description: str | None = None

            # Extract description from Annotated[type, "description"]
            if getattr(hint, "__metadata__", None):
                for meta in hint.__metadata__:
                    if isinstance(meta, str):
                        description = meta
                        break
                # Unwrap Annotated to get the base type
                hint = hint.__args__[0]

            properties[param_name] = _python_type_to_schema(hint, description)

            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        declaration = types.FunctionDeclaration(
            name=tool_name,
            description=(fn.__doc__ or "").strip(),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties=properties,
                required=required if required else None,
            ),
        )

        self._tools[tool_name] = _RegisteredTool(
            name=tool_name,
            handler=fn,
            declaration=declaration,
            tags=tags or set(),
        )

    # -- query --------------------------------------------------------------

    def get_declarations(
        self, *, tags: set[str] | None = None
    ) -> list[types.Tool]:
        """Return a ``list[types.Tool]`` suitable for Gemini config.

        If *tags* is given, only include tools whose tags intersect.
        """
        _discover_tools()
        decls = [
            t.declaration
            for t in self._tools.values()
            if tags is None or t.tags & tags
        ]
        if not decls:
            return []
        return [types.Tool(function_declarations=decls)]

    def execute(self, name: str, args: dict) -> dict:
        """Dispatch a tool call by name. Returns the tool result dict."""
        _discover_tools()
        registered = self._tools.get(name)
        if registered is None:
            return {"error": f"Unknown tool: {name}"}

        # Filter args to only declared parameters (defense-in-depth)
        valid_params = set(inspect.signature(registered.handler).parameters)
        filtered_args = {k: v for k, v in args.items() if k in valid_params}

        start = time.monotonic()
        try:
            result = registered.handler(**filtered_args)
            duration_ms = (time.monotonic() - start) * 1000
            log.info(
                "tool.ok name=%s args=%s duration_ms=%.1f",
                name,
                _sanitize_args(filtered_args),
                duration_ms,
            )
            return result
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            log.error(
                "tool.error name=%s args=%s error=%s duration_ms=%.1f",
                name,
                _sanitize_args(filtered_args),
                exc,
                duration_ms,
            )
            # Return generic message to LLM; technical details stay in logs
            return {"error": "Tool execution failed. Please try again."}

    def names(self) -> list[str]:
        return list(self._tools.keys())


class _RegisteredTool:
    __slots__ = ("name", "handler", "declaration", "tags")

    def __init__(
        self,
        name: str,
        handler: Callable[..., dict],
        declaration: types.FunctionDeclaration,
        tags: set[str],
    ) -> None:
        self.name = name
        self.handler = handler
        self.declaration = declaration
        self.tags = tags


_SENSITIVE_KEYS = {"password", "token", "secret", "key", "ssn", "credit_card", "api_key"}


def _sanitize_args(args: dict) -> dict:
    """Return args with sensitive values redacted and long values truncated."""
    sanitized = {}
    for k, v in args.items():
        if any(s in k.lower() for s in _SENSITIVE_KEYS):
            sanitized[k] = "[REDACTED]"
        else:
            s = str(v)
            sanitized[k] = s[:100] + "..." if len(s) > 100 else s
    return sanitized


# ---------------------------------------------------------------------------
# Module-level singleton + decorator
# ---------------------------------------------------------------------------

registry = ToolRegistry()

_discovered = False


def _discover_tools() -> None:
    """Import all tool modules in this package so @tool decorators run."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    package_path = __path__
    for info in pkgutil.iter_modules(package_path):
        if info.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{info.name}")


def tool(
    fn: Callable[..., dict] | None = None,
    *,
    name: str | None = None,
    tags: set[str] | None = None,
) -> Callable[..., dict]:
    """Decorator that registers a function as an agent tool.

    Can be used bare (``@tool``) or with arguments
    (``@tool(tags={"voice"})``).
    """

    def _register(f: Callable[..., dict]) -> Callable[..., dict]:
        registry.register(f, name=name, tags=tags)
        return f

    if fn is not None:
        # Called as @tool without parens
        return _register(fn)
    # Called as @tool(...) with keyword args
    return _register
