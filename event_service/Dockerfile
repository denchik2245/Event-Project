FROM python:3.12-slim

WORKDIR /app
COPY event_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY event_service /app/event_service

RUN python -m grpc_tools.protoc -I/app/common/protos \
  --python_out=/app/event_service --grpc_python_out=/app/event_service \
  /app/common/protos/events.proto

ENV PYTHONPATH=/app/event_service
CMD ["python", "-m", "event_service.server"]