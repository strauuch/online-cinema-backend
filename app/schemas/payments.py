from pydantic import BaseModel, ConfigDict
from decimal import Decimal
from datetime import datetime
from typing import Optional
from database.models.enums import PaymentStatusEnum
from schemas.orders import OrderUserSchema


class PaymentResponseSchema(BaseModel):
    id: int
    order_id: int
    status: PaymentStatusEnum
    amount: Decimal
    external_payment_id: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPaymentResponseSchema(PaymentResponseSchema):
    user: Optional["OrderUserSchema"]
