from pydantic import BaseModel, ConfigDict
from decimal import Decimal
from datetime import datetime
from typing import Optional
from database.models.enums import PaymentStatusEnum
from schemas.orders import OrderUserSchema


class PaymentItemResponseSchema(BaseModel):
    order_item_id: int
    price_at_payment: Decimal
    model_config = ConfigDict(from_attributes=True)


class PaymentResponseSchema(BaseModel):
    id: int
    order_id: int
    status: PaymentStatusEnum
    amount: Decimal
    external_payment_id: Optional[str]
    created_at: datetime
    items: list[PaymentItemResponseSchema]

    model_config = ConfigDict(from_attributes=True)


class AdminPaymentResponseSchema(PaymentResponseSchema):
    user: Optional["OrderUserSchema"]
