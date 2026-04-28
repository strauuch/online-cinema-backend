from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class GenreReadSchema(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class GenreWithCountSchema(GenreReadSchema):
    movie_count: int


class StarReadSchema(BaseModel):
    id: int
    name: str = Field(..., max_length=100)

    model_config = ConfigDict(from_attributes=True)


class DirectorReadSchema(StarReadSchema):
    pass


class CertificationReadSchema(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class MovieShortResponseSchema(BaseModel):
    id: int
    uuid: UUID
    name: str
    year: int
    imdb: float
    price: Decimal
    genres: List[GenreReadSchema]

    model_config = ConfigDict(from_attributes=True)


class MovieDetailResponseSchema(MovieShortResponseSchema):

    time: int
    votes: int
    meta_score: Optional[float]
    gross: Optional[float]
    description: str
    certification: CertificationReadSchema
    stars: List[StarReadSchema]
    directors: List[DirectorReadSchema]


class MovieUpdateSchema(BaseModel):

    name: Optional[str] = None
    year: Optional[int] = None
    time: Optional[int] = None
    imdb: Optional[float] = None
    price: Optional[Decimal] = None
    description: Optional[str] = None
    certification_id: Optional[int] = None
    genre_ids: Optional[List[int]] = None
    star_ids: Optional[List[int]] = None
    director_ids: Optional[List[int]] = None
