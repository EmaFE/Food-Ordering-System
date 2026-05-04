FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir fastapi uvicorn sqlmodel python-jose[cryptography] "passlib[bcrypt]==1.7.4" "bcrypt==4.0.1"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]