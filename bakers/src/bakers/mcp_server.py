"""Servidor MCP `bakers` (stdio) para Claude Code."""
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import core, reel as _reel

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


@mcp.tool(description="""Turn reels or short videos (Instagram, TikTok, Shorts; links or local files, up to 10 min),
or photo posts and carousels (Instagram /p/, TikTok photos), into inspiration notes on Pixilate: transcript, on-screen text, resources, quotes, visuals, claims to verify.
Only pieces the user shared, one link each: never crawl accounts, feeds or saved lists.
destino: folder where the notes go, per the project table in the inspiracion skill (e.g. docs/inspiracion of the
current repo); heavy material (video, frames, transcript) always stays in ~/.bakers/reels.
Returns one dict per source with the note fields and the path of the draft note (or `error`).
Resources come back unverified, and the Aplicación section is left for you to write.""")
def reel(fuentes: list[str], destino: str | None = None) -> list[dict]:
    try:
        return _reel.reel(fuentes, destino)
    except core.BakerError as e:
        raise ToolError(str(e)) from e


@mcp.tool(description="Which model serves each Baker and which models llama-swap has loaded right now.")
def bakers_status() -> dict:
    try:
        return core.estado()
    except core.BakerError as e:
        raise ToolError(str(e)) from e


def main() -> None:
    mcp.run()
