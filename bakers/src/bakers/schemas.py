"""Esquemas de respuesta. De cada uno sale el JSON Schema que llama-server convierte en gramática."""
from typing import Literal

from pydantic import BaseModel, Field, create_model


class Resumen(BaseModel):
    resumen: str = Field(description="What the files say about the task, in a few sentences")
    puntos: list[str] = Field(description="Key facts, one per item, each self-contained")
    alertas: list[str] = Field(
        description="Errors, risks or anything the orchestrator should check in person; empty if none"
    )


class Recurso(BaseModel):
    nombre: str = Field(description="Tool, library, site, font, book, account, color (hex), prompt or command")
    que_es: str = Field(description="What it is or what it is used for in the video, one short sentence")
    donde: Literal["audio", "pantalla", "caption"] = Field(description="Where it appears")


class Cita(BaseModel):
    t: str = Field(description="Timestamp mm:ss taken from the transcript")
    texto: str = Field(description="Verbatim quote, in its original language")


class Reel(BaseModel):
    tema: str = Field(description="Topic in a few words, used as the note title")
    idea_central: str = Field(description="The technique or idea and why it works, 1 to 3 sentences")
    recursos: list[Recurso] = Field(description="Concrete resources mentioned or shown; empty if none")
    citas: list[Cita] = Field(description="Up to 5 quotes worth keeping; empty if there is no speech")
    texto_en_pantalla: list[str] = Field(description="Relevant on-screen text: code, titles, captions, labels")
    visual: str = Field(description="What is seen: scene, style, palette, editing, in 1 to 3 sentences")
    afirmaciones: list[str] = Field(
        description="Only bold claims that could be false or exaggerated (numbers, speed, 'free', 'nobody tells "
                    "you', star counts); not descriptions of what the video shows. Empty if none"
    )


def clasificacion(categorias: list[str]) -> type[BaseModel]:
    """Esquema con las categorías como enum: la gramática no deja inventar otras."""
    item = create_model("Item", n=(int, Field(ge=1)), categoria=(Literal[tuple(categorias)], ...))
    return create_model("Clasificacion", items=(list[item], ...))
