FROM python:3.12-slim

WORKDIR /app
COPY ticket_worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY ticket_worker /app/ticket_worker
RUN python -m grpc_tools.protoc -I/app/common/protos \
  --python_out=/app/ticket_worker --grpc_python_out=/app/ticket_worker \
  /app/common/protos/events.proto
RUN mkdir -p /app/generated_qr

ENV PYTHONPATH=/app/ticket_worker
CMD ["python", "-m", "ticket_worker.worker"]