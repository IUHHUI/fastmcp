"""FastMCP - An ergonomic MCP interface."""

from importlib.metadata import version

from fastmcp.utilities.mcp_session import patch_mcp_session_invalid_request_handling
from fastmcp.server.server import FastMCP
from fastmcp.server.context import Context
import fastmcp.server

from fastmcp.client import Client
from fastmcp.utilities.types import Image
from . import client, settings

patch_mcp_session_invalid_request_handling()

__version__ = version("fastmcp")
__all__ = [
    "FastMCP",
    "Context",
    "client",
    "Client",
    "settings",
    "Image",
]
