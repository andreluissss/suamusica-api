FROM python:3.11-slim

WORKDIR /app

COPY requirements_api.txt .
RUN pip install --no-cache-dir -r requirements_api.txt

COPY suamusica_api.py .

EXPOSE $PORT

CMD uvicorn suamusica_api:app --host 0.0.0.0 --port $PORT