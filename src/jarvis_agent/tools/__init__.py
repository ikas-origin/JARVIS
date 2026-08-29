"""Built-in local tools."""

from .filesystem import FILESYSTEM_TOOLS
from .shell import make_run_command_tool


def built_in_tools(*, command_timeout: float, output_limit: int):
    return [*FILESYSTEM_TOOLS, make_run_command_tool(command_timeout, output_limit)]

