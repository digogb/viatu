PROJECT_DIR := $(shell pwd)

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f api worker beat

logs-worker:
	docker compose logs -f worker beat

build:
	docker compose build

test:
	docker compose run --rm --no-deps \
		-v $(PROJECT_DIR)/tests:/app/tests \
		-v $(PROJECT_DIR)/docs:/app/docs \
		api uv run pytest tests/ -v

primer:
	docker compose --profile primer run --rm primer

migrate:
	docker compose exec api uv run alembic upgrade head

shell:
	docker compose exec api bash
