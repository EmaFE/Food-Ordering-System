import threading
import urllib.request
import json
import random
import time

BASE = "http://localhost:8080/api"
NUM_USERS = 10
ORDERS_PER_USER = 5


def post(url, body):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data = data, headers = {"Content-Type": "application/json"})
    
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def post_auth(url, body, token):
    data = json.dumps(body).encode()
    
    req  = urllib.request.Request(url, data=data, headers={
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {token}"
    })
    
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def register():
    email = f"loadtest{random.randint(10000, 99999)}@test.com"
    
    return post(f"{BASE}/authentication/register", {
        "name":     "Load Test User",
        "email":    email,
        "password": "password123"
    })["token"]


def place_orders(token):
    for _ in range(ORDERS_PER_USER):
        for attempt in range(3):
            try:
                post_auth(f"{BASE}/orders/", {"items": [{"item_id": 6, "quantity": 1}]}, token)
                break
            except Exception:
                if attempt < 2:
                    time.sleep(2)
                else:
                    print("Order failed after 3 attempts")
        time.sleep(5)


print(f"Placing {NUM_USERS * ORDERS_PER_USER} orders across {NUM_USERS} users...\n")

threads = []
for _ in range(NUM_USERS):
    token = register()
    t = threading.Thread(target = place_orders, args = (token,))
    threads.append(t)

for t in threads:
    t.start()

for t in threads:
    t.join()

print("Load test complete.")
