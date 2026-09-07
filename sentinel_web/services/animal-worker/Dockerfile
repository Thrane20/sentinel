FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir paho-mqtt==2.1.0 requests==2.32.5
COPY services/animal-worker/worker.py ./worker.py
COPY services/animal-worker/test_worker.py ./test_worker.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/worker.py"]
