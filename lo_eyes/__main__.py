"""Run lo-eyes MCP server: python -m lo_eyes"""

from lo_eyes.server import mcp

mcp.run(transport="stdio")
