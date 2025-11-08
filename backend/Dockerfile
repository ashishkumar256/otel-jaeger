FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt
RUN opentelemetry-bootstrap --action=install
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]