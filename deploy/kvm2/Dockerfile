FROM wantcat/trendradar@sha256:3effcb5cedf5c385b50a6a32cd2599cbdbf54c9d8c52c0403406e356f88df80b

WORKDIR /app
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/naxiaoxin77/TrendRadar"
LABEL org.opencontainers.image.revision="$SOURCE_REVISION"

COPY pyproject.toml uv.lock ./
COPY trendradar/ ./trendradar/
COPY mcp_server/ ./mcp_server/
COPY docker/manage.py ./manage.py
COPY docker/entrypoint.sh /entrypoint.sh

RUN uv sync --frozen --no-dev \
    && sed -i 's/\r$//' /entrypoint.sh \
    && chmod +x /entrypoint.sh ./manage.py
