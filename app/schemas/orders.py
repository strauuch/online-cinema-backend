from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import List


class OrderItemOutSchema(BaseModel):
    movie_id: int
    price_at_order: Decimal


class OrderResponseSchema(BaseModel):
    id: int
    status: str
    total_amount: Decimal
    created_at: datetime
    items: List[OrderItemOutSchema]

    class Config:
        from_attributes = True
