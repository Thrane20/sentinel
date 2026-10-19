FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir paho-mqtt==2.1.0 requests==2.32.5
COPY services/animal-worker/worker.py ./worker.py
COPY services/animal-worker/ivsec_notifications.py ./ivsec_notifications.py
COPY services/animal-worker/test_ivsec_notifications.py ./test_ivsec_notifications.py
COPY services/animal-worker/recorder_security.py ./recorder_security.py
COPY services/animal-worker/test_recorder_security.py ./test_recorder_security.py
COPY services/animal-worker/test_worker.py ./test_worker.py
COPY services/animal-worker/cpu_monitor.py ./cpu_monitor.py
COPY services/animal-worker/test_cpu_monitor.py ./test_cpu_monitor.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/worker.py"]
