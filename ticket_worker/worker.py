import os
import smtplib
import time
from email.message import EmailMessage

import grpc
import psycopg
import qrcode
import redis
import requests

import events_pb2
import events_pb2_grpc

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://tickets:tickets@localhost:5432/tickets")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QR_DIR = os.getenv("QR_DIR", "/app/generated_qr")
CONSUL_URL = os.getenv("CONSUL_URL", "http://consul:8500")
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM") or GMAIL_USER
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
REQUEST_TIMEOUT = 5

def get_conn():
    return psycopg.connect(DATABASE_URL)

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
        if attempt < 10:
            time.sleep(1)
    raise RuntimeError(f"{name} is not registered in Consul")

def get_event(event_id: int):
    channel = grpc.insecure_channel(service_address("event-service"))
    stub = events_pb2_grpc.EventServiceStub(channel)
    return stub.GetEvent(events_pb2.GetEventRequest(event_id=event_id))

def send_ticket_email(buyer_email: str, buyer_name: str, token: str, ticket_id: int, event):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise RuntimeError("Gmail credentials are not configured")

    message = EmailMessage()
    message["Subject"] = f"Ваш билет на {event.title}"
    message["From"] = MAIL_FROM
    message["To"] = buyer_email
    message.set_content(
        f"""Здравствуйте, {buyer_name}!

Ваш билет оплачен.

Мероприятие:
{event.title}

Описание:
{event.description}

Дата и время:
{event.event_date}

Место:
{event.location}

Номер билета:
{ticket_id}

Код для входа:
{token}

Покажите этот код организатору на входе.
"""
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(message)

def generate_qr_and_send_email(ticket_id: int):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT qr_token, buyer_email, buyer_name, event_id
            FROM tickets
            WHERE id = %s AND status = 'PAID_QR_PENDING'
            """,
            (ticket_id,),
        ).fetchone()
        if not row:
            return

        token, buyer_email, buyer_name, event_id = row
        time.sleep(2)
        os.makedirs(QR_DIR, exist_ok=True)
        path = os.path.join(QR_DIR, f"ticket-{ticket_id}.png")
        image = qrcode.make(token)
        image.save(path)

        try:
            event = get_event(event_id)
            send_ticket_email(buyer_email, buyer_name, token, ticket_id, event)
            conn.execute(
                "UPDATE tickets SET status = 'READY', qr_image_path = %s WHERE id = %s",
                (path, ticket_id),
            )
        except Exception as error:
            print(f"ticket email failed for {ticket_id}: {error}", flush=True)
            conn.execute(
                "UPDATE tickets SET status = 'EMAIL_FAILED', qr_image_path = %s WHERE id = %s",
                (path, ticket_id),
            )

def main():
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    print("ticket-worker started", flush=True)
    while True:
        _, ticket_id = client.blpop("qr_jobs")
        generate_qr_and_send_email(int(ticket_id))

if __name__ == "__main__":
    main()