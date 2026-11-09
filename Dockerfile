# Stage 1: build the dashboard
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: API + built dashboard (fake provider only; no API keys in the image)
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    INTENTTRACE_LLM_PROVIDER=fake \
    INTENTTRACE_DB=/tmp/intenttrace.db
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
RUN pip install --no-cache-dir .
COPY benchmark/sample benchmark/sample
COPY benchmark/results.json benchmark/results.json
COPY --from=web /web/dist web/dist
EXPOSE 8787
CMD ["sh", "-c", "intenttrace load-sample && intenttrace paygate-load-sample && intenttrace serve --host 0.0.0.0 --port ${PORT:-8787}"]
