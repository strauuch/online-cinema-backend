from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from datetime import datetime
from typing import List

from app.database.models.enums import OrderStatusEnum


class OrderItemOutSchema(BaseModel):
    movie_id: int
    price_at_order: Decimal = Field(default=Decimal("0.00"), examples=["49.00"])


class OrderResponseSchema(BaseModel):
    id: int
    status: OrderStatusEnum
    total_amount: Decimal = Field(default=Decimal("0.00"), examples=["49.00"])
    created_at: datetime
    items: List[OrderItemOutSchema]

    model_config = ConfigDict(from_attributes=True)


class OrderMovieSchema(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class OrderItemOutListSchema(BaseModel):
    movie_id: int
    price_at_order: Decimal = Field(default=Decimal("0.00"), examples=["49.00"])
    movie: OrderMovieSchema

    model_config = ConfigDict(from_attributes=True)


class OrderListResponseSchema(BaseModel):
    id: int
    status: OrderStatusEnum
    total_amount: Decimal = Field(default=Decimal("0.00"), examples=["499.00"])
    created_at: datetime
    items: List[OrderItemOutListSchema]

    model_config = ConfigDict(from_attributes=True)


class OrderUserSchema(BaseModel):
    id: int
    email: str

    model_config = ConfigDict(from_attributes=True)


class AdminOrderResponseSchema(OrderListResponseSchema):
    user: OrderUserSchema
