from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, computed_field

from database.models.enums import NotificationType


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


class CommentAuthorSchema(BaseModel):
    email: str
    model_config = ConfigDict(from_attributes=True)


class CommentReadSchema(BaseModel):
    id: int
    user_id: int
    text: str
    parent_id: Optional[int] = None
    created_at: datetime

    user: CommentAuthorSchema = Field(exclude=True)

    @computed_field
    @property
    def likes_count(self) -> int:
        return len(self.likes) if hasattr(self, "likes") else 0

    likes: List[dict] = Field(exclude=True, default=[])

    @computed_field
    @property
    def email(self) -> str:
        return self.user.email

    model_config = ConfigDict(from_attributes=True)
