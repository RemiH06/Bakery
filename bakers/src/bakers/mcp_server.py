"""Servidor MCP `bakers` (stdio) para Claude Code."""
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import core

mcp = MCPServer("bakers")

_lista = "\n".join(f"- {n}: {cfg['descripcion']}" for n, cfg in core.BAKERS.items())


@mcp.tool(description=f"""Delegate reading to a local model on Pixilate and get back short validated JSON.
Pass file paths, never file contents: the Baker reads them so you don't. One step, no tools.
Use it when the files are much larger than the answer you need (logs, long docs, batches to label).
categorias is only for clasificador. Bakers:
{_lista}""")
def bake(baker: str, tarea: str, rutas: list[str], categorias: list[str] | None = None) -> dict:
    try:
        return core.bake(baker, tarea, rutas, categorias)
    except core.BakerError as e:
        raise ToolError(str(e)) from e  # MCP oculta el texto de cualquier otra excepción


@mcp.tool(description="Which model serves each Baker and which models llama-swap has loaded right now.")
def bakers_status() -> dict:
    try:
        return core.estado()
    except core.BakerError as e:
        raise ToolError(str(e)) from e


def main() -> None:
    mcp.run()
