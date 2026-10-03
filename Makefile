.PHONY: install db-up init-db mock-api etl test export dashboard
install:
	python -m venv .venv && .venv/bin/pip install -r requirements.txt
db-up:
	docker compose up -d db
init-db:
	python -m etl.init_db
mock-api:
	python -m mock_api.app
etl:
	python -m etl.run
test:
	pytest -q
export:
	python -m etl.export
dashboard:
	python -m etl.dashboard   # -> exports/dashboard.html (open it in any browser)
