FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY packages ./packages
COPY infrastructure ./infrastructure
COPY research ./research
COPY scripts ./scripts

RUN python -m pip install --no-cache-dir ".[dev,yahoo]"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "market_genome_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
