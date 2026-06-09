import os
import time
import uuid
from concurrent import futures

import grpc
import psycopg
import redis
import requests

import events_pb2
import events_pb2_grpc
import tickets_pb2
import tickets_pb2_grpc

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://tickets:tickets@localhost:5432/tickets")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CONSUL_URL = os.getenv("CONSUL_URL", "http://consul:8500")
GRPC_PORT = int(os.getenv("GRPC_PORT", "50052"))
SERVICE_NAME = "ticket-service"
REQUEST_TIMEOUT = 5

def get_conn():
    return psycopg.connect(DATABASE_URL)

def migrate():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
              id BIGSERIAL PRIMARY KEY,
              event_id BIGINT NOT NULL,
              buyer_name TEXT NOT NULL,
              buyer_email TEXT NOT NULL,
              status TEXT NOT NULL,
              qr_token TEXT NOT NULL UNIQUE,
              qr_image_path TEXT NOT NULL DEFAULT '',
              visited BOOLEAN NOT NULL DEFAULT false,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )

def to_ticket(row):
    return tickets_pb2.TicketResponse(
        id=row[0],
        event_id=row[1],
        buyer_name=row[2],
        buyer_email=row[3],
        status=row[4],
        qr_token=row[5],
        qr_image_path=row[6],
        visited=row[7],
    )

def service_address(name: str) -> str:
    for attempt in range(1, 11):
        response = requests.get(
            f"{CONSUL_URL}/v1/catalog/service/{name}",
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        services = response.json()
        if services:
            service = services[0]
            return f"{service['ServiceAddress']}:{service['ServicePort']}"
        if attempt == 10:
            break
        time.sleep(1)
    raise RuntimeError(f"{name} is not registered in Consul")

class TicketService(tickets_pb2_grpc.TicketServiceServicer):
    def __init__(self):
        self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)

    def BuyTicket(self, request, context):
        event_channel = grpc.insecure_channel(service_address("event-service"))
        event_stub = events_pb2_grpc.EventServiceStub(event_channel)
        event = event_stub.GetEvent(events_pb2.GetEventRequest(event_id=request.event_id))
        if event.available_tickets <= 0:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "no tickets available")

        token = str(uuid.uuid4())
        with get_conn() as conn:
            row = conn.execute(
                """
                INSERT INTO tickets(event_id, buyer_name, buyer_email, status, qr_token)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, event_id, buyer_name, buyer_email, status, qr_token, qr_image_path, visited
                """,
                (request.event_id, request.buyer_name, request.buyer_email, "PAYMENT_PENDING", token),
            ).fetchone()

        return to_ticket(row)

    def PayTicket(self, request, context):
        queued = False
        event_channel = grpc.insecure_channel(service_address("event-service"))
        event_stub = events_pb2_grpc.EventServiceStub(event_channel)

        with get_conn() as conn:
            row = conn.execute(
                """
                UPDATE tickets
                SET status = 'PAID_QR_PENDING'
                WHERE id = %s AND status = 'PAYMENT_PENDING'
                RETURNING id, event_id, buyer_name, buyer_email, status, qr_token, qr_image_path, visited
                """,
                (request.ticket_id,),
            ).fetchone()
            queued = row is not None

            if row:
                reservation = event_stub.ReserveSeat(events_pb2.ReserveSeatRequest(event_id=row[1]))
                if not reservation.reserved:
                  context.abort(grpc.StatusCode.FAILED_PRECONDITION, "no tickets available")

            if not row:
                row = conn.execute(
                    """
                    SELECT id, event_id, buyer_name, buyer_email, status, qr_token, qr_image_path, visited
                    FROM tickets WHERE id = %s
                    """,
                    (request.ticket_id,),
                ).fetchone()

        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, "ticket not found")

        if queued:
            self.redis.rpush("qr_jobs", row[0])

        return to_ticket(row)

    def GetTicket(self, request, context):
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, event_id, buyer_name, buyer_email, status, qr_token, qr_image_path, visited
                FROM tickets WHERE id = %s
                """,
                (request.ticket_id,),
            ).fetchone()
        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, "ticket not found")
        return to_ticket(row)

    def ValidateTicket(self, request, context):
        with get_conn() as conn:
            row = conn.execute(
                """
                UPDATE tickets
                SET visited = true, status = 'USED'
                WHERE qr_token = %s AND visited = false AND status = 'READY'
                RETURNING id
                """,
                (request.qr_token,),
            ).fetchone()
        if not row:
            return tickets_pb2.ValidateTicketResponse(
                ok=False,
                message="Билет не найден, не оплачен или уже использован",
            )
        return tickets_pb2.ValidateTicketResponse(
            ok=True,
            message="Проход разрешён",
            ticket_id=row[0],
        )

def register_in_consul():
    payload = {
        "ID": SERVICE_NAME,
        "Name": SERVICE_NAME,
        "Address": SERVICE_NAME,
        "Port": GRPC_PORT,
        "Check": {
            "TCP": f"{SERVICE_NAME}:{GRPC_PORT}",
            "Interval": "10s",
            "DeregisterCriticalServiceAfter": "1m",
        },
    }
    for attempt in range(1, 11):
        try:
            requests.put(
                f"{CONSUL_URL}/v1/agent/service/register",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            ).raise_for_status()
            return
        except requests.RequestException as error:
            if attempt == 10:
                raise RuntimeError("cannot register ticket-service in Consul") from error
            time.sleep(1)

def serve():
    migrate()
    register_in_consul()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    tickets_pb2_grpc.add_TicketServiceServicer_to_server(TicketService(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    print(f"{SERVICE_NAME} started on {GRPC_PORT}", flush=True)
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
