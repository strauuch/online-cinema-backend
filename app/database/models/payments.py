from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from decimal import Decimal
from sqlalchemy import ForeignKey, DateTime, Numeric, func, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from database.models.enums import PaymentStatusEnum

if TYPE_CHECKING:
    from database.models.accounts import UserModel
    from database.models.orders import OrderModel, OrderItemModel


class PaymentModel(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[PaymentStatusEnum] = mapped_column(
        Enum(PaymentStatusEnum), default=PaymentStatusEnum.PENDING, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    external_payment_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["UserModel"] = relationship("UserModel")
    order: Mapped["OrderModel"] = relationship("OrderModel", back_populates="payments")
    items: Mapped[List["PaymentItemModel"]] = relationship(
        "PaymentItemModel", back_populates="payment", cascade="all, delete-orphan"
    )


class PaymentItemModel(Base):
    __tablename__ = "payment_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False
    )
    price_at_payment: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    payment: Mapped["PaymentModel"] = relationship(
        "PaymentModel", back_populates="items"
    )
    order_item: Mapped["OrderItemModel"] = relationship("OrderItemModel")
