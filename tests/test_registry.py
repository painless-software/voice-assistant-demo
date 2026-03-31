"""Tests for the decorator-based tool registry."""

from __future__ import annotations

from typing import Annotated

import pytest
from google.genai import types

from voice_assistant.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers -- create a fresh registry per test to avoid cross-contamination
# ---------------------------------------------------------------------------


def _fresh_registry() -> ToolRegistry:
    return ToolRegistry()


def _register_weather(reg: ToolRegistry) -> None:
    @reg.register
    def get_current_weather(
        city: Annotated[str, "City name, e.g. 'Zürich'"],
    ) -> dict:
        """Get the current weather for a given city."""
        return {"city": city, "temperature_celsius": 18}

    # register() is called as a method, not a decorator here -- need to call it
    # differently.  Let's just use the register method directly:
    pass


# We need a helper that uses the register method properly:

def _make_registry_with_weather() -> ToolRegistry:
    reg = ToolRegistry()

    def get_current_weather(
        city: Annotated[str, "City name, e.g. 'Zürich'"],
    ) -> dict:
        """Get the current weather for a given city."""
        return {"city": city, "temperature_celsius": 18}

    reg.register(get_current_weather)
    return reg


def _make_registry_with_tagged_tools() -> ToolRegistry:
    reg = ToolRegistry()

    def weather(city: Annotated[str, "City name"]) -> dict:
        """Get weather."""
        return {"city": city}

    def end_call(reason: Annotated[str, "Reason for ending"]) -> dict:
        """End the call."""
        return {"action": "end_call", "reason": reason}

    reg.register(weather, tags={"voice", "repl"})
    reg.register(end_call, tags={"voice"})
    return reg


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_function(self):
        reg = _make_registry_with_weather()
        assert "get_current_weather" in reg.names()

    def test_register_with_custom_name(self):
        reg = ToolRegistry()

        def my_func(x: str) -> dict:
            """Do something."""
            return {}

        reg.register(my_func, name="custom_tool")
        assert "custom_tool" in reg.names()
        assert "my_func" not in reg.names()

    def test_register_with_tags(self):
        reg = _make_registry_with_tagged_tools()
        assert "weather" in reg.names()
        assert "end_call" in reg.names()


# ---------------------------------------------------------------------------
# Declaration generation
# ---------------------------------------------------------------------------


class TestDeclarationGeneration:
    def test_generates_function_declaration(self):
        reg = _make_registry_with_weather()
        decls = reg.get_declarations()
        assert len(decls) == 1
        tool_obj = decls[0]
        assert isinstance(tool_obj, types.Tool)
        fd = tool_obj.function_declarations[0]
        assert fd.name == "get_current_weather"

    def test_declaration_has_description_from_docstring(self):
        reg = _make_registry_with_weather()
        fd = reg.get_declarations()[0].function_declarations[0]
        assert fd.description == "Get the current weather for a given city."

    def test_declaration_has_city_parameter(self):
        reg = _make_registry_with_weather()
        fd = reg.get_declarations()[0].function_declarations[0]
        assert "city" in fd.parameters.properties

    def test_declaration_city_is_string_type(self):
        reg = _make_registry_with_weather()
        fd = reg.get_declarations()[0].function_declarations[0]
        city_schema = fd.parameters.properties["city"]
        assert city_schema.type == types.Type.STRING

    def test_declaration_city_has_description(self):
        reg = _make_registry_with_weather()
        fd = reg.get_declarations()[0].function_declarations[0]
        city_schema = fd.parameters.properties["city"]
        assert city_schema.description == "City name, e.g. 'Zürich'"

    def test_declaration_city_is_required(self):
        reg = _make_registry_with_weather()
        fd = reg.get_declarations()[0].function_declarations[0]
        assert "city" in fd.parameters.required

    def test_optional_param_not_required(self):
        reg = ToolRegistry()

        def my_tool(
            name: Annotated[str, "Name"],
            verbose: Annotated[bool, "Verbose output"] = False,
        ) -> dict:
            """A tool."""
            return {}

        reg.register(my_tool)
        fd = reg.get_declarations()[0].function_declarations[0]
        assert "name" in fd.parameters.required
        assert "verbose" not in (fd.parameters.required or [])

    def test_int_param_maps_to_integer(self):
        reg = ToolRegistry()

        def my_tool(count: Annotated[int, "How many"]) -> dict:
            """A tool."""
            return {}

        reg.register(my_tool)
        fd = reg.get_declarations()[0].function_declarations[0]
        assert fd.parameters.properties["count"].type == types.Type.INTEGER

    def test_empty_registry_returns_no_declarations(self):
        reg = ToolRegistry()
        assert reg.get_declarations() == []


# ---------------------------------------------------------------------------
# Tag filtering
# ---------------------------------------------------------------------------


class TestTagFiltering:
    def test_no_filter_returns_all(self):
        reg = _make_registry_with_tagged_tools()
        decls = reg.get_declarations()
        names = [fd.name for fd in decls[0].function_declarations]
        assert "weather" in names
        assert "end_call" in names

    def test_filter_voice_returns_both(self):
        reg = _make_registry_with_tagged_tools()
        decls = reg.get_declarations(tags={"voice"})
        names = [fd.name for fd in decls[0].function_declarations]
        assert "weather" in names
        assert "end_call" in names

    def test_filter_repl_excludes_voice_only(self):
        reg = _make_registry_with_tagged_tools()
        decls = reg.get_declarations(tags={"repl"})
        names = [fd.name for fd in decls[0].function_declarations]
        assert "weather" in names
        assert "end_call" not in names

    def test_filter_nonexistent_tag_returns_empty(self):
        reg = _make_registry_with_tagged_tools()
        assert reg.get_declarations(tags={"nonexistent"}) == []


# ---------------------------------------------------------------------------
# Dispatch / execute
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_execute_known_tool(self):
        reg = _make_registry_with_weather()
        result = reg.execute("get_current_weather", {"city": "Bern"})
        assert result["city"] == "Bern"
        assert "temperature_celsius" in result

    def test_execute_unknown_tool(self):
        reg = _make_registry_with_weather()
        result = reg.execute("nonexistent", {})
        assert "error" in result

    def test_execute_tool_that_raises(self):
        reg = ToolRegistry()

        def failing_tool() -> dict:
            """Fails."""
            raise RuntimeError("boom")

        reg.register(failing_tool)
        result = reg.execute("failing_tool", {})
        assert "error" in result
        assert "RuntimeError" in result["error"]
