FROM python:3.12-slim

WORKDIR /app
COPY ticket_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY ticket_service /app/ticket_service

RUN python -m grpc_tools.protoc -I/app/common/protos \
  --python_out=/app/ticket_service --grpc_python_out=/app/ticket_service \
  /app/common/protos/events.proto /app/common/protos/tickets.proto

ENV PYTHONPATH=/app/ticket_service
CMD ["python", "-m", "ticket_service.server"]
