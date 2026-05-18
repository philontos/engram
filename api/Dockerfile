FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./
COPY shared ./shared

RUN mkdir -p data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
