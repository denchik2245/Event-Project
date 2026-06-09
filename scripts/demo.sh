#!/usr/bin/env sh
set -eu

API_URL="${API_URL:-http://localhost:8080}"

echo "Creating event..."
curl -sS -X POST "$API_URL/events" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "University Tech Night",
    "description": "Student meetup with talks and networking",
    "event_date": "2026-06-15T18:00:00",
    "location": "Main campus, room 301",
    "total_tickets": 50,
    "price_cents": 100000
  }'

echo
echo "Reserving ticket..."
curl -sS -X POST "$API_URL/tickets" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": 1,
    "buyer_name": "Ivan Petrov",
    "buyer_email": "ivan@example.com"
  }'

echo
echo "Open the payment page from the response, or use:"
echo "$API_URL/pay/1"
echo
echo "After pressing Pay, check the buyer mailbox and validate the emailed code on:"
echo "$API_URL/organizer"