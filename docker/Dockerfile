FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src
ENV TZ=America/Chicago
ENV HOMELAB_MCP_TRANSPORT=sse
ENV HOMELAB_MCP_PORT=8200
EXPOSE 8200
CMD ["python", "-m", "homelab_infra_mcp"]
