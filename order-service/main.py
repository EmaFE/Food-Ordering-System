import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from sqlmodel import Session, select
from jose import jwt, JWTError
import os

from database import Order, OrderItem, create_db, engine
from events import connect_rabbitmq, consume_events, publish_event, payment_breaker


logging.basicConfig(level = logging.INFO)
logger = logging.getLogger(__name__)

# JWT config
JWT_SECRET = os.getenv("JWT_SECRET", "supersecretkey")
JWT_ALGORITHM = "HS256"


# helper function
def get_customer_id(authorization: str) -> int:
    """
    Extract customer_id from JWT token in Authorization header.
    """
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, JWT_SECRET, algorithms = [JWT_ALGORITHM])
        return int(payload["sub"])
    
    except JWTError:
        raise HTTPException(status_code = 401, detail = "Invalid or expired token")


# Hateoas
def order_links(order_id: int, status: str):
    links = {
        "self": {"href": f"/api/orders/{order_id}", "method": "GET"},
        "my_orders": {"href": "/api/orders/my-orders", "method": "GET"},
        "menu": {"href": "/api/restaurant/menu", "method": "GET"},
    }
    
    if status == "pending":
        links["cancel"] = {"href": f"/api/orders/cancel/{order_id}", "method": "POST"}
    
    return links


# lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    await connect_rabbitmq()
    await consume_events()
    yield


# application
app = FastAPI(lifespan = lifespan)


# schemas - define what the paylod for an order request should look like
class OrderItemRequest(BaseModel):
    item_id: int
    quantity: int


class CreateOrderRequest(BaseModel):
    items: List[OrderItemRequest]


# Routes

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "order-service",
        "circuit_breaker": payment_breaker.status(),
    }


@app.post("/")
async def create_order(request: CreateOrderRequest, authorization: str = Header(...)):
    customer_id = get_customer_id(authorization)

    with Session(engine) as session:
        order = Order(customer_id = customer_id)
        session.add(order)
        session.commit()
        session.refresh(order)

        order_id = order.id

        for entry in request.items:
            session.add(OrderItem(
                order_id = order_id,
                item_id = entry.item_id,
                quantity = entry.quantity,
            ))

        session.commit()

    await publish_event("order_created", {
        "order_id": order_id,
        "items": [{"item_id": e.item_id, "quantity": e.quantity} for e in request.items],
    })

    return {
        "order_id": order_id,
        "status": "pending",
        "message": "Order received - processing started",
        "_links": order_links(order_id, "pending"),
    }


# get all past orders 
@app.get("/my-orders")
def get_my_orders(authorization: str = Header(...)):
    customer_id = get_customer_id(authorization)

    with Session(engine) as session:
        orders = session.exec(select(Order).where(Order.customer_id == customer_id)).all()

    return {
        "orders": [
            {**o.model_dump(), "_links": order_links(o.id, o.status)}
            for o in orders
        ],
        
        "_links": {
            "self": {"href": "/api/orders/my-orders", "method": "GET"},
            "create": {"href": "/api/orders/", "method": "POST"},
        }
    }


@app.get("/circuit-breaker/status")
def circuit_breaker_status():
    """
    Check circuit breaker state (for demo).
    """
    payment_breaker._should_attempt() # force check, triggers OPEN --> HALF_OPEN transition if timeout elapses
    return payment_breaker.status()


@app.post("/cancel/{order_id}")
async def cancel_order(order_id: int, authorization: str = Header(...)):
    customer_id = get_customer_id(authorization)

    with Session(engine) as session:
        order = session.exec(
            select(Order).where(Order.id == order_id, Order.customer_id == customer_id)
        ).first()

        if not order:
            raise HTTPException(status_code = 404, detail = "Order not found")
        
        if order.status != "pending":
            raise HTTPException(status_code = 400, detail = f"Cannot cancel order with status '{order.status}'")

        items = session.exec(select(OrderItem).where(OrderItem.order_id == order_id)).all()
        item_payloads = [{"item_id": i.item_id, "quantity": i.quantity} for i in items]
        order.status = "cancelled"
        order.cancellation_reason = "customer_cancelled"
        session.add(order)
        session.commit()

    await publish_event("release_items", {
        "order_id": order_id,
        "items": item_payloads,
        "reason": "customer_cancelled"
    })

    return {
        "order_id": order_id,
        "status": "cancelled",
        "_links": order_links(order_id, "cancelled")
    }


# get a single order information
@app.get("/{order_id}")
def get_order(order_id: int, authorization: str = Header(...)):
    customer_id = get_customer_id(authorization)

    with Session(engine) as session:
        order = session.exec(
            select(Order).where(Order.id == order_id, Order.customer_id == customer_id)
        ).first()
        
        if not order:
            raise HTTPException(status_code = 404, detail = "Order not found")
        
        items = session.exec(select(OrderItem).where(OrderItem.order_id == order_id)).all()

    return {
        **order.model_dump(),
        "items": [i.model_dump() for i in items],
        "_links": order_links(order_id, order.status),
    }
