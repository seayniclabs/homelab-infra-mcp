FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .
ENV TZ=America/Chicago
ENV HOMELAB_MCP_TRANSPORT=sse
ENV HOMELAB_MCP_PORT=8200
EXPOSE 8200
CMD ["python", "-m", "homelab_infra_mcp"]
