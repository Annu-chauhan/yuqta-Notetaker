.PHONY: env up down logs ps test test-db health seed migrate clean

env:  ## Create .env from the example if it does not exist
	@test -f .env || cp .env.example .env

up: env  ## Build and start postgres, backend and frontend
	docker compose up --build -d

down:  ## Stop all services (keeps the database volume)
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

test:  ## Backend unit tests inside the backend container
	docker compose run --rm --no-deps backend python -m pytest -q

test-db:  ## Backend tests including the real-database checks
	docker compose run --rm -e RUN_DB_TESTS=1 backend python -m pytest -q

health:
	curl -s http://localhost:$${BACKEND_HOST_PORT:-8000}/health

seed:  ## Reset demo business data from data/seed.sql
	docker compose exec backend python -m app.db.seed

migrate:  ## Apply database migrations
	docker compose exec backend alembic upgrade head

clean:  ## Stop everything and DELETE the database volume
	docker compose down -v
