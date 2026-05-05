from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from typing import List
from datetime import datetime


class CartMovieSchema(BaseModel):
    """
    Schema representing movie details within the shopping cart context.
    """

    id: int
    name: str
    price: Decimal
    year: int
    genres: List[str]

    model_config = ConfigDict(from_attributes=True)


class CartItemResponseSchema(BaseModel):
    """
    Schema representing a single entry in the shopping cart.
    """

    id: int
    added_at: datetime
    movie: CartMovieSchema

    model_config = ConfigDict(from_attributes=True)


class CartResponseSchema(BaseModel):
    """
    Schema for the complete user shopping cart, including the calculated total price.
    """

    id: int
    user_id: int
    items: List[CartItemResponseSchema]
    total_price: Decimal = Field(
        default=Decimal("0.00"),
        description="The sum of prices of all movies currently in the cart",
    )

    model_config = ConfigDict(from_attributes=True)
