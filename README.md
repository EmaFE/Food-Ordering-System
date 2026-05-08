# Dysfunctional Systems

A distributed food ordering system built as part of COMP30220 Assignment.

Link to report: https://docs.google.com/document/d/1hddA38j8OQTGtCt_fzh6-6gBzNPcQ4w3Opi0XpxHB4g/edit?usp=sharing

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- [Postman](https://www.postman.com/downloads/) (optional for manual API testing via the included collection)

---

## 1. Running the System

From the project root (where the `docker-compose.yml` is):

```bash
docker compose up --build
```

This starts all services. Wait until all services are healthy before sending requests (roughly 10–15 seconds).
Everything runs locally. 

The API Gateway (nginx) is the main entry point for all requests. It runs on `localhost:8080`

The RabbitMQ Management UI is available on `localhost:15672`. Credentials are `guest` / `guest`

---

## 2. Interacting via Terminal

All requests go through the API Gateway at `http://localhost:8080/api`, and the system can be interacted with via curl commands.

Some sample commands:

**Register a user**
```bash
curl -X POST http://localhost:8080/api/authentication/register \
  -H "Content-Type: application/json" \
  -d '{"name": "John", "email": "john@test.com", "password": "pizza123"}'
```

**Login**
```bash
curl -X POST http://localhost:8080/api/authentication/login \
  -H "Content-Type: application/json" \
  -d '{"email": "john@test.com", "password": "pizza123"}'
```

Make sure to copy the `token` from the response of these two requests.

**Browse the menu**
```bash
curl http://localhost:8080/api/restaurant/menu
```
A `token` is not needed for this request.


**Place an order**
```bash
curl -X POST http://localhost:8080/api/orders/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your_token>" \
  -d '{"items": [{"item_id": 6, "quantity": 1}]}'
```

**View your previous orders**
```bash
curl http://localhost:8080/api/orders/my-orders \
  -H "Authorization: Bearer <your_token>"
```

**Check circuit breaker status**
```bash
curl http://localhost:8080/api/orders/circuit-breaker/status
```


---

## 3. Interacting via Postman

We suggest using Postman to interact with the system over curl. Import the postman_collection_for_testing.json from the repository, which already has all requests prepared with the correct endpoints, headers, and example bodies into Postman Start with registration to obtain a token for subsequent requests. Add this token to Headers, with Key: Authorization and Value: Bearer <your_token> 

---

## 4. Autoscaler

The autoscaler monitors the `items_reserved` RabbitMQ queue and dynamically scales the Order and Payment services between 1 and 2 instances. To run autoscaler, in a **separate terminal** from the project root:

```bash
python autoscaler.py
```

The autoscaler requires the Docker Compose stack to already be running. It will log scaling events to the terminal as queue depth changes. It provides several configurable parameters in the script. 

---

## 5. Load Test

The load test simulates 10 concurrent users, each placing orders every 2 seconds, to drive up queue depth and trigger autoscaling. This is a mechanism to simulate rush hour scenarios, and witness the scaler work.

To run the load test, in a **separate terminal** from the project root:

```bash
python load_test.py
```

The system and autoscaler should both be running before starting the load test. Watch the RabbitMQ Management UI at `http://localhost:15672` to observe the `items_reserved` queue depth rise and fall as the autoscaler responds. Use `Ctrl+C` to stop the load test.

---

## Stopping the System

```bash
docker compose down
```
