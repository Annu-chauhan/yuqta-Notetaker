FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home yuqta
USER yuqta

EXPOSE 8000

# Apply migrations, load demo data into an empty database, then serve.
CMD ["sh", "-c", "alembic upgrade head && python -m app.db.seed --if-empty && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
