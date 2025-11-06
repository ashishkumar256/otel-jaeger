FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

RUN opentelemetry-bootstrap --action=install

CMD ["python", "app.py"]
