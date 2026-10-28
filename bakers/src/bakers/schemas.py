"""Esquemas de respuesta. De cada uno sale el JSON Schema que llama-server convierte en gramática."""
from typing import Literal

from pydantic import BaseModel, Field, create_model


class Resumen(BaseModel):
    resumen: str = Field(description="What the files say about the task, in a few sentences")
    puntos: list[str] = Field(description="Key facts, one per item, each self-contained")
    alertas: list[str] = Field(
        description="Errors, risks or anything the orchestrator should check in person; empty if none"
    )


class Dato(BaseModel):
    campo: str = Field(description="Attribute name, e.g. height, flowering season, native range")
    valor: str
    fuente: str = Field(description="File name the value comes from")


class Ubicacion(BaseModel):
    lugar: str
    fuente: str


class Interaccion(BaseModel):
    especie: str
    tipo: str = Field(description="One or two words for the role of the other species: polinizador, hospedero, "
                                  "depredador, simbionte, visitante, etc.")
    fuente: str


class Contradiccion(BaseModel):
    campo: str
    valor_a: str
    fuente_a: str
    valor_b: str
    fuente_b: str


class Ficha(BaseModel):
    """Ficha de especie. Sustituye a Resumen ahí: con Resumen los datos llegaban como texto suelto
    y `alertas` se llenaba de contradicciones inventadas (Campus Lab, 2026-10-27)."""
    nombre_comun: str
    nombre_cientifico: str
    familia: str
    descripcion: str = Field(description="One paragraph for a general audience, only from the sources")
    datos: list[Dato]
    ubicaciones_iteso: list[Ubicacion] = Field(description="Places on the ITESO campus; empty if none")
    interacciones: list[Interaccion] = Field(description="Empty if none")
    contradicciones: list[Contradiccion] = Field(
        description="Only when two sources give different values for the same field; empty otherwise"
    )
    faltantes: list[str] = Field(description="Names of usual fact sheet fields no source covers (e.g. fruto, "
                                             "floración, polinizadores, usos); names only, no comments")


class Recurso(BaseModel):
    nombre: str = Field(description="Exact name someone could search for or use: tool, library, site, font, book, "
                                    "account, hex color, prompt or command")
    que_es: str = Field(description="What it is or what it is used for in the video, one short sentence")
    donde: Literal["audio", "pantalla", "caption"] = Field(description="Where it appears")


class Cita(BaseModel):
    t: str = Field(description="Timestamp mm:ss taken from the transcript")
    texto: str = Field(description="Verbatim quote, in its original language")


class Reel(BaseModel):
    tema: str = Field(description="Topic in a few words, used as the note title")
    idea_central: str = Field(description="The technique or idea and why it works, 1 to 3 sentences")
    recursos: list[Recurso] = Field(
        description="Only things someone could look up or use (software, sites, books, accounts, fonts, colors, "
                    "commands); not brands seen in passing, places, people or topics. Empty if none"
    )
    citas: list[Cita] = Field(description="Up to 5 quotes worth keeping; empty if there is no speech")
    texto_en_pantalla: list[str] = Field(
        description="Only on-screen text that is not already in the transcript: titles, code, names, numbers, "
                    "labels. Skip burned-in subtitles that repeat the speech. Empty if none"
    )
    visual: str = Field(description="What is seen: scene, style, palette, editing, in 1 to 3 sentences")
    afirmaciones: list[str] = Field(
        description="Only bold claims that could be false or exaggerated (numbers, speed, 'free', 'nobody tells "
                    "you', star counts); not descriptions of what the video shows. Empty if none"
    )


def clasificacion(categorias: list[str]) -> type[BaseModel]:
    """Esquema con las categorías como enum: la gramática no deja inventar otras."""
    item = create_model("Item", n=(int, Field(ge=1)), categoria=(Literal[tuple(categorias)], ...))
    return create_model("Clasificacion", items=(list[item], ...))


class Respuesta(BaseModel):
    """Turno del Baker `chat`. `escalar` lo lee el código, no el cliente: marca la conversación para el dueño."""
    respuesta: str = Field(description="What the guest reads")
    escalar: bool = Field(description="True when the sheet does not answer the question")
