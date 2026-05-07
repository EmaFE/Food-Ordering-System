from fastapi import FastAPI, HTTPException
from typing import Optional
from contextlib import asynccontextmanager
from sqlmodel import Field, Session, SQLModel, create_engine, select
import json
import logging
import asyncio
import aio_pika

# logging
logging.basicConfig(level = logging.INFO)
logger = logging.getLogger(__name__)

# Database
DATABASE_URL = "sqlite:///./restaurant.db"
RABBITMQ_URL = "amqp://guest:guest@rabbitmq:5672/"

engine = create_engine(DATABASE_URL, connect_args = {"check_same_thread": False})


# Model
class MenuItem(SQLModel, table = True):
    id: Optional[int] = Field(default = None, primary_key = True)
    name: str
    description: str
    price: float
    quantity: int
    available: bool = True


def initialize_menu(session: Session):
    # Only initialize menu if table is empty
    existing = session.exec(select(MenuItem)).first()
    if existing:
        return
    
    items = [
        MenuItem(name = "Margherita Pizza", description = "Classic tomato and mozzarella", price = 12.99, quantity = 20),
        MenuItem(name = "Pepperoni Pizza", description = "Loaded with pepperoni", price = 14.99, quantity = 15),
        MenuItem(name = "Caesar Salad", description = "Crispy romaine and parmesan", price = 8.99,  quantity = 25),
        MenuItem(name = "Garlic Bread", description = "Toasted with herb butter", price = 4.99,  quantity = 30),
        MenuItem(name = "Tiramisu", description = "Classic Italian dessert", price = 6.99,  quantity = 10),
        MenuItem(name = "Soft Drink", description = "Coke, Fanta or Sprite", price = 2.99,  quantity = 50),
    ]
    
    for item in items:
        session.add(item)
    
    session.commit()


def create_db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        initialize_menu(session)


# RabbitMQ message Queue
rabbitmq_connection = None
rabbitmq_channel = None


async def connect_rabbitmq():
    global rabbitmq_connection, rabbitmq_channel
    
    for attempt in range(10):
        try:
            rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
            rabbitmq_channel = await rabbitmq_connection.channel()
            logger.info("Connected to RabbitMQ")

            # Declare all queues this service uses
            await rabbitmq_channel.declare_queue("order_created", durable = True)
            await rabbitmq_channel.declare_queue("payment_success", durable = True)
            await rabbitmq_channel.declare_queue("items_reserved", durable = True)
            await rabbitmq_channel.declare_queue("items_unavailable", durable = True)
            await rabbitmq_channel.declare_queue("release_items", durable = True)
            return
        
        except Exception as e:
            logger.warning(f"RabbitMQ not ready (attempt {attempt + 1}): {e}")
            await asyncio.sleep(3)
    
    raise RuntimeError("Could not connect to RabbitMQ after 10 attempts")


async def publish_event(queue_name: str, payload: dict):
    await rabbitmq_channel.default_exchange.publish(
        aio_pika.Message(
            body = json.dumps(payload).encode(),
            delivery_mode = aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key = queue_name,
    )
    
    logger.info(f"Published to {queue_name}: {payload}")


async def consume_events():
    order_created_queue = await rabbitmq_channel.get_queue("order_created")
    payment_success_queue = await rabbitmq_channel.get_queue("payment_success")
    release_items_queue = await rabbitmq_channel.get_queue("release_items")

    await order_created_queue.consume(handle_order_created)
    await payment_success_queue.consume(handle_payment_success)
    await release_items_queue.consume(handle_release_stock)

    logger.info("Restaurant Service listening for events")


async def handle_payment_success(message: aio_pika.IncomingMessage):
    async with message.process():
        data = json.loads(message.body)
        order_id = data.get("order_id")

        logger.info(f"Payment confirmed for order {order_id} - preparing order")


async def handle_order_created(message: aio_pika.IncomingMessage):
    async with message.process():
        data = json.loads(message.body)
        order_id = data.get("order_id")
        items = data.get("items", [])

        logger.info(f"Received order_created for order {order_id}")

        with Session(engine) as session:
            total = 0.0
            reserved_items = []

            for entry in items:
                item = session.get(MenuItem, entry["item_id"])

                if not item:
                    await publish_event("items_unavailable", {
                        "order_id": order_id,
                        "reason": "invalid_item"
                    })
                    logger.warning(f"Invalid item {entry['item_id']} in order {order_id}")
                    return

                if item.quantity < entry["quantity"]:
                    await publish_event("items_unavailable", {
                        "order_id": order_id,
                        "reason": "insufficient_stock"
                    })
                    logger.warning(f"Insufficient stock for order {order_id}")
                    return

                total += item.price * entry["quantity"]
                reserved_items.append({
                    "item_id": item.id,
                    "name": item.name,
                    "price": item.price,
                    "quantity": entry["quantity"],
                })
                item.quantity -= entry["quantity"]

            session.commit()
            await publish_event("items_reserved", {
                "order_id": order_id,
                "total": round(total, 2),
                "items": reserved_items,
            })
            logger.info(f"Items reserved for order {order_id}")


async def handle_release_stock(message: aio_pika.IncomingMessage):
    async with message.process():
        data = json.loads(message.body)
        
        order_id = data.get("order_id")
        items = data.get("items", [])
        reason = data.get("reason")

        logger.info(f"Releasing stock for order {order_id} - reason: {reason}")

        # Add quantities back
        with Session(engine) as session:
            for entry in items:
                item = session.get(MenuItem, entry["item_id"])
                
                if item:
                    item.quantity += entry["quantity"]
            
            session.commit()

        logger.info(f"Items released for order {order_id}")


# Heteaos helpers

# For each item
def item_links(item_id: int):
    return {
        "self": {"href": f"/api/restaurant/menu/{item_id}", "method": "GET"},
        "place_order": {"href": "/api/orders/", "method": "POST"},
    }


# For menu
def menu_links():
    return {
        "self": {"href": "/api/restaurant/menu", "method": "GET"},
    }


# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    await connect_rabbitmq()
    await consume_events()
    yield
    
    if rabbitmq_connection:
        await rabbitmq_connection.close()


# Application
app = FastAPI(title = "Restaurant", lifespan = lifespan)


# Routes

@app.get("/menu")
def get_menu():
    with Session(engine) as session:
        items = session.exec(select(MenuItem).where(MenuItem.available == True)).all()
    
    return {
        "items": [
            {**item.model_dump(exclude = {"quantity"}), "_links": item_links(item.id)}
            for item in items
        ],
        
        "_links": menu_links(),
    }


@app.get("/stock")
def get_stock():
    with Session(engine) as session:
        items = session.exec(select(MenuItem)).all()
    
    return {
        "stock": [
            {"id": i.id, "name": i.name, "quantity": i.quantity, "available": i.available}
            for i in items
        ]
    }


@app.get("/menu/{item_id}")
def get_menu_item(item_id: int):
    with Session(engine) as session:
        item = session.get(MenuItem, item_id)
    
    if not item:
        raise HTTPException(status_code = 404, detail = "Item not found")
    
    return {**item.model_dump(exclude = {"quantity"}), "_links": item_links(item.id)}


@app.get("/health")
def health():
    return {"status": "ok", "service": "restaurant-service"}