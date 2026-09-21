"""Request models and locatable validation for the reconstruction API."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class KnownCell(BaseModel):
    row: int = Field(..., description="zero-based row index")
    col: int = Field(..., description="zero-based column index")
    value: Literal[0, 1] = Field(..., description="fixed cell value")


class ReconstructRequest(BaseModel):
    rows: int = Field(..., ge=4, le=12)
    cols: int = Field(..., ge=4, le=12)
    row: List[int]
    col: List[int]
    diff: List[int] = Field(..., description="r-c diagonal sums, increasing r-c")
    sum: List[int] = Field(..., description="r+c diagonal sums, increasing r+c")
    known: List[KnownCell] = Field(default_factory=list)


class FieldError(BaseModel):
    field: str
    message: str
    code: str


class RejectResponse(BaseModel):
    message: str
    errors: List[FieldError]


class LineWitness(BaseModel):
    row: List[int]
    col: List[int]
    diff: List[int]
    sum: List[int]


class Witness(BaseModel):
    grid: str
    lines: LineWitness


class Difference(BaseModel):
    index: int
    row: int
    col: int
    values: List[int]  # values in the first and second witness, 0/1


class ReconstructResponse(BaseModel):
    status: Literal["none", "unique", "multiple"]
    rows: int
    cols: int
    targets: LineWitness
    witnesses: List[Witness]
    differences: List[Difference] = Field(default_factory=list)


class Health(BaseModel):
    status: str
    service: str
