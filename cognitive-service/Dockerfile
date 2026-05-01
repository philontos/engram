FROM python:3.12-slim

WORKDIR /app

COPY cognitive-service/requirements.txt ./requirements.txt
RUN apt-get update && apt-get install -y g++ && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY cognitive-service/ .
COPY shared ./shared

RUN mkdir -p data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
