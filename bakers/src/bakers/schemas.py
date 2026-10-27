"""Esquemas de respuesta. De cada uno sale el JSON Schema que llama-server convierte en gramática."""
from typing import Literal

from pydantic import BaseModel, Field, create_model


class Resumen(BaseModel):
    resumen: str = Field(description="What the files say about the task, in a few sentences")
    puntos: list[str] = Field(description="Key facts, one per item, each self-contained")
    alertas: list[str] = Field(
        description="Errors, risks or anything the orchestrator should check in person; empty if none"
    )


def clasificacion(categorias: list[str]) -> type[BaseModel]:
    """Esquema con las categorías como enum: la gramática no deja inventar otras."""
    item = create_model("Item", n=(int, Field(ge=1)), categoria=(Literal[tuple(categorias)], ...))
    return create_model("Clasificacion", items=(list[item], ...))
