FROM rust:1.86-slim-bookworm AS builder
WORKDIR /app

COPY Cargo.toml Cargo.toml
COPY src src
COPY static static

RUN cargo build --release

FROM debian:bookworm-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/trade-bot-starter /usr/local/bin/trade-bot-starter
COPY static static

ENV APP_HOST=0.0.0.0
ENV APP_PORT=3000
ENV DATA_DIR=/data
ENV WATCHLIST=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT
ENV STARTING_CASH=10000
ENV PAPER_FEE_BPS=10
ENV DEFAULT_INTERVAL=1m

EXPOSE 3000

CMD ["trade-bot-starter"]
