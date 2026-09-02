FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY aethelgard ./aethelgard

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[all]"

EXPOSE 8080

CMD ["sh", "-c", "aethelgard worker --host 0.0.0.0 --port ${PORT:-8080}"]
