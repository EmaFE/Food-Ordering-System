from typing import Optional
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel, create_engine
import os


# Databse config
# DATABASE_URL = "sqlite:///./orders.db"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://orders:orders@postgres:5432/orders")
engine = create_engine(DATABASE_URL)


# Models
class Order(SQLModel, table = True):
    id:                  Optional[int] = Field(default = None, primary_key = True)
    customer_id:         int
    status:              str = "pending"
    total:               float = 0.0
    payment_id:          Optional[str] = None
    cancellation_reason: Optional[str] = None
    created_at:          str = Field(default_factory = lambda: datetime.now(timezone.utc).isoformat())


class OrderItem(SQLModel, table = True):
    id:       Optional[int] = Field(default = None, primary_key = True)
    order_id: int = Field(foreign_key = "order.id")
    item_id:  int
    name:     str = ""
    price:    float = 0.0
    quantity: int


# Create order database
def create_db():
    SQLModel.metadata.create_all(engine)