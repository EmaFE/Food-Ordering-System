import time
import subprocess
import urllib.request
import json
import base64

RABBITMQ_API = "http://localhost:15672/api/queues/%2F/items_reserved"
AUTH = base64.b64encode(b"guest:guest").decode()
MIN_INSTANCES = 1
MAX_INSTANCES = 2
SCALE_UP_THRESHOLD = 3
POLL_INTERVAL = 5

current_instances = 1


def get_queue_depth():
    try:
        req = urllib.request.Request(RABBITMQ_API, headers = {"Authorization": f"Basic {AUTH}"})
        with urllib.request.urlopen(req, timeout = 3) as r:
            return json.loads(r.read()).get("messages", 0)
    except Exception:
        pass
    return 0


def scale(n):
    subprocess.run(
        ["docker", "compose", "up", "--scale", f"order-service={n}", "-d", "--no-recreate"],
        capture_output = True
    )
    print(f"  --> Scaled order-service to {n} instance(s)")


print("Autoscaler started. Polling every 5s...\n")

while True:
    depth = get_queue_depth()
    print(f"Queue depth: {depth} | Instances: {current_instances}")

    if depth > SCALE_UP_THRESHOLD and current_instances < MAX_INSTANCES:
        current_instances += 1
        scale(current_instances)

    elif depth == 0 and current_instances > MIN_INSTANCES:
        current_instances -= 1
        scale(current_instances)

    time.sleep(POLL_INTERVAL)
