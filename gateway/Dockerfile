FROM python:3.12-slim

WORKDIR /app
COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY gateway /app/gateway

RUN python -m grpc_tools.protoc -I/app/common/protos \
  --python_out=/app/gateway --grpc_python_out=/app/gateway \
  /app/common/protos/events.proto /app/common/protos/tickets.proto

ENV PYTHONPATH=/app/gateway
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
