from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, computed_field, field_validator
from database.validators import movies_validators

from database.models.enums import NotificationType

# Schemas for user endpoints


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


class RatingCreateSchema(BaseModel):
    score: int = Field(..., ge=1, le=10, description="Rating from 1 to 10")


class RatingReadSchema(RatingCreateSchema):
    movie_id: int
    user_id: int

    model_config = ConfigDict(from_attributes=True)


class VoteCreateSchema(BaseModel):
    is_like: bool  # True = Like, False = Dislike


class NotificationReadSchema(BaseModel):
    id: int
    notification_type: NotificationType
    content: str
    link_to_id: Optional[str]
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CommentCreateSchema(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    parent_id: Optional[int] = None


class CommentUpdateSchema(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


class CommentAuthorSchema(BaseModel):
    email: str
    model_config = ConfigDict(from_attributes=True)


class CommentLikeReadSchema(BaseModel):
    user_id: int

    model_config = ConfigDict(from_attributes=True)


class CommentReadSchema(BaseModel):
    id: int
    user_id: int
    text: str
    parent_id: Optional[int] = None
    created_at: datetime

    likes: List[CommentLikeReadSchema] = Field(exclude=True, default=[])

    user: CommentAuthorSchema = Field(exclude=True)

    @computed_field
    @property
    def likes_count(self) -> int:
        return len(self.likes)

    @computed_field
    @property
    def email(self) -> str:
        return self.user.email

    model_config = ConfigDict(from_attributes=True)


# Schemas for moderator and admin endpoints


class MovieCreateSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=250)
    year: int
    time: int
    imdb: float
    description: str = Field(..., min_length=10)
    price: Decimal
    certification_id: int
    genre_ids: List[int] = Field(..., min_length=1)
    star_ids: List[int] = Field(..., min_length=1)
    director_ids: List[int] = Field(..., min_length=1)

    meta_score: Optional[float] = None
    gross: Optional[float] = None
    votes: int = Field(0, ge=0)

    @field_validator("year")
    @classmethod
    def check_year(cls, v):
        return movies_validators.validate_movie_year(v)

    @field_validator("imdb")
    @classmethod
    def check_imdb(cls, v):
        return movies_validators.validate_imdb_rating(v)

    @field_validator("price")
    @classmethod
    def check_price(cls, v):
        return movies_validators.validate_movie_price(v)

    @field_validator("time")
    @classmethod
    def check_time(cls, v):
        return movies_validators.validate_movie_duration(v)


class MovieUpdateSchema(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=250)
    year: Optional[int] = None
    time: Optional[int] = None
    imdb: Optional[float] = None
    description: Optional[str] = Field(None, min_length=10)
    price: Optional[Decimal] = None
    certification_id: Optional[int] = None
    genre_ids: Optional[List[int]] = None
    star_ids: Optional[List[int]] = None
    director_ids: Optional[List[int]] = None
    meta_score: Optional[float] = None
    gross: Optional[float] = None
    votes: Optional[int] = Field(None, ge=0)

    @field_validator("year")
    @classmethod
    def check_year(cls, v):
        return movies_validators.validate_movie_year(v) if v is not None else v

    @field_validator("imdb")
    @classmethod
    def check_imdb(cls, v):
        return movies_validators.validate_imdb_rating(v) if v is not None else v

    @field_validator("price")
    @classmethod
    def check_price(cls, v):
        return movies_validators.validate_movie_price(v) if v is not None else v

    @field_validator("time")
    @classmethod
    def check_time(cls, v):
        return movies_validators.validate_movie_duration(v) if v is not None else v
