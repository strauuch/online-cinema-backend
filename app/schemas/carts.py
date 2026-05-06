from fastapi.openapi.models import Example
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from typing import List
from datetime import datetime


class CartMovieSchema(BaseModel):
    id: int
    name: str
    price: Decimal
    year: int
    genres: List[str]

    model_config = ConfigDict(from_attributes=True)


class CartItemResponseSchema(BaseModel):
    id: int
    added_at: datetime
    movie: CartMovieSchema

    model_config = ConfigDict(from_attributes=True)


class CartResponseSchema(BaseModel):
    id: int
    user_id: int
    items: List[CartItemResponseSchema]
    total_price: Decimal = Field(
        default=Decimal(
            "0.00",
        ),
        description="The sum of prices of all movies currently in the cart",
        examples=["499.00"],
    )

    model_config = ConfigDict(from_attributes=True)


class CartItemAddedSchema(BaseModel):
    message: str
    movie_id: int
    cart_id: int

    model_config = ConfigDict(from_attributes=True)


class CartItemRemovedSchema(BaseModel):
    message: str
    movie_id: int

    model_config = ConfigDict(from_attributes=True)


class CartClearSchema(BaseModel):
    message: str

    model_config = ConfigDict(from_attributes=True)
