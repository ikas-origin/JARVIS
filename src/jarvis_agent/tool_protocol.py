"""Tool interface, registry, validation, and error conversion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import JarvisError, ToolError
from .policy import Policy
from .types import ToolResult


ToolHandler = Callable[[dict[str, Any], Policy], ToolResult]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def api_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool], policy: Policy) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("Tool names must be unique")
        self.policy = policy

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [tool.api_schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, f"Unknown tool: {name}")
        try:
            self._validate(arguments, tool.parameters)
            return tool.handler(arguments, self.policy)
        except JarvisError as error:
            return ToolResult(False, str(error), {"error_type": error.code})
        except (OSError, UnicodeError) as error:
            return ToolResult(False, f"Local tool failed: {error}", {"error_type": "os_error"})
        except Exception as error:  # defensive boundary around tool plugins
            return ToolResult(False, f"Unexpected tool failure: {error}", {"error_type": "internal_tool_error"})

    @staticmethod
    def _validate(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ToolError("Tool arguments must be a JSON object")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in arguments:
                raise ToolError(f"Missing required argument: {name}")
        extra = set(arguments) - set(properties)
        if extra and schema.get("additionalProperties") is False:
            raise ToolError("Unexpected argument(s): " + ", ".join(sorted(extra)))
        python_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        for name, value in arguments.items():
            expected_name = properties.get(name, {}).get("type")
            expected = python_types.get(expected_name)
            if expected and (not isinstance(value, expected) or expected_name == "integer" and isinstance(value, bool)):
                raise ToolError(f"Argument {name!r} must be of type {expected_name}")

