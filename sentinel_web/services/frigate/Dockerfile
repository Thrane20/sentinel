FROM ghcr.io/blakeblackshear/frigate:0.17.2
COPY services/frigate/force_model_fp32.py /tmp/force_model_fp32.py
RUN python3 /tmp/force_model_fp32.py && rm /tmp/force_model_fp32.py
