import asyncio
import json
import logging
import os
import aio_pika
import httpx
from sqlmodel import Session, select
from database import Order, OrderItem, engine
from circuit_breaker import CircuitBreaker


logger = logging.getLogger(__name__)

PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")

# rabbitMQ setup
RABBITMQ_URL = "amqp://guest:guest@rabbitmq:5672/"
rabbitmq_connection = None
rabbitmq_channel = None

# build CB
payment_breaker = CircuitBreaker(failure_threshold = 3, recovery_timeout = 15)


async def connect_rabbitmq():
    global rabbitmq_connection, rabbitmq_channel

    for attempt in range(10):
        try:
            rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
            rabbitmq_channel = await rabbitmq_connection.channel()
            logger.info("Connected to RabbitMQ")

            await rabbitmq_channel.declare_queue("order_created", durable = True)
            await rabbitmq_channel.declare_queue("items_reserved", durable = True)
            await rabbitmq_channel.declare_queue("items_unavailable", durable = True)
            await rabbitmq_channel.declare_queue("release_items", durable=True)
            await rabbitmq_channel.declare_queue("payment_success", durable = True)
            return

        except Exception as e:
            logger.warning("RabbitMQ not ready (attempt %d): %s", attempt + 1, e)
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
    # define which queues to listen to
    items_reserved_queue = await rabbitmq_channel.get_queue("items_reserved")
    items_unavailable_queue = await rabbitmq_channel.get_queue("items_unavailable")

    await items_reserved_queue.consume(handle_items_reserved)
    await items_unavailable_queue.consume(handle_items_unavailable)

    logger.info("Order Service listening for events")


# message handlers

# triggered when restaurant confirms items were reserved (in stock)
async def handle_items_reserved(message: aio_pika.IncomingMessage):
    async with message.process():
        data = json.loads(message.body)

        order_id = data.get("order_id")
        total = data.get("total")
        item_details = data.get("items", [])

        logger.info(f"Items reserved for order {order_id} - attempting payment")

        with Session(engine) as session:
            order = session.get(Order, order_id)

            if not order:
                logger.error(f"Order {order_id} not found")
                return

            # update order total and item names/prices confirmed by restaurant
            order.total = total
            for detail in item_details:
                order_item = session.exec(
                    select(OrderItem).where(
                        OrderItem.order_id == order_id,
                        OrderItem.item_id == detail["item_id"]
                    )
                ).first()
                if order_item:
                    order_item.name = detail["name"]
                    order_item.price = detail["price"]

            item_payloads = [
                {"item_id": i.item_id, "quantity": i.quantity}
                for i in session.exec(select(OrderItem).where(OrderItem.order_id == order_id)).all()
            ]

            session.commit()

            # call payment service via circuit breaker
            try:
                async with httpx.AsyncClient() as client:
                    async def do_payment():
                        response = await client.post(
                            f"{PAYMENT_SERVICE_URL}/charge",
                            json = {"order_id": order_id, "amount": total},
                            timeout = 20
                        )

                        response.raise_for_status()
                        return response.json()

                    result = await payment_breaker.call(do_payment())

                # payment succeeds --> update order status to confirmed, publish payment_success message
                order.status = "confirmed"
                order.payment_id = result.get("payment_id")
                session.add(order)
                session.commit()

                await publish_event("payment_success", {"order_id": order_id})
                logger.info(f"Payment successful for order {order_id}")

            # payment fails --> update order status to cancelled, publish payment_failed message with items so restaurant can release stock

            except Exception as e:
                logger.error(f"Payment failed for order {order_id}: {e}")
                
                # determine reason
                if isinstance(e, RuntimeError): # CB is OPEN
                    reason = "payment_processor_failed"

                elif isinstance(e, httpx.HTTPStatusError):
                    if e.response.status_code == 402:
                        reason = "payment_declined"
                    else:
                        reason = "payment_processor_failed"

                elif isinstance(e, httpx.RequestError):
                    reason = "payment_processor_failed"

                else:
                    reason = "unexpected_error"

                order.status = "cancelled"
                order.cancellation_reason = reason
                session.add(order)
                session.commit()

                await publish_event("release_items", {
                    "order_id": order_id,
                    "items": item_payloads,
                    "reason": reason
                })

# restaurant does not have enough stock --> update order status to cancelled
async def handle_items_unavailable(message: aio_pika.IncomingMessage):
    async with message.process():
        data = json.loads(message.body)
        order_id = data.get("order_id")

        logger.info(f"Items unavailable for order {order_id} - cancelling")

        with Session(engine) as session:
            order = session.get(Order, order_id)
            if order:
                order.status = "cancelled"
                order.cancellation_reason = "insufficient_stock"
                session.add(order)
                session.commit()