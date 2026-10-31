# PiyaNota backend

Flask API for Module 3. Configuration comes from `PIYA_*` environment variables (see
`backend/.env.example`); the app does not read a `.env` file itself.

## Setup (Windows)

```
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
```

## Tests

Tests need PostgreSQL at `TEST_DATABASE_URL` (default `postgresql://piya:piya@localhost:55432/piya_test`).
Start it with:

```
docker run -d --name piya-pg-test -e POSTGRES_USER=piya -e POSTGRES_PASSWORD=piya -e POSTGRES_DB=piya_test -p 55432:5432 postgres:16
```

Run from the repository root:

```
backend/.venv/Scripts/python -m pytest backend/tests -v
```
