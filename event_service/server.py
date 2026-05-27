import os
import time
from concurrent import futures

import grpc
import psycopg
import requests

import events_pb2
import events_pb2_grpc


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://events:events@localhost:5432/events")
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))
CONSUL_URL = os.getenv("CONSUL_URL", "http://consul:8500")
SERVICE_NAME = "event-service"
REQUEST_TIMEOUT = 5


def get_conn():
    return psycopg.connect(DATABASE_URL)


def migrate():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id BIGSERIAL PRIMARY KEY,
              title TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              event_date TEXT NOT NULL,
              location TEXT NOT NULL,
              total_tickets INTEGER NOT NULL CHECK (total_tickets >= 0),
              available_tickets INTEGER NOT NULL CHECK (available_tickets >= 0),
              price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


def to_event(row):
    return events_pb2.EventResponse(
        id=row[0],
        title=row[1],
        description=row[2],
        event_date=row[3],
        location=row[4],
        total_tickets=row[5],
        available_tickets=row[6],
        price_cents=row[7],
    )


class EventService(events_pb2_grpc.EventServiceServicer):
    def CreateEvent(self, request, context):
        with get_conn() as conn:
            row = conn.execute(
                """
                INSERT INTO events(title, description, event_date, location, total_tickets, available_tickets, price_cents)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, title, description, event_date, location, total_tickets, available_tickets, price_cents
                """,
                (
                    request.title,
                    request.description,
                    request.event_date,
                    request.location,
                    request.total_tickets,
                    request.total_tickets,
                    request.price_cents,
                ),
            ).fetchone()
        return to_event(row)

    def GetEvent(self, request, context):
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, title, description, event_date, location, total_tickets, available_tickets, price_cents
                FROM events WHERE id = %s
                """,
                (request.event_id,),
            ).fetchone()
        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, "event not found")
        return to_event(row)

    def ListEvents(self, request, context):
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, title, description, event_date, location, total_tickets, available_tickets, price_cents
                FROM events ORDER BY id DESC
                """
            ).fetchall()
        return events_pb2.ListEventsResponse(events=[to_event(row) for row in rows])

    def UpdateEvent(self, request, context):
        with get_conn() as conn:
            current = conn.execute(
                """
                SELECT total_tickets, available_tickets
                FROM events WHERE id = %s
                """,
                (request.event_id,),
            ).fetchone()
            if not current:
                context.abort(grpc.StatusCode.NOT_FOUND, "event not found")

            old_total, old_available = current
            sold_tickets = old_total - old_available
            if request.total_tickets < sold_tickets:
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "total tickets cannot be less than already sold tickets",
                )

            row = conn.execute(
                """
                UPDATE events
                SET title = %s,
                    description = %s,
                    event_date = %s,
                    location = %s,
                    total_tickets = %s,
                    available_tickets = %s,
                    price_cents = %s
                WHERE id = %s
                RETURNING id, title, description, event_date, location, total_tickets, available_tickets, price_cents
                """,
                (
                    request.title,
                    request.description,
                    request.event_date,
                    request.location,
                    request.total_tickets,
                    request.total_tickets - sold_tickets,
                    request.price_cents,
                    request.event_id,
                ),
            ).fetchone()
        return to_event(row)

    def DeleteEvent(self, request, context):
        with get_conn() as conn:
            row = conn.execute(
                """
                DELETE FROM events WHERE id = %s
                RETURNING id
                """,
                (request.event_id,),
            ).fetchone()
        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, "event not found")
        return events_pb2.DeleteEventResponse(deleted=True)

    def ReserveSeat(self, request, context):
        with get_conn() as conn:
            row = conn.execute(
                """
                UPDATE events
                SET available_tickets = available_tickets - 1
                WHERE id = %s AND available_tickets > 0
                RETURNING available_tickets
                """,
                (request.event_id,),
            ).fetchone()
        if not row:
            return events_pb2.ReserveSeatResponse(reserved=False, available_tickets=0)
        return events_pb2.ReserveSeatResponse(reserved=True, available_tickets=row[0])


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
                raise RuntimeError("cannot register event-service in Consul") from error
            time.sleep(1)


def serve():
    migrate()
    register_in_consul()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    events_pb2_grpc.add_EventServiceServicer_to_server(EventService(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    print(f"{SERVICE_NAME} started on {GRPC_PORT}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()