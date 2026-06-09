.PHONY: build up down logs ps check demo

build:
 docker compose build

up:
 docker compose up --build

down:
 docker compose down

logs:
 docker compose logs -f

ps:
 docker compose ps

check:
 python3 -m py_compile gateway/main.py event_service/server.py ticket_service/server.py ticket_worker/worker.py
 node --check gateway/static/app.js
 docker compose config --no-interpolate

demo:
 sh scripts/demo.sh