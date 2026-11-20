"""Esquemas de respuesta. De cada uno sale el JSON Schema que llama-server convierte en gramática."""
from typing import Annotated, Literal

from pydantic import BaseModel, Field, create_model


class Resumen(BaseModel):
    resumen: str = Field(description="What the files say about the task, in a few sentences")
    puntos: list[str] = Field(description="Key facts, one per item, each self-contained")
    alertas: list[str] = Field(
        description="Errors, risks or anything the orchestrator should check in person; empty if none"
    )


class RespuestaCitada(BaseModel):
    # citas va primero: la gramática sigue este orden y el modelo copia la evidencia antes de redactar
    citas: list[str] = Field(description="Verbatim passages copied from the fragments; empty if no_encontrado")
    no_encontrado: bool = Field(description="True when the fragments do not contain the answer")
    respuesta: str = Field(description="Short answer based only on the citas; empty if no_encontrado")


# Tope en la gramática, no en el prompt: Bonsai ignora los límites escritos, pero llama-server no deja
# pasar de maxItems ni de maxLength. Así un artículo con muchos casos (art. 236 Bis del Código Penal de
# Jalisco, 2026-11-17) no lleva al bucle hasta el tope de tokens: la salida cabe en ~900 de los 1,024.
# Una cita cortada en el carácter 350 sigue siendo texto literal del fragmento y Tabularium la verifica;
# una respuesta cortada, Tabularium la recorta a su última oración completa.
class RespuestaLegal(RespuestaCitada):
    citas: list[Annotated[str, Field(max_length=350)]] = Field(
        max_length=4, description="Verbatim passages copied from the fragments; empty if no_encontrado")
    respuesta: str = Field(max_length=1000, description="Short answer based only on the citas; empty if no_encontrado")


class Reformulacion(BaseModel):
    """Una pregunta de ley contada como la contaría cualquiera, vuelta consultas con el vocabulario de la ley,
    para que Tabularium (61.Tabularium, 10.5 y 10.8) busque con ellas. `pregunta` va primero: con turnos
    anteriores, el modelo resuelve a qué se refiere un seguimiento antes de escribir las consultas."""
    pregunta: str = Field(max_length=500, description="The current question as a standalone question in Spanish")
    consultas: list[Annotated[str, Field(max_length=120)]] = Field(
        min_length=1, max_length=3, description="Short search queries in the formal vocabulary of Mexican statutes")


class Glosa(BaseModel):
    """Efecto de una reforma en una unidad de una norma, para las Novellae de Tabularium (61.Tabularium).
    `resumen` va primero: el modelo describe el cambio antes de decidir qué efecto tiene."""
    resumen: str = Field(description="What the change does, one or two sentences, in Spanish (Mexico)")
    efecto: Literal["amplia", "restringe", "aclara"] = Field(
        description="For the taxpayer: amplia grants or widens a right, option or benefit or lightens a burden; "
                    "restringe adds or tightens an obligation, requirement, sanction or limit, or removes a benefit; "
                    "aclara changes wording, references or numbering without changing rights or obligations"
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
    pasos: list[str] = Field(
        description="Ordered steps of a tutorial, recipe or workout shown in the video, one per item, with the "
                    "product, tool, sets and reps it names. Empty if it is not a step by step piece"
    )


def _parte(nombre: str, campos: tuple[str, ...]) -> type[BaseModel]:
    return create_model(nombre, **{k: (f.annotation, f) for k, f in Reel.model_fields.items() if k in campos})


# Si la visión se cicla con el esquema completo, cada mitad va en su propia llamada con su propio tope de salida
REEL_PARTES = (_parte("ReelHabla", ("tema", "idea_central", "recursos", "citas", "afirmaciones")),
               _parte("ReelVista", ("texto_en_pantalla", "visual", "pasos")))


def clasificacion(categorias: list[str]) -> type[BaseModel]:
    """Esquema con las categorías como enum: la gramática no deja inventar otras."""
    item = create_model("Item", n=(int, Field(ge=1)), categoria=(Literal[tuple(categorias)], ...))
    return create_model("Clasificacion", items=(list[item], ...))


class Respuesta(BaseModel):
    """Turno del Baker `chat`. `escalar` lo lee el código, no el cliente: marca la conversación para el dueño."""
    respuesta: str = Field(description="What the guest reads")
    escalar: bool = Field(description="True when the sheet does not answer the question")
