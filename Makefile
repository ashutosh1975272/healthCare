.PHONY: dev down migrate test seed reset load-test eval

COMPOSE := docker compose -f docker-compose.local-online.yml

dev:
	$(COMPOSE) up -d --build api

down:
	$(COMPOSE) down

migrate:
	$(COMPOSE) exec api alembic upgrade head

test:
	cd backend && pytest -q

# DANGER: seeds against Neon (online). Reference rows are already there —
# running this duplicates learn/body-test data. Only for a wiped DB:
#   SEED_ONLINE=1 make seed
seed:
ifndef SEED_ONLINE
	@echo "Refusing: online DB already has seed data. Use SEED_ONLINE=1 to force."
else
	$(COMPOSE) exec api python /app/seed/seed.py
endif

reset:
	$(COMPOSE) down
	$(COMPOSE) up -d --build api
	@echo "Waiting for API health..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -sf http://localhost:8000/health >/dev/null && break; \
		sleep 3; \
	done

load-test:
	@echo "load-test — wire k6 in M23"

eval:
	@echo "eval — wire AI eval harness in M6+"
