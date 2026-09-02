FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY aethelgard ./aethelgard
RUN pip install --no-cache-dir ".[models,cloud,pdf]"
ENV PORT=8080
CMD ["sh", "-c", "aethelgard worker --host 0.0.0.0 --port ${PORT}"]
