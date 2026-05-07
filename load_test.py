import threading
import urllib.request
import json
import random
import time

BASE = "http://localhost:8080/api"
NUM_USERS = 10
DELAY_BETWEEN_ORDERS = 2  # seconds between each order per user

stop_event = threading.Event()


def post(url, body):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
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


def place_orders(token, user_id):
    order_count = 0
    while not stop_event.is_set():
        try:
            post_auth(f"{BASE}/orders/", {"items": [{"item_id": 6, "quantity": 1}]}, token)
            order_count += 1
            print(f"[user-{user_id}] Order #{order_count} placed")
        except Exception as e:
            print(f"[user-{user_id}] Order failed: {e}")
        stop_event.wait(DELAY_BETWEEN_ORDERS)


print(f"Starting continuous load test with {NUM_USERS} users. Press Ctrl+C to stop.\n")

threads = []
for i in range(NUM_USERS):
    token = register()
    t = threading.Thread(target = place_orders, args = (token, i + 1), daemon = True)
    threads.append(t)

for t in threads:
    t.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nStopping load test...")
    stop_event.set()

for t in threads:
    t.join()

print("Load test stopped.")
