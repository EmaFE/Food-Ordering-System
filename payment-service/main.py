import uuid
import random
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# Failure toggle 
# In-memory,  resets to False every time the service restarts
_payment_should_fail = False


app = FastAPI()


# Schemas
class ChargeRequest(BaseModel):
    order_id: int
    amount: float


# Routes

@app.post("/charge")
async def charge(request: ChargeRequest):
    global _payment_should_fail

    await asyncio.sleep(10)  # simulate payment processing delay

    if _payment_should_fail:
        raise HTTPException(status_code = 503, detail = "Payment processor unavailable")

    # simulate user's payment being declined with a prob of 20%
    if random.random() < 0.2:
        raise HTTPException(status_code = 402, detail = "Payment declined")

    payment_id = str(uuid.uuid4())

    return {
        "payment_id": payment_id,
        "order_id": request.order_id,
        "amount": request.amount,
        "status": "success",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "payment-service",
        "mode": "failing" if _payment_should_fail else "healthy",
    }


# Demo Toggle Routes

@app.post("/mock/break")
def break_payment():
    global _payment_should_fail
    _payment_should_fail = True
    return {"status": "Payment processor is now FAILING"}


@app.post("/mock/fix")
def fix_payment():
    global _payment_should_fail
    _payment_should_fail = False
    return {"status": "Payment processor is now HEALTHY"}

