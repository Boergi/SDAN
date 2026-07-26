ARG CADDY_PLUGINS=""

FROM caddy:2-builder AS builder

ARG CADDY_PLUGINS

# Build with caddy-security + any additional plugins
RUN --mount=type=cache,target=/root/.cache/go-build \
    xcaddy build \
    --with github.com/greenpau/caddy-security@v1.1.62 \
    ${CADDY_PLUGINS}

FROM caddy:2

COPY --from=builder /usr/bin/caddy /usr/bin/caddy