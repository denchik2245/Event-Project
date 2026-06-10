import asyncio
import os
import time
from pathlib import Path

import grpc
import qrcode
import qrcode.image.svg
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

import events_pb2
import events_pb2_grpc
import tickets_pb2
import tickets_pb2_grpc

CONSUL_URL = os.getenv("CONSUL_URL", "http://consul:8500")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080")
REQUEST_TIMEOUT = 5
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Event Platform API Gateway", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class EventCreate(BaseModel):
    title: str = Field(min_length=3)
    description: str = ""
    event_date: str
    location: str
    total_tickets: int = Field(ge=0)
    price_cents: int = Field(ge=0)

class EventUpdate(EventCreate):
    pass

class TicketBuy(BaseModel):
    event_id: int
    buyer_name: str = Field(min_length=2)
    buyer_email: EmailStr

class TicketValidation(BaseModel):
    qr_token: str

def service_address(name: str) -> str:
    for attempt in range(1, 6):
        try:
            response = requests.get(
                f"{CONSUL_URL}/v1/catalog/service/{name}",
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            services = response.json()
        except requests.RequestException:
            services = []

        if services:
            service = services[0]
            return f"{service['ServiceAddress']}:{service['ServicePort']}"

        if attempt < 5:
            time.sleep(0.5)

    raise HTTPException(status_code=503, detail=f"{name} is unavailable")

def grpc_error(error: grpc.RpcError):
    code = error.code()
    if code == grpc.StatusCode.NOT_FOUND:
        return HTTPException(status_code=404, detail=error.details())
    if code == grpc.StatusCode.FAILED_PRECONDITION:
        return HTTPException(status_code=409, detail=error.details())
    return HTTPException(status_code=502, detail=error.details())

def event_dict(event):
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "event_date": event.event_date,
        "location": event.location,
        "total_tickets": event.total_tickets,
        "available_tickets": event.available_tickets,
        "price_cents": event.price_cents,
    }

def ticket_dict(ticket):
    return {
        "id": ticket.id,
        "event_id": ticket.event_id,
        "buyer_name": ticket.buyer_name,
        "buyer_email": ticket.buyer_email,
        "status": ticket.status,
        "qr_token": ticket.qr_token,
        "qr_image_path": ticket.qr_image_path,
        "visited": ticket.visited,
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "visitor.html")

@app.get("/visitor")
async def visitor_page():
    return FileResponse(STATIC_DIR / "visitor.html")

@app.get("/organizer")
async def organizer_page():
    return FileResponse(STATIC_DIR / "organizer.html")

@app.get("/pay/{ticket_id}")
async def payment_page(ticket_id: int):
    return FileResponse(STATIC_DIR / "payment.html")

@app.get("/tickets/{ticket_id}/payment-qr")
async def payment_qr(ticket_id: int):
    payment_url = f"{PUBLIC_BASE_URL}/pay/{ticket_id}"
    image = qrcode.make(payment_url, image_factory=qrcode.image.svg.SvgPathImage)
    return Response(content=image.to_string(), media_type="image/svg+xml")

@app.post("/events", status_code=201)
async def create_event(payload: EventCreate):
    def call():
        channel = grpc.insecure_channel(service_address("event-service"))
        stub = events_pb2_grpc.EventServiceStub(channel)
        return stub.CreateEvent(
            events_pb2.CreateEventRequest(
                title=payload.title,
                description=payload.description,
                event_date=payload.event_date,
                location=payload.location,
                total_tickets=payload.total_tickets,
                price_cents=payload.price_cents,
            )
        )

    try:
        return event_dict(await asyncio.to_thread(call))
    except grpc.RpcError as error:
        raise grpc_error(error)

@app.get("/events")
async def list_events():
    def call():
        channel = grpc.insecure_channel(service_address("event-service"))
        stub = events_pb2_grpc.EventServiceStub(channel)
        return stub.ListEvents(events_pb2.ListEventsRequest())

    try:
        result = await asyncio.to_thread(call)
        return [event_dict(event) for event in result.events]
    except grpc.RpcError as error:
        raise grpc_error(error)

@app.get("/events/{event_id}")
async def get_event(event_id: int):
    def call():
        channel = grpc.insecure_channel(service_address("event-service"))
        stub = events_pb2_grpc.EventServiceStub(channel)
        return stub.GetEvent(events_pb2.GetEventRequest(event_id=event_id))

    try:
        return event_dict(await asyncio.to_thread(call))
    except grpc.RpcError as error:
        raise grpc_error(error)

@app.put("/events/{event_id}")
async def update_event(event_id: int, payload: EventUpdate):
    def call():
        channel = grpc.insecure_channel(service_address("event-service"))
        stub = events_pb2_grpc.EventServiceStub(channel)
        return stub.UpdateEvent(
            events_pb2.UpdateEventRequest(
                event_id=event_id,
                title=payload.title,
                description=payload.description,
                event_date=payload.event_date,
                location=payload.location,
                total_tickets=payload.total_tickets,
                price_cents=payload.price_cents,
            )
        )

    try:
        return event_dict(await asyncio.to_thread(call))
    except grpc.RpcError as error:
        raise grpc_error(error)

@app.delete("/events/{event_id}")
async def delete_event(event_id: int):
    def call():
        channel = grpc.insecure_channel(service_address("event-service"))
        stub = events_pb2_grpc.EventServiceStub(channel)
        return stub.DeleteEvent(events_pb2.DeleteEventRequest(event_id=event_id))

    try:
        result = await asyncio.to_thread(call)
        return {"deleted": result.deleted}
    except grpc.RpcError as error:
        raise grpc_error(error)

@app.post("/tickets", status_code=202)
async def buy_ticket(payload: TicketBuy):
    def call():
        channel = grpc.insecure_channel(service_address("ticket-service"))
        stub = tickets_pb2_grpc.TicketServiceStub(channel)
        return stub.BuyTicket(
            tickets_pb2.BuyTicketRequest(
                event_id=payload.event_id,
                buyer_name=payload.buyer_name,
                buyer_email=str(payload.buyer_email),
            )
        )

    try:
        ticket = await asyncio.to_thread(call)
        data = ticket_dict(ticket)
        data["payment_url"] = f"{PUBLIC_BASE_URL}/pay/{ticket.id}"
        data["payment_qr_url"] = f"/tickets/{ticket.id}/payment-qr"
        data["message"] = "Ticket reservation created, waiting for payment"
        return data
    except grpc.RpcError as error:
        raise grpc_error(error)

@app.post("/tickets/{ticket_id}/pay")
async def pay_ticket(ticket_id: int):
    def call():
        channel = grpc.insecure_channel(service_address("ticket-service"))
        stub = tickets_pb2_grpc.TicketServiceStub(channel)
        return stub.PayTicket(tickets_pb2.PayTicketRequest(ticket_id=ticket_id))

    try:
        ticket = await asyncio.to_thread(call)
        data = ticket_dict(ticket)
        data["message"] = "Payment confirmed, ticket code email is queued"
        return data
    except grpc.RpcError as error:
        raise grpc_error(error)

@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int):
    def call():
        channel = grpc.insecure_channel(service_address("ticket-service"))
        stub = tickets_pb2_grpc.TicketServiceStub(channel)
        return stub.GetTicket(tickets_pb2.GetTicketRequest(ticket_id=ticket_id))

    try:
        return ticket_dict(await asyncio.to_thread(call))
    except grpc.RpcError as error:
        raise grpc_error(error)

@app.post("/tickets/validate")
async def validate_ticket(payload: TicketValidation):
    def call():
        channel = grpc.insecure_channel(service_address("ticket-service"))
        stub = tickets_pb2_grpc.TicketServiceStub(channel)
        return stub.ValidateTicket(tickets_pb2.ValidateTicketRequest(qr_token=payload.qr_token))

    try:
        result = await asyncio.to_thread(call)
        return {"ok": result.ok, "message": result.message, "ticket_id": result.ticket_id}
    except grpc.RpcError as error:
        raise grpc_error(error)
