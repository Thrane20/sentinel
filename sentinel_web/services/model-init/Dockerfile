FROM python:3.12-slim
WORKDIR /opt/sentinel
RUN pip install --no-cache-dir onnx==1.17.0
COPY services/model-init/install.py ./install.py
ENTRYPOINT ["python", "/opt/sentinel/install.py"]
