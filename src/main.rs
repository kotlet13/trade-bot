use std::{
    collections::HashMap,
    env, fmt, fs,
    path::Path,
    sync::{Arc, Mutex},
    time::Duration,
};

use axum::{
    extract::{Path as AxumPath, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Datelike, Timelike, Utc};
use quick_xml::de::from_str;
use reqwest::Client;
use rusqlite::{params, Connection, OptionalExtension, Transaction};
use serde::{Deserialize, Serialize};
use tokio::net::TcpListener;
use tower_http::{
    cors::{Any, CorsLayer},
    services::{ServeDir, ServeFile},
};

const BINANCE_DATA_API: &str = "https://data-api.binance.vision";
const BINANCE_FAPI_API: &str = "https://fapi.binance.com";
const DEFAULT_WATCHLIST: &str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,TONUSDT,ZECUSDT,TRXUSDT,SUIUSDT,ADAUSDT,AAVEUSDT,LINKUSDT,AXSUSDT,AVAXUSDT,LTCUSDT,APTUSDT,NEARUSDT,LDOUSDT,XLMUSDT,HBARUSDT,ARBUSDT,UNIUSDT,INJUSDT,DOTUSDT,BCHUSDT";
const DEFAULT_INTERVAL: &str = "1m";
const DEFAULT_STARTING_CASH: f64 = 10_000.0;
const DEFAULT_FEE_BPS: f64 = 10.0;
const DEFAULT_AUTO_PAPER_INTERVAL_SECONDS: u64 = 60;
const DEFAULT_AUTO_PAPER_MAX_OPEN_SLOTS: usize = 1;
const DEFAULT_AUTO_PAPER_MAX_DAILY_ENTRIES: usize = 3;
const DEFAULT_AUTO_PAPER_MAX_DAILY_LOSS_PERCENT: f64 = 2.0;
const DEFAULT_RUNTIME_TELEMETRY_INTERVAL_SECONDS: u64 = 900;
const DEFAULT_RUNTIME_TELEMETRY_CANDLE_LIMIT: usize = 240;
const DEFAULT_RUNTIME_TELEMETRY_FUNDING_LOOKBACK_HOURS: f64 = 72.0;
const TELEMETRY_CANDLE_INTERVALS: &[&str] = &["1m", "15m", "1h", "4h"];
const ACTIVE_PAPER_STRATEGY_VERSION: &str = "ai_score_v2_base_score7";
const SECONDARY_PAPER_STRATEGY_VERSION: &str = "ai_score_v2_ablate_oi";
const ACTIVE_PAPER_STRATEGY_MIN_SCORE: i32 = 7;
const ACTIVE_PAPER_STRATEGY_MIN_STOP_PCT: f64 = 0.004;
const ACTIVE_PAPER_STRATEGY_MAX_FEE_DRAG_R: f64 = 0.45;
const ACTIVE_PAPER_STRATEGY_FUNDING_MAX_AGE_HOURS: f64 = 12.0;
const ACTIVE_PAPER_STRATEGY_METRICS_MAX_AGE_MINUTES: f64 = 20.0;
const ACTIVE_PAPER_STRATEGY_BASKET_LOOKBACK_HOURS: f64 = 24.0;
const MAX_TRADES: usize = 200;
const SIGNAL_REPLAY_TRIGGER_LIMIT: usize = 720;
const SIGNAL_REPLAY_FORWARD_CANDLES: usize = 32;
const SIGNAL_REPLAY_BASE_CAPITAL: f64 = 10_000.0;
const BTC_REFERENCE_SYMBOL: &str = "BTCUSDT";
const SIGNAL_SESSION_START_HOUR_UTC: u32 = 7;
const SIGNAL_SESSION_END_HOUR_UTC: u32 = 22;
const SIGNAL_CORRELATION_LOOKBACK_RETURNS: usize = 96;
const SIGNAL_CORRELATION_MIN_SAMPLES: usize = 48;
const SIGNAL_CORRELATION_THRESHOLD: f64 = 0.88;
const SIGNAL_STALK_ATR_DISTANCE_MAX: f64 = 0.5;
const SIGNAL_RECLAIM_ATR_DISTANCE_MAX: f64 = 0.5;
const NEWS_CACHE_TTL_MINUTES: i64 = 5;
const NEWS_SCHEDULE_LOOKAHEAD_MINUTES: i64 = 15;
const NEWS_RELEASE_BLACKOUT_MINUTES: i64 = 60;
const NEWS_HEADLINE_BLACKOUT_MINUTES: i64 = 120;
const NEWS_SOFT_BLACKOUT_MINUTES: i64 = 90;
const BEA_RELEASE_SCHEDULE_URL: &str = "https://apps.bea.gov/API/signup/release_dates.json";
const FED_MONETARY_RSS_URL: &str = "https://www.federalreserve.gov/feeds/press_monetary.xml";
const SEC_PRESS_RSS_URL: &str = "https://www.sec.gov/news/pressreleases.rss";
const COINDESK_RSS_URL: &str = "https://www.coindesk.com/arc/outboundfeeds/rss";
const NO_DISABLED_SCORE_COMPONENTS: &[&str] = &[];
const OI_DISABLED_SCORE_COMPONENTS: &[&str] = &["oi"];

#[derive(Debug, Clone, Copy)]
struct PaperStrategy {
    version: &'static str,
    role: &'static str,
    min_score: i32,
    disabled_score_components: &'static [&'static str],
}

impl PaperStrategy {
    fn disables_score_component(self, component: &str) -> bool {
        self.disabled_score_components
            .iter()
            .any(|disabled| *disabled == component)
    }
}

const PRIMARY_PAPER_STRATEGY: PaperStrategy = PaperStrategy {
    version: ACTIVE_PAPER_STRATEGY_VERSION,
    role: "primary",
    min_score: ACTIVE_PAPER_STRATEGY_MIN_SCORE,
    disabled_score_components: NO_DISABLED_SCORE_COMPONENTS,
};

const SECONDARY_PAPER_STRATEGY: PaperStrategy = PaperStrategy {
    version: SECONDARY_PAPER_STRATEGY_VERSION,
    role: "secondary",
    min_score: ACTIVE_PAPER_STRATEGY_MIN_SCORE,
    disabled_score_components: OI_DISABLED_SCORE_COMPONENTS,
};

const APPROVED_PAPER_STRATEGIES: &[PaperStrategy] =
    &[PRIMARY_PAPER_STRATEGY, SECONDARY_PAPER_STRATEGY];

#[derive(Clone)]
struct AppState {
    client: Client,
    db: Arc<Mutex<Connection>>,
    watchlist: Vec<String>,
    default_interval: String,
    paper_fee_bps: f64,
    news_cache: Arc<Mutex<HashMap<String, CachedNewsStatus>>>,
    auto_paper: AutoPaperConfig,
    telemetry: RuntimeTelemetryConfig,
}

#[derive(Debug, Clone)]
struct AutoPaperConfig {
    enabled: bool,
    interval_seconds: u64,
    max_open_slots: usize,
    max_daily_entries: usize,
    max_daily_loss_percent: f64,
    allow_multi_strategy_same_signal: bool,
    prefer_secondary_on_score_tie: bool,
}

#[derive(Debug, Clone)]
struct RuntimeTelemetryConfig {
    enabled: bool,
    interval_seconds: u64,
    candle_limit: usize,
    futures_enabled: bool,
    signal_evaluations_enabled: bool,
}

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: message.into(),
        }
    }

    fn internal(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message: message.into(),
        }
    }

    fn upstream(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_GATEWAY,
            message: message.into(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = Json(ErrorPayload {
            error: self.message,
        });
        (self.status, body).into_response()
    }
}

impl fmt::Display for ApiError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.message)
    }
}

impl std::error::Error for ApiError {}

impl From<rusqlite::Error> for ApiError {
    fn from(error: rusqlite::Error) -> Self {
        ApiError::internal(format!("Database error: {error}"))
    }
}

#[derive(Serialize)]
struct ErrorPayload {
    error: String,
}

#[derive(Debug, Deserialize)]
struct DashboardQuery {
    symbol: Option<String>,
    interval: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ReplayQuery {
    symbol: Option<String>,
}

#[derive(Debug, Deserialize)]
struct OrderRequest {
    symbol: String,
    side: OrderSide,
    order_kind: OrderKind,
    quantity: f64,
    limit_price: Option<f64>,
    stop_loss: Option<f64>,
    take_profit: Option<f64>,
    note: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CancelOrderRequest {
    reason: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
enum OrderSide {
    Buy,
    Sell,
}

impl OrderSide {
    fn as_str(self) -> &'static str {
        match self {
            Self::Buy => "BUY",
            Self::Sell => "SELL",
        }
    }
}

#[derive(Debug, Deserialize, Serialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
enum OrderKind {
    Market,
    Limit,
}

#[derive(Debug)]
struct AccountRecord {
    initial_cash: f64,
    cash_balance: f64,
    fee_bps: f64,
    realized_pnl: f64,
}

#[derive(Debug)]
struct DbPosition {
    symbol: String,
    quantity: f64,
    avg_price: f64,
    stop_loss: Option<f64>,
    take_profit: Option<f64>,
    note: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
struct Trade {
    id: i64,
    symbol: String,
    side: String,
    quantity: f64,
    price: f64,
    gross_value: f64,
    fee_paid: f64,
    realized_pnl: f64,
    note: Option<String>,
    source: String,
    source_order_id: Option<i64>,
    executed_at: i64,
}

#[derive(Debug, Serialize, Clone)]
struct OpenOrder {
    id: i64,
    symbol: String,
    side: String,
    order_kind: String,
    quantity: f64,
    limit_price: Option<f64>,
    stop_loss: Option<f64>,
    take_profit: Option<f64>,
    note: Option<String>,
    created_at: i64,
}

#[derive(Debug, Serialize)]
struct DashboardResponse {
    watchlist: Vec<String>,
    selected_symbol: String,
    interval: String,
    updated_at: i64,
    tickers: Vec<TickerSummary>,
    candles: Vec<Candle>,
    paper: PaperSnapshot,
    signal_assistant: SignalAssistant,
    secondary_signal_assistants: Vec<SignalAssistant>,
}

#[derive(Debug, Serialize)]
struct ReplayResponse {
    symbol: String,
    generated_at: i64,
    lookback_trigger_candles: usize,
    forward_trigger_candles: usize,
    ready_signals: usize,
    setup_signals: usize,
    tp1_hits: usize,
    tp2_hits: usize,
    stop_losses: usize,
    breakeven_exits: usize,
    timeout_exits: usize,
    win_rate_percent: f64,
    average_r: f64,
    total_r: f64,
    notes: Vec<String>,
    recent_trades: Vec<ReplayTradeSample>,
}

#[derive(Debug, Serialize)]
struct ReplayTradeSample {
    opened_at: i64,
    closed_at: i64,
    outcome: ReplayOutcome,
    entry: f64,
    stop_loss: f64,
    take_profit_1: f64,
    take_profit_2: f64,
    realized_r: f64,
    bars_held: usize,
    confidence: u8,
}

#[derive(Debug, Serialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum ReplayOutcome {
    StopLoss,
    TakeProfit2,
    Breakeven,
    Timeout,
}

#[derive(Debug, Serialize)]
struct PaperSnapshot {
    initial_cash: f64,
    cash_balance: f64,
    fee_bps: f64,
    realized_pnl: f64,
    positions: Vec<PositionSnapshot>,
    trades: Vec<Trade>,
    open_orders: Vec<OpenOrder>,
    summary: PaperSummary,
}

#[derive(Debug, Serialize)]
struct PositionSnapshot {
    symbol: String,
    quantity: f64,
    avg_price: f64,
    current_price: f64,
    market_value: f64,
    unrealized_pnl: f64,
    stop_loss: Option<f64>,
    take_profit: Option<f64>,
    note: Option<String>,
}

#[derive(Debug, Serialize)]
struct PaperSummary {
    equity: f64,
    positions_value: f64,
    unrealized_pnl: f64,
    total_pnl: f64,
    trade_count: usize,
    open_order_count: usize,
}

#[derive(Debug, Serialize)]
struct SignalAssistant {
    symbol: String,
    strategy_version: &'static str,
    bias: SignalBias,
    stage: SignalStage,
    technical_stage: SignalStage,
    confidence: u8,
    ai_score: i32,
    summary: String,
    generated_at: i64,
    signal_close_time: i64,
    timeframes: SignalTimeframes,
    checklist: Vec<SignalCheck>,
    risk_plan: Option<SignalRiskPlan>,
    warnings: Vec<String>,
    journal_tags: Vec<String>,
}

#[derive(Debug, Serialize)]
struct SignalTimeframes {
    trend: &'static str,
    setup: &'static str,
    trigger: &'static str,
}

#[derive(Debug, Serialize)]
struct SignalCheck {
    label: String,
    passed: bool,
    detail: String,
}

#[derive(Debug)]
struct AiScorecardEvaluation {
    score: i32,
    components: Vec<SignalCheck>,
    blockers: Vec<String>,
    warnings: Vec<String>,
}

#[derive(Debug)]
struct ScorecardContext {
    funding_bps: Option<(f64, i64)>,
    metrics: Option<FuturesMetricSnapshot>,
    basket: Option<BasketSnapshot>,
    warnings: Vec<String>,
}

impl ScorecardContext {
    fn empty() -> Self {
        Self {
            funding_bps: None,
            metrics: None,
            basket: None,
            warnings: Vec::new(),
        }
    }
}

#[derive(Debug)]
struct FuturesMetricSnapshot {
    timestamp: i64,
    taker_buy_sell_ratio: f64,
    global_account_long_short_ratio: f64,
    top_trader_position_long_short_ratio: f64,
    open_interest_24h_change_pct: Option<f64>,
}

#[derive(Debug)]
struct BasketSnapshot {
    relative_strength_percentile: Option<f64>,
    positive_share_pct: Option<f64>,
    sample_size: usize,
}

#[derive(Debug, Serialize, Clone)]
struct SignalRiskPlan {
    entry: f64,
    stop_loss: f64,
    take_profit_1: f64,
    take_profit_2: f64,
    risk_per_unit: f64,
    risk_amount: f64,
    suggested_quantity: f64,
    notional_estimate: f64,
    capital_at_risk_percent: f64,
}

#[derive(Debug)]
struct EvaluatedSignal {
    bias: SignalBias,
    stage: SignalStage,
    confidence: u8,
    trend: StructureSnapshot,
    support_level: Option<f64>,
    distance_to_support: Option<f64>,
    trigger: TriggerSnapshot,
    risk_plan: Option<SignalRiskPlan>,
    cash_capped: bool,
}

#[derive(Debug)]
struct SessionFilterStatus {
    passed: bool,
    detail: String,
}

#[derive(Debug)]
struct CorrelationFilterStatus {
    passed: bool,
    detail: String,
}

#[derive(Debug, Clone)]
struct NewsFilterStatus {
    passed: bool,
    detail: String,
    warnings: Vec<String>,
}

#[derive(Debug, Clone)]
struct CachedNewsStatus {
    fetched_at: i64,
    status: NewsFilterStatus,
}

#[derive(Debug, Serialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum SignalBias {
    Bullish,
    Neutral,
    Bearish,
}

impl SignalBias {
    fn as_label(self) -> &'static str {
        match self {
            Self::Bullish => "bullish",
            Self::Neutral => "neutral",
            Self::Bearish => "bearish",
        }
    }
}

#[derive(Debug, Serialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum SignalStage {
    Wait,
    Stalk,
    Setup,
    Ready,
}

impl SignalStage {
    fn as_label(self) -> &'static str {
        match self {
            Self::Wait => "WAIT",
            Self::Stalk => "STALK",
            Self::Setup => "SETUP",
            Self::Ready => "READY",
        }
    }
}

#[derive(Debug)]
struct StructureSnapshot {
    bias: SignalBias,
    last_pivot_high: Option<f64>,
    previous_pivot_high: Option<f64>,
    last_pivot_low: Option<f64>,
    previous_pivot_low: Option<f64>,
    slope_up: bool,
}

#[derive(Debug, Serialize)]
struct OrderSubmissionResponse {
    outcome: String,
    message: String,
    trade: Option<Trade>,
    order: Option<OpenOrder>,
}

#[derive(Debug, Serialize)]
struct TickerSummary {
    symbol: String,
    last_price: f64,
    price_change_percent: f64,
    high_price: f64,
    low_price: f64,
    volume: f64,
    quote_volume: f64,
}

#[derive(Debug, Serialize)]
struct Candle {
    open_time: i64,
    open: f64,
    high: f64,
    low: f64,
    close: f64,
    volume: f64,
}

#[derive(Debug, Deserialize)]
struct RssDocument {
    channel: RssChannel,
}

#[derive(Debug, Deserialize)]
struct RssChannel {
    #[serde(default)]
    item: Vec<RssItem>,
}

#[derive(Debug, Deserialize)]
struct RssItem {
    title: Option<String>,
    #[serde(rename = "pubDate")]
    pub_date: Option<String>,
}

#[derive(Debug, Deserialize)]
struct BeaReleaseSeries {
    #[serde(default)]
    release_dates: Vec<String>,
}

#[derive(Debug, Clone)]
struct NewsHeadline {
    title: String,
    published_at: i64,
}

#[derive(Debug, Deserialize)]
struct BinanceTicker {
    symbol: String,
    #[serde(rename = "lastPrice")]
    last_price: String,
    #[serde(rename = "priceChangePercent")]
    price_change_percent: String,
    #[serde(rename = "highPrice")]
    high_price: String,
    #[serde(rename = "lowPrice")]
    low_price: String,
    volume: String,
    #[serde(rename = "quoteVolume")]
    quote_volume: String,
}

#[derive(Debug, Deserialize)]
struct BinancePriceTicker {
    symbol: String,
    price: String,
}

#[derive(Debug, Deserialize)]
struct BinanceFundingRate {
    symbol: String,
    #[serde(rename = "fundingTime")]
    funding_time: serde_json::Value,
    #[serde(rename = "fundingRate")]
    funding_rate: String,
    #[serde(rename = "markPrice")]
    mark_price: Option<String>,
}

#[derive(Debug, Deserialize, Clone)]
struct BinanceOpenInterestHist {
    #[serde(rename = "sumOpenInterest")]
    sum_open_interest: Option<String>,
    #[serde(rename = "sumOpenInterestValue")]
    sum_open_interest_value: String,
    timestamp: serde_json::Value,
}

#[derive(Debug, Deserialize, Clone)]
struct BinanceRatioRow {
    #[serde(rename = "longShortRatio")]
    long_short_ratio: Option<String>,
    #[serde(rename = "buySellRatio")]
    buy_sell_ratio: Option<String>,
    timestamp: serde_json::Value,
}

#[derive(Debug)]
struct AutoPaperCycleStats {
    active_slots: usize,
    daily_entries: usize,
    daily_realized_pnl: f64,
    initial_cash: f64,
    cash_balance: f64,
    fee_bps: f64,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let host = env::var("APP_HOST").unwrap_or_else(|_| "0.0.0.0".to_string());
    let port: u16 = env::var("APP_PORT")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(3000);
    let default_interval =
        env::var("DEFAULT_INTERVAL").unwrap_or_else(|_| DEFAULT_INTERVAL.to_string());
    let watchlist =
        parse_watchlist(env::var("WATCHLIST").unwrap_or_else(|_| DEFAULT_WATCHLIST.to_string()));
    let starting_cash = env::var("STARTING_CASH")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(DEFAULT_STARTING_CASH);
    let fee_bps = env::var("PAPER_FEE_BPS")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(DEFAULT_FEE_BPS);
    let auto_paper = AutoPaperConfig {
        enabled: env_bool("AUTO_PAPER_TRADING", false),
        interval_seconds: env::var("AUTO_PAPER_INTERVAL_SECONDS")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_AUTO_PAPER_INTERVAL_SECONDS)
            .max(15),
        max_open_slots: env::var("AUTO_PAPER_MAX_OPEN_SLOTS")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_AUTO_PAPER_MAX_OPEN_SLOTS)
            .max(1),
        max_daily_entries: env::var("AUTO_PAPER_MAX_DAILY_ENTRIES")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_AUTO_PAPER_MAX_DAILY_ENTRIES)
            .max(1),
        max_daily_loss_percent: env::var("AUTO_PAPER_MAX_DAILY_LOSS_PERCENT")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_AUTO_PAPER_MAX_DAILY_LOSS_PERCENT)
            .max(0.1),
        allow_multi_strategy_same_signal: env_bool(
            "AUTO_PAPER_ALLOW_MULTI_STRATEGY_SAME_SIGNAL",
            false,
        ),
        prefer_secondary_on_score_tie: env_bool("AUTO_PAPER_PREFER_SECONDARY_ON_SCORE_TIE", false),
    };
    let telemetry = RuntimeTelemetryConfig {
        enabled: env_bool("RUNTIME_TELEMETRY_ENABLED", true),
        interval_seconds: env::var("RUNTIME_TELEMETRY_INTERVAL_SECONDS")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_RUNTIME_TELEMETRY_INTERVAL_SECONDS)
            .max(60),
        candle_limit: env::var("RUNTIME_TELEMETRY_CANDLE_LIMIT")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_RUNTIME_TELEMETRY_CANDLE_LIMIT)
            .clamp(10, 1000),
        futures_enabled: env_bool("RUNTIME_TELEMETRY_FUTURES_ENABLED", true),
        signal_evaluations_enabled: env_bool("RUNTIME_TELEMETRY_SIGNAL_EVALUATIONS", true),
    };
    let data_dir = env::var("DATA_DIR").unwrap_or_else(|_| "./data".to_string());
    let db_path = Path::new(&data_dir).join("tradebot.db");

    fs::create_dir_all(&data_dir)?;

    let mut connection = Connection::open(db_path)?;
    initialize_database(&mut connection, starting_cash, fee_bps)?;

    let shared_state = AppState {
        client: Client::builder()
            .user_agent("trade-bot-starter/0.2.0")
            .build()?,
        db: Arc::new(Mutex::new(connection)),
        watchlist,
        default_interval,
        paper_fee_bps: fee_bps,
        news_cache: Arc::new(Mutex::new(HashMap::new())),
        auto_paper,
        telemetry,
    };

    if shared_state.telemetry.enabled {
        let telemetry_state = shared_state.clone();
        tokio::spawn(async move {
            runtime_telemetry_worker(telemetry_state).await;
        });
    }

    if shared_state.auto_paper.enabled {
        let auto_state = shared_state.clone();
        tokio::spawn(async move {
            auto_paper_worker(auto_state).await;
        });
    }

    let static_files =
        ServeDir::new("static").not_found_service(ServeFile::new("static/index.html"));
    let cors = CorsLayer::new()
        .allow_methods(Any)
        .allow_headers(Any)
        .allow_origin(Any);

    let app = Router::new()
        .route("/health", get(health))
        .route("/api/dashboard", get(get_dashboard))
        .route("/api/replay", get(get_signal_replay))
        .route("/api/paper/orders", post(create_paper_order))
        .route("/api/paper/orders/:id/cancel", post(cancel_paper_order))
        .route("/api/paper/reset", post(reset_paper_account))
        .fallback_service(static_files)
        .layer(cors)
        .with_state(shared_state);

    let listener = TcpListener::bind((host.as_str(), port)).await?;
    println!("trade-bot-starter running on http://{}:{port}", host);
    axum::serve(listener, app).await?;

    Ok(())
}

async fn health() -> &'static str {
    "ok"
}

async fn get_dashboard(
    State(state): State<AppState>,
    Query(query): Query<DashboardQuery>,
) -> Result<Json<DashboardResponse>, ApiError> {
    let now = Utc::now().timestamp_millis();
    let symbol = pick_symbol(&state.watchlist, query.symbol)?;
    let interval = query
        .interval
        .unwrap_or_else(|| state.default_interval.clone());
    validate_interval(&interval)?;

    let tickers = fetch_tickers(&state.client, &state.watchlist).await?;
    let candles = fetch_candles(&state.client, &symbol, &interval, 120).await?;
    persist_market_tickers_if_enabled(&state, &tickers, now);
    persist_candles_if_enabled(&state, &symbol, &interval, &candles, now);
    let prices: HashMap<String, f64> = tickers
        .iter()
        .map(|ticker| (ticker.symbol.clone(), ticker.last_price))
        .collect();

    let paper = {
        let mut db = state
            .db
            .lock()
            .map_err(|_| ApiError::internal("Paper database lock is poisoned."))?;
        process_price_events(&mut db, &prices, now)?;
        load_paper_snapshot(&db, &prices)?
    };
    let current_price = prices
        .get(&symbol)
        .copied()
        .or_else(|| candles.last().map(|candle| candle.close))
        .unwrap_or_default();
    let mut signal_assistants = match build_signal_assistants(
        &state.client,
        &state.news_cache,
        &state.watchlist,
        &symbol,
        current_price,
        paper.cash_balance,
        paper.fee_bps,
        now,
        APPROVED_PAPER_STRATEGIES,
    )
    .await
    {
        Ok(signals) => signals,
        Err(error) => APPROVED_PAPER_STRATEGIES
            .iter()
            .map(|strategy| {
                unavailable_signal_assistant(*strategy, &symbol, now, error.message.clone())
            })
            .collect(),
    };
    persist_signal_evaluations_if_enabled(&state, &signal_assistants, now);
    let signal_assistant = if signal_assistants.is_empty() {
        unavailable_signal_assistant(
            PRIMARY_PAPER_STRATEGY,
            &symbol,
            now,
            "No paper strategies are configured.".to_string(),
        )
    } else {
        signal_assistants.remove(0)
    };
    let secondary_signal_assistants = signal_assistants;

    Ok(Json(DashboardResponse {
        watchlist: state.watchlist.clone(),
        selected_symbol: symbol,
        interval,
        updated_at: now,
        tickers,
        candles,
        paper,
        signal_assistant,
        secondary_signal_assistants,
    }))
}

async fn get_signal_replay(
    State(state): State<AppState>,
    Query(query): Query<ReplayQuery>,
) -> Result<Json<ReplayResponse>, ApiError> {
    let symbol = pick_symbol(&state.watchlist, query.symbol)?;
    let replay = build_signal_replay(
        &state.client,
        &symbol,
        state.paper_fee_bps,
        Utc::now().timestamp_millis(),
    )
    .await?;
    Ok(Json(replay))
}

async fn create_paper_order(
    State(state): State<AppState>,
    Json(payload): Json<OrderRequest>,
) -> Result<Json<OrderSubmissionResponse>, ApiError> {
    let symbol = pick_symbol(&state.watchlist, Some(payload.symbol.clone()))?;
    let current_price = fetch_last_price(&state.client, &symbol).await?;
    validate_order_request(&payload, current_price)?;
    let note = sanitize_note(payload.note.clone());
    let submitted_at = Utc::now().timestamp_millis();

    let mut db = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))?;

    let response = match payload.order_kind {
        OrderKind::Market => {
            let mut execution_quantity = payload.quantity;
            let mut quantity_adjustment = None;
            if matches!(payload.side, OrderSide::Buy) {
                let account = fetch_account(&db)?;
                let affordable_quantity =
                    max_affordable_quantity(account.cash_balance, current_price, account.fee_bps);
                if affordable_quantity <= 0.0 {
                    return Err(ApiError::bad_request(
                        "Not enough paper cash for a market order at the current price.",
                    ));
                }
                if execution_quantity > affordable_quantity + 1e-9 {
                    quantity_adjustment = Some((execution_quantity, affordable_quantity));
                    execution_quantity = affordable_quantity;
                }
            }

            let trade = execute_trade(
                &mut db,
                TradeExecution {
                    symbol,
                    side: payload.side,
                    quantity: execution_quantity,
                    price: current_price,
                    note,
                    source: "MANUAL_MARKET".to_string(),
                    source_order_id: None,
                    attached_stop_loss: payload.stop_loss,
                    attached_take_profit: payload.take_profit,
                    executed_at: submitted_at,
                },
            )?;

            OrderSubmissionResponse {
                outcome: "filled".to_string(),
                message: match quantity_adjustment {
                    Some((requested_quantity, filled_quantity)) => format!(
                        "{} {} @ {:.4} executed as a paper market trade. Quantity was reduced from {:.6} to {:.6} because the live price moved before execution.",
                        trade.side, trade.symbol, trade.price, requested_quantity, filled_quantity
                    ),
                    None => format!(
                        "{} {} @ {:.4} executed as a paper market trade.",
                        trade.side, trade.symbol, trade.price
                    ),
                },
                trade: Some(trade),
                order: None,
            }
        }
        OrderKind::Limit => {
            let order_id = insert_open_order(
                &mut db,
                &symbol,
                payload.side,
                payload.quantity,
                payload.limit_price,
                payload.stop_loss,
                payload.take_profit,
                note,
                submitted_at,
            )?;

            let prices = HashMap::from([(symbol.clone(), current_price)]);
            process_price_events(&mut db, &prices, submitted_at)?;
            let order_status = fetch_order_status(&db, order_id)?;

            match order_status {
                Some(OpenOrderStatus::Open(order)) => OrderSubmissionResponse {
                    outcome: "open".to_string(),
                    message: format!(
                        "{} {} limit order is waiting at {:.4}.",
                        order.side,
                        order.symbol,
                        order.limit_price.unwrap_or_default()
                    ),
                    trade: None,
                    order: Some(order),
                },
                Some(OpenOrderStatus::Filled(trade)) => OrderSubmissionResponse {
                    outcome: "filled".to_string(),
                    message: format!(
                        "{} {} limit order filled at {:.4}.",
                        trade.side, trade.symbol, trade.price
                    ),
                    trade: Some(trade),
                    order: None,
                },
                Some(OpenOrderStatus::Cancelled(reason)) => OrderSubmissionResponse {
                    outcome: "cancelled".to_string(),
                    message: reason,
                    trade: None,
                    order: None,
                },
                None => {
                    return Err(ApiError::internal(
                        "New limit order was created but could not be loaded back.",
                    ))
                }
            }
        }
    };

    Ok(Json(response))
}

async fn cancel_paper_order(
    State(state): State<AppState>,
    AxumPath(order_id): AxumPath<i64>,
    Json(payload): Json<CancelOrderRequest>,
) -> Result<StatusCode, ApiError> {
    let reason = sanitize_note(payload.reason)
        .unwrap_or_else(|| "Cancelled manually from the dashboard.".to_string());

    let db = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))?;

    let changed = db.execute(
        "UPDATE orders
         SET status = 'CANCELLED', cancelled_reason = ?1, cancelled_at = ?2
         WHERE id = ?3 AND status = 'OPEN'",
        params![reason, Utc::now().timestamp_millis(), order_id],
    )?;

    if changed == 0 {
        return Err(ApiError::bad_request(
            "Open order was not found or it is already closed.",
        ));
    }

    Ok(StatusCode::NO_CONTENT)
}

async fn reset_paper_account(State(state): State<AppState>) -> Result<StatusCode, ApiError> {
    let mut db = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))?;
    reset_database(&mut db)?;
    Ok(StatusCode::NO_CONTENT)
}

fn parse_watchlist(raw: String) -> Vec<String> {
    let mut symbols: Vec<String> = raw
        .split(',')
        .map(|value| value.trim().to_uppercase())
        .filter(|value| !value.is_empty())
        .collect();

    if symbols.is_empty() {
        symbols = DEFAULT_WATCHLIST
            .split(',')
            .map(|value| value.to_string())
            .collect();
    }

    symbols
}

fn env_bool(name: &str, default: bool) -> bool {
    env::var(name)
        .ok()
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(default)
}

fn pick_symbol(watchlist: &[String], requested: Option<String>) -> Result<String, ApiError> {
    let candidate = requested
        .unwrap_or_else(|| {
            watchlist
                .first()
                .cloned()
                .unwrap_or_else(|| "BTCUSDT".to_string())
        })
        .trim()
        .to_uppercase();

    if watchlist.iter().any(|symbol| symbol == &candidate) {
        Ok(candidate)
    } else {
        Err(ApiError::bad_request(format!(
            "Symbol {candidate} is not in the configured watchlist."
        )))
    }
}

fn validate_interval(interval: &str) -> Result<(), ApiError> {
    let allowed = ["1m", "5m", "15m", "1h", "4h"];
    if allowed.contains(&interval) {
        Ok(())
    } else {
        Err(ApiError::bad_request(
            "Unsupported interval. Use 1m, 5m, 15m, 1h or 4h.",
        ))
    }
}

fn validate_order_request(payload: &OrderRequest, current_price: f64) -> Result<(), ApiError> {
    if !payload.quantity.is_finite() || payload.quantity <= 0.0 {
        return Err(ApiError::bad_request("Quantity must be a positive number."));
    }

    if matches!(payload.order_kind, OrderKind::Limit) {
        let limit_price = payload
            .limit_price
            .ok_or_else(|| ApiError::bad_request("Limit orders require a limit price."))?;
        if !limit_price.is_finite() || limit_price <= 0.0 {
            return Err(ApiError::bad_request(
                "Limit price must be a positive number.",
            ));
        }
    }

    if matches!(payload.side, OrderSide::Sell)
        && (payload.stop_loss.is_some() || payload.take_profit.is_some())
    {
        return Err(ApiError::bad_request(
            "Stop-loss and take-profit are only attached to buy entries in this version.",
        ));
    }

    let reference_price = match payload.order_kind {
        OrderKind::Market => current_price,
        OrderKind::Limit => payload.limit_price.unwrap_or(current_price),
    };

    if let Some(stop_loss) = payload.stop_loss {
        if !stop_loss.is_finite() || stop_loss <= 0.0 {
            return Err(ApiError::bad_request(
                "Stop-loss must be a positive number.",
            ));
        }
        if stop_loss >= reference_price {
            return Err(ApiError::bad_request(
                "Stop-loss must be below the entry price for long paper trades.",
            ));
        }
    }

    if let Some(take_profit) = payload.take_profit {
        if !take_profit.is_finite() || take_profit <= 0.0 {
            return Err(ApiError::bad_request(
                "Take-profit must be a positive number.",
            ));
        }
        if take_profit <= reference_price {
            return Err(ApiError::bad_request(
                "Take-profit must be above the entry price for long paper trades.",
            ));
        }
    }

    Ok(())
}

fn sanitize_note(note: Option<String>) -> Option<String> {
    note.and_then(|value| {
        let trimmed = value.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    })
}

fn initialize_database(
    connection: &mut Connection,
    starting_cash: f64,
    fee_bps: f64,
) -> Result<(), ApiError> {
    connection.busy_timeout(Duration::from_secs(5))?;
    connection.execute_batch(
        "
        PRAGMA journal_mode = DELETE;
        PRAGMA synchronous = NORMAL;

        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            initial_cash REAL NOT NULL,
            cash_balance REAL NOT NULL,
            fee_bps REAL NOT NULL,
            realized_pnl REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL NOT NULL,
            avg_price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            note TEXT,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            gross_value REAL NOT NULL,
            fee_paid REAL NOT NULL,
            realized_pnl REAL NOT NULL,
            note TEXT,
            source TEXT NOT NULL,
            source_order_id INTEGER,
            executed_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_kind TEXT NOT NULL,
            quantity REAL NOT NULL,
            limit_price REAL,
            status TEXT NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            note TEXT,
            cancelled_reason TEXT,
            created_at INTEGER NOT NULL,
            filled_at INTEGER,
            cancelled_at INTEGER,
            fill_price REAL
        );

        CREATE INDEX IF NOT EXISTS idx_orders_status_created_at
            ON orders(status, created_at);

        CREATE TABLE IF NOT EXISTS auto_paper_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_version TEXT NOT NULL,
            symbol TEXT NOT NULL,
            signal_close_time INTEGER NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT,
            ai_score INTEGER,
            stage TEXT,
            created_at INTEGER NOT NULL,
            trade_id INTEGER,
            entry_price REAL,
            stop_loss REAL,
            take_profit REAL,
            quantity REAL,
            risk_per_unit REAL,
            risk_amount REAL,
            UNIQUE(strategy_version, symbol, signal_close_time)
        );

        CREATE INDEX IF NOT EXISTS idx_auto_paper_decisions_created_at
            ON auto_paper_decisions(created_at);

        CREATE TABLE IF NOT EXISTS telemetry_market_tickers (
            symbol TEXT NOT NULL,
            snapshot_time INTEGER NOT NULL,
            last_price REAL NOT NULL,
            price_change_percent REAL NOT NULL,
            high_price REAL NOT NULL,
            low_price REAL NOT NULL,
            volume REAL NOT NULL,
            quote_volume REAL NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(symbol, snapshot_time)
        );

        CREATE INDEX IF NOT EXISTS idx_telemetry_market_tickers_snapshot_time
            ON telemetry_market_tickers(snapshot_time);

        CREATE TABLE IF NOT EXISTS telemetry_candles (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            fetched_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(symbol, interval, open_time)
        );

        CREATE INDEX IF NOT EXISTS idx_telemetry_candles_symbol_interval_time
            ON telemetry_candles(symbol, interval, open_time);

        CREATE TABLE IF NOT EXISTS telemetry_funding_rates (
            symbol TEXT NOT NULL,
            funding_time INTEGER NOT NULL,
            funding_rate_bps REAL NOT NULL,
            mark_price REAL,
            fetched_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(symbol, funding_time)
        );

        CREATE INDEX IF NOT EXISTS idx_telemetry_funding_rates_time
            ON telemetry_funding_rates(funding_time);

        CREATE TABLE IF NOT EXISTS telemetry_futures_metric_rows (
            symbol TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            period TEXT NOT NULL,
            long_short_ratio REAL,
            buy_sell_ratio REAL,
            sum_open_interest REAL,
            sum_open_interest_value REAL,
            fetched_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(symbol, metric_name, timestamp)
        );

        CREATE INDEX IF NOT EXISTS idx_telemetry_futures_metric_rows_time
            ON telemetry_futures_metric_rows(metric_name, timestamp);

        CREATE TABLE IF NOT EXISTS telemetry_signal_evaluations (
            strategy_version TEXT NOT NULL,
            symbol TEXT NOT NULL,
            signal_close_time INTEGER NOT NULL,
            generated_at INTEGER NOT NULL,
            captured_at INTEGER NOT NULL,
            stage TEXT NOT NULL,
            technical_stage TEXT NOT NULL,
            bias TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            ai_score INTEGER NOT NULL,
            summary TEXT NOT NULL,
            has_risk_plan INTEGER NOT NULL,
            entry_price REAL,
            stop_loss REAL,
            take_profit_1 REAL,
            take_profit_2 REAL,
            suggested_quantity REAL,
            risk_amount REAL,
            failed_checks_json TEXT NOT NULL,
            checklist_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            journal_tags_json TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(strategy_version, symbol, signal_close_time)
        );

        CREATE INDEX IF NOT EXISTS idx_telemetry_signal_evaluations_generated_at
            ON telemetry_signal_evaluations(generated_at);

        CREATE TABLE IF NOT EXISTS telemetry_news_events (
            event_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_url TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            published_at INTEGER,
            fetched_at INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            severity INTEGER NOT NULL,
            confidence REAL NOT NULL,
            symbols_json TEXT NOT NULL,
            bases_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            summary TEXT,
            classification_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_telemetry_news_events_published_at
            ON telemetry_news_events(published_at);

        CREATE INDEX IF NOT EXISTS idx_telemetry_news_events_event_type
            ON telemetry_news_events(event_type);
        ",
    )?;
    ensure_column(connection, "auto_paper_decisions", "entry_price", "REAL")?;
    ensure_column(connection, "auto_paper_decisions", "stop_loss", "REAL")?;
    ensure_column(connection, "auto_paper_decisions", "take_profit", "REAL")?;
    ensure_column(connection, "auto_paper_decisions", "quantity", "REAL")?;
    ensure_column(connection, "auto_paper_decisions", "risk_per_unit", "REAL")?;
    ensure_column(connection, "auto_paper_decisions", "risk_amount", "REAL")?;

    let account_exists: Option<i64> = connection
        .query_row("SELECT id FROM account WHERE id = 1", [], |row| row.get(0))
        .optional()?;

    if account_exists.is_none() {
        connection.execute(
            "INSERT INTO account (id, initial_cash, cash_balance, fee_bps, realized_pnl)
             VALUES (1, ?1, ?2, ?3, 0.0)",
            params![starting_cash, starting_cash, fee_bps],
        )?;
    }

    Ok(())
}

fn reset_database(connection: &mut Connection) -> Result<(), ApiError> {
    let (initial_cash, fee_bps): (f64, f64) = connection.query_row(
        "SELECT initial_cash, fee_bps FROM account WHERE id = 1",
        [],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;

    let tx = connection.transaction()?;
    tx.execute("DELETE FROM positions", [])?;
    tx.execute("DELETE FROM trades", [])?;
    tx.execute("DELETE FROM orders", [])?;
    tx.execute("DELETE FROM auto_paper_decisions", [])?;
    tx.execute(
        "UPDATE account
         SET cash_balance = ?1, realized_pnl = 0.0, fee_bps = ?2
         WHERE id = 1",
        params![initial_cash, fee_bps],
    )?;
    tx.commit()?;

    Ok(())
}

fn ensure_column(
    connection: &Connection,
    table: &str,
    column: &str,
    definition: &str,
) -> Result<(), ApiError> {
    let mut statement = connection.prepare(&format!("PRAGMA table_info({table})"))?;
    let rows = statement.query_map([], |row| row.get::<_, String>(1))?;
    let columns = rows.collect::<Result<Vec<_>, _>>()?;
    if !columns.iter().any(|name| name == column) {
        connection.execute(
            &format!("ALTER TABLE {table} ADD COLUMN {column} {definition}"),
            [],
        )?;
    }
    Ok(())
}

fn fetch_account(connection: &Connection) -> Result<AccountRecord, ApiError> {
    connection
        .query_row(
            "SELECT initial_cash, cash_balance, fee_bps, realized_pnl
             FROM account WHERE id = 1",
            [],
            |row| {
                Ok(AccountRecord {
                    initial_cash: row.get(0)?,
                    cash_balance: row.get(1)?,
                    fee_bps: row.get(2)?,
                    realized_pnl: row.get(3)?,
                })
            },
        )
        .map_err(ApiError::from)
}

fn load_paper_snapshot(
    connection: &Connection,
    prices: &HashMap<String, f64>,
) -> Result<PaperSnapshot, ApiError> {
    let account = fetch_account(connection)?;

    let mut positions_statement = connection.prepare(
        "SELECT symbol, quantity, avg_price, stop_loss, take_profit, note
         FROM positions ORDER BY symbol ASC",
    )?;

    let positions_rows = positions_statement.query_map([], |row| {
        Ok(DbPosition {
            symbol: row.get(0)?,
            quantity: row.get(1)?,
            avg_price: row.get(2)?,
            stop_loss: row.get(3)?,
            take_profit: row.get(4)?,
            note: row.get(5)?,
        })
    })?;

    let mut positions = Vec::new();
    for row in positions_rows {
        let item = row?;
        let current_price = prices.get(&item.symbol).copied().unwrap_or(0.0);
        let market_value = current_price * item.quantity;
        let cost_basis = item.avg_price * item.quantity;
        positions.push(PositionSnapshot {
            symbol: item.symbol,
            quantity: item.quantity,
            avg_price: item.avg_price,
            current_price,
            market_value,
            unrealized_pnl: market_value - cost_basis,
            stop_loss: item.stop_loss,
            take_profit: item.take_profit,
            note: item.note,
        });
    }

    let mut orders_statement = connection.prepare(
        "SELECT id, symbol, side, order_kind, quantity, limit_price, stop_loss,
                take_profit, note, created_at
         FROM orders
         WHERE status = 'OPEN'
         ORDER BY created_at DESC",
    )?;

    let order_rows = orders_statement.query_map([], |row| {
        Ok(OpenOrder {
            id: row.get(0)?,
            symbol: row.get(1)?,
            side: row.get(2)?,
            order_kind: row.get(3)?,
            quantity: row.get(4)?,
            limit_price: row.get(5)?,
            stop_loss: row.get(6)?,
            take_profit: row.get(7)?,
            note: row.get(8)?,
            created_at: row.get(9)?,
        })
    })?;

    let open_orders: Vec<OpenOrder> = order_rows.collect::<Result<Vec<_>, _>>()?;
    let open_order_count = open_orders.len();

    let mut trades_statement = connection.prepare(
        "SELECT id, symbol, side, quantity, price, gross_value, fee_paid,
                realized_pnl, note, source, source_order_id, executed_at
         FROM trades
         ORDER BY executed_at DESC
         LIMIT ?1",
    )?;

    let trade_rows = trades_statement.query_map(params![MAX_TRADES as i64], |row| {
        Ok(Trade {
            id: row.get(0)?,
            symbol: row.get(1)?,
            side: row.get(2)?,
            quantity: row.get(3)?,
            price: row.get(4)?,
            gross_value: row.get(5)?,
            fee_paid: row.get(6)?,
            realized_pnl: row.get(7)?,
            note: row.get(8)?,
            source: row.get(9)?,
            source_order_id: row.get(10)?,
            executed_at: row.get(11)?,
        })
    })?;

    let trades: Vec<Trade> = trade_rows.collect::<Result<Vec<_>, _>>()?;
    let trade_count = trades.len();
    let positions_value: f64 = positions.iter().map(|position| position.market_value).sum();
    let unrealized_pnl: f64 = positions
        .iter()
        .map(|position| position.unrealized_pnl)
        .sum();
    let equity = account.cash_balance + positions_value;
    let total_pnl = equity - account.initial_cash;

    Ok(PaperSnapshot {
        initial_cash: account.initial_cash,
        cash_balance: account.cash_balance,
        fee_bps: account.fee_bps,
        realized_pnl: account.realized_pnl,
        positions,
        trades,
        open_orders,
        summary: PaperSummary {
            equity,
            positions_value,
            unrealized_pnl,
            total_pnl,
            trade_count,
            open_order_count,
        },
    })
}

fn insert_open_order(
    connection: &mut Connection,
    symbol: &str,
    side: OrderSide,
    quantity: f64,
    limit_price: Option<f64>,
    stop_loss: Option<f64>,
    take_profit: Option<f64>,
    note: Option<String>,
    created_at: i64,
) -> Result<i64, ApiError> {
    if matches!(side, OrderSide::Sell) {
        let available = connection
            .query_row(
                "SELECT quantity FROM positions WHERE symbol = ?1",
                params![symbol],
                |row| row.get::<_, f64>(0),
            )
            .optional()?
            .unwrap_or(0.0);

        if available + 1e-9 < quantity {
            return Err(ApiError::bad_request(format!(
                "Not enough quantity to place a sell order. Trying to sell {:.6}, holding {:.6}.",
                quantity, available
            )));
        }
    }

    connection.execute(
        "INSERT INTO orders (
            symbol, side, order_kind, quantity, limit_price, status,
            stop_loss, take_profit, note, created_at
         ) VALUES (?1, ?2, 'LIMIT', ?3, ?4, 'OPEN', ?5, ?6, ?7, ?8)",
        params![
            symbol,
            side.as_str(),
            quantity,
            limit_price,
            stop_loss,
            take_profit,
            note,
            created_at
        ],
    )?;

    Ok(connection.last_insert_rowid())
}

enum OpenOrderStatus {
    Open(OpenOrder),
    Filled(Trade),
    Cancelled(String),
}

fn fetch_order_status(
    connection: &Connection,
    order_id: i64,
) -> Result<Option<OpenOrderStatus>, ApiError> {
    let order = connection
        .query_row(
            "SELECT id, symbol, side, order_kind, quantity, limit_price, stop_loss,
                    take_profit, note, created_at, status, cancelled_reason
             FROM orders WHERE id = ?1",
            params![order_id],
            |row| {
                Ok((
                    OpenOrder {
                        id: row.get(0)?,
                        symbol: row.get(1)?,
                        side: row.get(2)?,
                        order_kind: row.get(3)?,
                        quantity: row.get(4)?,
                        limit_price: row.get(5)?,
                        stop_loss: row.get(6)?,
                        take_profit: row.get(7)?,
                        note: row.get(8)?,
                        created_at: row.get(9)?,
                    },
                    row.get::<_, String>(10)?,
                    row.get::<_, Option<String>>(11)?,
                ))
            },
        )
        .optional()?;

    let Some((order, status, cancelled_reason)) = order else {
        return Ok(None);
    };

    match status.as_str() {
        "OPEN" => Ok(Some(OpenOrderStatus::Open(order))),
        "FILLED" => {
            let trade = connection.query_row(
                "SELECT id, symbol, side, quantity, price, gross_value, fee_paid,
                        realized_pnl, note, source, source_order_id, executed_at
                 FROM trades
                 WHERE source_order_id = ?1
                 ORDER BY executed_at DESC
                 LIMIT 1",
                params![order_id],
                |row| {
                    Ok(Trade {
                        id: row.get(0)?,
                        symbol: row.get(1)?,
                        side: row.get(2)?,
                        quantity: row.get(3)?,
                        price: row.get(4)?,
                        gross_value: row.get(5)?,
                        fee_paid: row.get(6)?,
                        realized_pnl: row.get(7)?,
                        note: row.get(8)?,
                        source: row.get(9)?,
                        source_order_id: row.get(10)?,
                        executed_at: row.get(11)?,
                    })
                },
            )?;

            Ok(Some(OpenOrderStatus::Filled(trade)))
        }
        "CANCELLED" => Ok(Some(OpenOrderStatus::Cancelled(
            cancelled_reason.unwrap_or_else(|| "Order was cancelled.".to_string()),
        ))),
        _ => Ok(None),
    }
}

fn process_price_events(
    connection: &mut Connection,
    prices: &HashMap<String, f64>,
    timestamp: i64,
) -> Result<(), ApiError> {
    process_open_orders(connection, prices, timestamp)?;
    process_position_triggers(connection, prices, timestamp)?;
    Ok(())
}

async fn auto_paper_worker(state: AppState) {
    println!(
        "auto-paper worker enabled: strategies={}, interval={}s, max_open_slots={}, max_daily_entries={}, max_daily_loss={:.2}%, allow_multi_strategy_same_signal={}",
        approved_paper_strategy_versions(),
        state.auto_paper.interval_seconds,
        state.auto_paper.max_open_slots,
        state.auto_paper.max_daily_entries,
        state.auto_paper.max_daily_loss_percent,
        state.auto_paper.allow_multi_strategy_same_signal
    );

    let mut ticker = tokio::time::interval(Duration::from_secs(state.auto_paper.interval_seconds));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        ticker.tick().await;
        if let Err(error) = run_auto_paper_cycle(&state).await {
            eprintln!("auto-paper cycle failed: {}", error.message);
        }
    }
}

fn approved_paper_strategy_versions() -> String {
    APPROVED_PAPER_STRATEGIES
        .iter()
        .map(|strategy| strategy.version)
        .collect::<Vec<_>>()
        .join(",")
}

async fn run_auto_paper_cycle(state: &AppState) -> Result<(), ApiError> {
    if !state.auto_paper.enabled {
        return Ok(());
    }

    let now = Utc::now().timestamp_millis();
    let tickers = fetch_tickers(&state.client, &state.watchlist).await?;
    let prices: HashMap<String, f64> = tickers
        .iter()
        .map(|ticker| (ticker.symbol.clone(), ticker.last_price))
        .collect();

    let mut stats = {
        let mut db = state
            .db
            .lock()
            .map_err(|_| ApiError::internal("Paper database lock is poisoned."))?;
        process_price_events(&mut db, &prices, now)?;
        load_auto_paper_cycle_stats(&db, now)?
    };

    if auto_paper_caps_blocked(&state.auto_paper, &stats) {
        return Ok(());
    }

    for symbol in state
        .watchlist
        .iter()
        .filter(|symbol| symbol.as_str() != BTC_REFERENCE_SYMBOL)
    {
        let Some(current_price) = prices.get(symbol).copied() else {
            continue;
        };

        let signals = build_signal_assistants(
            &state.client,
            &state.news_cache,
            &state.watchlist,
            symbol,
            current_price,
            stats.cash_balance,
            stats.fee_bps,
            now,
            APPROVED_PAPER_STRATEGIES,
        )
        .await?;

        persist_signal_evaluations_if_enabled(state, &signals, now);

        let mut ready_signals = Vec::new();
        for signal in signals {
            if signal.risk_plan.is_some() {
                ready_signals.push(signal);
                continue;
            }
            if matches!(signal.technical_stage, SignalStage::Ready) {
                let db = state
                    .db
                    .lock()
                    .map_err(|_| ApiError::internal("Paper database lock is poisoned."))?;
                let reason = auto_paper_rejection_reason(&signal);
                insert_auto_paper_decision(&db, &signal, "rejected", Some(&reason), now)?;
            }
        }

        let selected_signals =
            select_auto_paper_signals_for_symbol(&state.auto_paper, ready_signals);
        for signal in selected_signals.skipped {
            let db = state
                .db
                .lock()
                .map_err(|_| ApiError::internal("Paper database lock is poisoned."))?;
            insert_auto_paper_decision(
                &db,
                &signal,
                "conflict_skipped",
                Some("duplicate_symbol_signal_conflict"),
                now,
            )?;
        }

        for signal in selected_signals.selected {
            let Some(risk_plan) = signal.risk_plan.clone() else {
                continue;
            };

            let entry_result = {
                let mut db = state
                    .db
                    .lock()
                    .map_err(|_| ApiError::internal("Paper database lock is poisoned."))?;
                process_price_events(&mut db, &prices, now)?;
                stats = load_auto_paper_cycle_stats(&db, now)?;

                if auto_paper_caps_blocked(&state.auto_paper, &stats) {
                    return Ok(());
                }

                if !state.auto_paper.allow_multi_strategy_same_signal
                    && has_auto_paper_symbol_signal_conflict(&db, &signal)?
                {
                    insert_auto_paper_decision(
                        &db,
                        &signal,
                        "conflict_skipped",
                        Some("duplicate_symbol_signal_conflict"),
                        now,
                    )?;
                    continue;
                }

                if !insert_auto_paper_entry_attempt(&db, &signal, now)? {
                    continue;
                }

                let affordable_quantity =
                    max_affordable_quantity(stats.cash_balance, current_price, stats.fee_bps);
                let quantity = risk_plan.suggested_quantity.min(affordable_quantity);
                if quantity <= 0.0 || !quantity.is_finite() {
                    update_auto_paper_decision_failure(
                        &db,
                        &signal,
                        "No affordable paper quantity at execution time.",
                    )?;
                    continue;
                }

                let note = Some(format!(
                    "AUTO_PAPER {} | signal_close={} | ai_score={} | {}",
                    signal.strategy_version,
                    format_utc_time(signal.signal_close_time),
                    signal.ai_score,
                    signal.summary
                ));
                let trade = execute_trade(
                    &mut db,
                    TradeExecution {
                        symbol: symbol.clone(),
                        side: OrderSide::Buy,
                        quantity,
                        price: current_price,
                        note,
                        source: "AUTO_PAPER_MARKET".to_string(),
                        source_order_id: None,
                        attached_stop_loss: Some(risk_plan.stop_loss),
                        attached_take_profit: Some(risk_plan.take_profit_1),
                        executed_at: now,
                    },
                );

                match trade {
                    Ok(trade) => {
                        update_auto_paper_decision_trade(&db, &signal, &trade, &risk_plan)?;
                        Ok(Some(trade))
                    }
                    Err(error) => {
                        update_auto_paper_decision_failure(&db, &signal, &error.message)?;
                        Err(error)
                    }
                }
            }?;

            if let Some(trade) = entry_result {
                println!(
                    "auto-paper entered {} qty {:.6} @ {:.4} using {}",
                    trade.symbol, trade.quantity, trade.price, signal.strategy_version
                );
                return Ok(());
            }
        }
    }

    Ok(())
}

fn auto_paper_caps_blocked(config: &AutoPaperConfig, stats: &AutoPaperCycleStats) -> bool {
    if stats.active_slots >= config.max_open_slots {
        return true;
    }
    if stats.daily_entries >= config.max_daily_entries {
        return true;
    }
    let max_daily_loss = stats.initial_cash * config.max_daily_loss_percent / 100.0;
    stats.daily_realized_pnl <= -max_daily_loss
}

fn load_auto_paper_cycle_stats(
    connection: &Connection,
    now: i64,
) -> Result<AutoPaperCycleStats, ApiError> {
    let account = fetch_account(connection)?;
    let day_start = utc_day_start_ms(now);
    let open_positions: i64 = connection.query_row(
        "SELECT COUNT(*) FROM positions WHERE quantity > 0",
        [],
        |row| row.get(0),
    )?;
    let open_orders: i64 = connection.query_row(
        "SELECT COUNT(*) FROM orders WHERE status = 'OPEN'",
        [],
        |row| row.get(0),
    )?;
    let daily_entries: i64 = connection.query_row(
        "SELECT COUNT(*) FROM trades
         WHERE source = 'AUTO_PAPER_MARKET' AND side = 'BUY' AND executed_at >= ?1",
        params![day_start],
        |row| row.get(0),
    )?;
    let daily_realized_pnl: f64 = connection.query_row(
        "SELECT COALESCE(SUM(realized_pnl), 0.0) FROM trades
         WHERE side = 'SELL' AND executed_at >= ?1",
        params![day_start],
        |row| row.get(0),
    )?;

    Ok(AutoPaperCycleStats {
        active_slots: (open_positions + open_orders).max(0) as usize,
        daily_entries: daily_entries.max(0) as usize,
        daily_realized_pnl,
        initial_cash: account.initial_cash,
        cash_balance: account.cash_balance,
        fee_bps: account.fee_bps,
    })
}

struct AutoPaperSignalSelection {
    selected: Vec<SignalAssistant>,
    skipped: Vec<SignalAssistant>,
}

fn auto_paper_conflict_priority(config: &AutoPaperConfig, strategy_version: &str) -> i32 {
    if config.prefer_secondary_on_score_tie {
        if strategy_version == SECONDARY_PAPER_STRATEGY_VERSION {
            2
        } else if strategy_version == ACTIVE_PAPER_STRATEGY_VERSION {
            1
        } else {
            0
        }
    } else if strategy_version == ACTIVE_PAPER_STRATEGY_VERSION {
        2
    } else if strategy_version == SECONDARY_PAPER_STRATEGY_VERSION {
        1
    } else {
        0
    }
}

fn select_auto_paper_signals_for_symbol(
    config: &AutoPaperConfig,
    signals: Vec<SignalAssistant>,
) -> AutoPaperSignalSelection {
    if config.allow_multi_strategy_same_signal {
        return AutoPaperSignalSelection {
            selected: signals,
            skipped: Vec::new(),
        };
    }

    let mut grouped: HashMap<i64, Vec<SignalAssistant>> = HashMap::new();
    for signal in signals {
        grouped
            .entry(signal.signal_close_time)
            .or_default()
            .push(signal);
    }

    let mut selected = Vec::new();
    let mut skipped = Vec::new();
    for (_, mut group) in grouped {
        group.sort_by(|left, right| {
            let left_key = (
                left.ai_score,
                auto_paper_conflict_priority(config, left.strategy_version),
            );
            let right_key = (
                right.ai_score,
                auto_paper_conflict_priority(config, right.strategy_version),
            );
            right_key.cmp(&left_key)
        });
        if !group.is_empty() {
            selected.push(group.remove(0));
        }
        skipped.extend(group);
    }
    selected.sort_by(|left, right| {
        let left_key = (
            left.signal_close_time,
            -left.ai_score,
            -auto_paper_conflict_priority(config, left.strategy_version),
        );
        let right_key = (
            right.signal_close_time,
            -right.ai_score,
            -auto_paper_conflict_priority(config, right.strategy_version),
        );
        left_key.cmp(&right_key)
    });
    AutoPaperSignalSelection { selected, skipped }
}

fn has_auto_paper_symbol_signal_conflict(
    connection: &Connection,
    signal: &SignalAssistant,
) -> Result<bool, ApiError> {
    let count: i64 = connection.query_row(
        "SELECT COUNT(*) FROM auto_paper_decisions
         WHERE symbol = ?1
           AND signal_close_time = ?2
           AND strategy_version != ?3
           AND decision IN ('entry_attempt', 'entered')",
        params![&signal.symbol, signal.signal_close_time, signal.strategy_version],
        |row| row.get(0),
    )?;
    Ok(count > 0)
}

fn insert_auto_paper_decision(
    connection: &Connection,
    signal: &SignalAssistant,
    decision: &str,
    reason: Option<&str>,
    created_at: i64,
) -> Result<bool, ApiError> {
    let changed = connection.execute(
        "INSERT OR IGNORE INTO auto_paper_decisions (
            strategy_version, symbol, signal_close_time, decision, reason,
            ai_score, stage, created_at
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        params![
            signal.strategy_version,
            &signal.symbol,
            signal.signal_close_time,
            decision,
            reason,
            signal.ai_score,
            signal.stage.as_label(),
            created_at
        ],
    )?;
    Ok(changed > 0)
}

fn insert_auto_paper_entry_attempt(
    connection: &Connection,
    signal: &SignalAssistant,
    created_at: i64,
) -> Result<bool, ApiError> {
    if insert_auto_paper_decision(connection, signal, "entry_attempt", None, created_at)? {
        return Ok(true);
    }

    let changed = connection.execute(
        "UPDATE auto_paper_decisions
         SET decision = 'entry_attempt',
             reason = NULL,
             ai_score = ?1,
             stage = ?2,
             created_at = ?3,
             trade_id = NULL,
             entry_price = NULL,
             stop_loss = NULL,
             take_profit = NULL,
             quantity = NULL,
             risk_per_unit = NULL,
             risk_amount = NULL
         WHERE strategy_version = ?4
           AND symbol = ?5
           AND signal_close_time = ?6
           AND decision = 'rejected'",
        params![
            signal.ai_score,
            signal.stage.as_label(),
            created_at,
            signal.strategy_version,
            &signal.symbol,
            signal.signal_close_time
        ],
    )?;
    Ok(changed > 0)
}

fn auto_paper_rejection_reason(signal: &SignalAssistant) -> String {
    let failed = signal
        .checklist
        .iter()
        .filter(|check| !check.passed)
        .map(|check| check.label.as_str())
        .collect::<Vec<_>>();
    if failed.is_empty() {
        signal.summary.clone()
    } else {
        format!("{} Failed checks: {}.", signal.summary, failed.join(", "))
    }
}

fn update_auto_paper_decision_trade(
    connection: &Connection,
    signal: &SignalAssistant,
    trade: &Trade,
    risk_plan: &SignalRiskPlan,
) -> Result<(), ApiError> {
    let risk_amount = trade.quantity * risk_plan.risk_per_unit;
    connection.execute(
        "UPDATE auto_paper_decisions
         SET decision = 'entered',
             trade_id = ?1,
             entry_price = ?2,
             stop_loss = ?3,
             take_profit = ?4,
             quantity = ?5,
             risk_per_unit = ?6,
             risk_amount = ?7
         WHERE strategy_version = ?8 AND symbol = ?9 AND signal_close_time = ?10",
        params![
            trade.id,
            trade.price,
            risk_plan.stop_loss,
            risk_plan.take_profit_1,
            trade.quantity,
            risk_plan.risk_per_unit,
            risk_amount,
            signal.strategy_version,
            &signal.symbol,
            signal.signal_close_time
        ],
    )?;
    Ok(())
}

fn update_auto_paper_decision_failure(
    connection: &Connection,
    signal: &SignalAssistant,
    reason: &str,
) -> Result<(), ApiError> {
    connection.execute(
        "UPDATE auto_paper_decisions
         SET decision = 'failed', reason = ?1
         WHERE strategy_version = ?2 AND symbol = ?3 AND signal_close_time = ?4",
        params![
            reason,
            signal.strategy_version,
            &signal.symbol,
            signal.signal_close_time
        ],
    )?;
    Ok(())
}

async fn runtime_telemetry_worker(state: AppState) {
    println!(
        "runtime telemetry enabled: interval={}s, candle_limit={}, futures={}, signal_evaluations={}",
        state.telemetry.interval_seconds,
        state.telemetry.candle_limit,
        state.telemetry.futures_enabled,
        state.telemetry.signal_evaluations_enabled
    );

    let mut ticker = tokio::time::interval(Duration::from_secs(state.telemetry.interval_seconds));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        ticker.tick().await;
        if let Err(error) = run_runtime_telemetry_cycle(&state).await {
            eprintln!("runtime telemetry cycle failed: {}", error.message);
        }
    }
}

async fn run_runtime_telemetry_cycle(state: &AppState) -> Result<(), ApiError> {
    if !state.telemetry.enabled {
        return Ok(());
    }

    let captured_at = Utc::now().timestamp_millis();
    let tickers = fetch_tickers(&state.client, &state.watchlist).await?;
    persist_market_tickers_if_enabled(state, &tickers, captured_at);

    for symbol in &state.watchlist {
        for interval in TELEMETRY_CANDLE_INTERVALS {
            match fetch_candles(
                &state.client,
                symbol,
                interval,
                state.telemetry.candle_limit,
            )
            .await
            {
                Ok(candles) => {
                    persist_candles_if_enabled(state, symbol, interval, &candles, captured_at);
                }
                Err(error) => eprintln!(
                    "runtime telemetry candle archive skipped {symbol} {interval}: {}",
                    error.message
                ),
            }
        }

        if state.telemetry.futures_enabled && symbol != BTC_REFERENCE_SYMBOL {
            archive_symbol_futures_telemetry(state, symbol, captured_at).await;
        }
    }

    Ok(())
}

async fn archive_symbol_futures_telemetry(state: &AppState, symbol: &str, captured_at: i64) {
    let funding_lookback_ms =
        (DEFAULT_RUNTIME_TELEMETRY_FUNDING_LOOKBACK_HOURS * 60.0 * 60.0 * 1000.0) as i64;
    let funding_start = captured_at.saturating_sub(funding_lookback_ms);

    match fetch_funding_rate_rows(&state.client, symbol, funding_start, captured_at, 1000).await {
        Ok(rows) => persist_funding_rates_if_enabled(state, &rows, captured_at),
        Err(error) => eprintln!(
            "runtime telemetry funding archive skipped {symbol}: {}",
            error.message
        ),
    }

    match fetch_open_interest_rows(&state.client, symbol, 300).await {
        Ok(rows) => persist_open_interest_rows_if_enabled(state, symbol, &rows, captured_at),
        Err(error) => eprintln!(
            "runtime telemetry open-interest archive skipped {symbol}: {}",
            error.message
        ),
    }

    let ratio_specs = [
        (
            "global_long_short_account_ratio",
            "/futures/data/globalLongShortAccountRatio",
        ),
        (
            "top_long_short_position_ratio",
            "/futures/data/topLongShortPositionRatio",
        ),
        (
            "taker_long_short_ratio",
            "/futures/data/takerlongshortRatio",
        ),
    ];
    for (metric_name, path) in ratio_specs {
        match fetch_futures_ratio_rows(&state.client, path, symbol, 300).await {
            Ok(rows) => persist_futures_ratio_rows_if_enabled(
                state,
                symbol,
                metric_name,
                &rows,
                captured_at,
            ),
            Err(error) => eprintln!(
                "runtime telemetry {metric_name} archive skipped {symbol}: {}",
                error.message
            ),
        }
    }
}

fn persist_market_tickers_if_enabled(
    state: &AppState,
    tickers: &[TickerSummary],
    captured_at: i64,
) {
    if !state.telemetry.enabled {
        return;
    }

    let result = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))
        .and_then(|db| insert_telemetry_market_tickers(&db, tickers, captured_at));
    if let Err(error) = result {
        eprintln!("runtime telemetry ticker archive failed: {}", error.message);
    }
}

fn persist_candles_if_enabled(
    state: &AppState,
    symbol: &str,
    interval: &str,
    candles: &[Candle],
    captured_at: i64,
) {
    if !state.telemetry.enabled {
        return;
    }

    let result = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))
        .and_then(|db| insert_telemetry_candles(&db, symbol, interval, candles, captured_at));
    if let Err(error) = result {
        eprintln!(
            "runtime telemetry candle archive failed for {symbol} {interval}: {}",
            error.message
        );
    }
}

fn persist_funding_rates_if_enabled(
    state: &AppState,
    rows: &[BinanceFundingRate],
    captured_at: i64,
) {
    if !state.telemetry.enabled || !state.telemetry.futures_enabled {
        return;
    }

    let result = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))
        .and_then(|db| insert_telemetry_funding_rates(&db, rows, captured_at));
    if let Err(error) = result {
        eprintln!(
            "runtime telemetry funding archive failed: {}",
            error.message
        );
    }
}

fn persist_open_interest_rows_if_enabled(
    state: &AppState,
    symbol: &str,
    rows: &[BinanceOpenInterestHist],
    captured_at: i64,
) {
    if !state.telemetry.enabled || !state.telemetry.futures_enabled {
        return;
    }

    let result = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))
        .and_then(|db| insert_telemetry_open_interest_rows(&db, symbol, rows, captured_at));
    if let Err(error) = result {
        eprintln!(
            "runtime telemetry open-interest archive failed for {symbol}: {}",
            error.message
        );
    }
}

fn persist_futures_ratio_rows_if_enabled(
    state: &AppState,
    symbol: &str,
    metric_name: &str,
    rows: &[BinanceRatioRow],
    captured_at: i64,
) {
    if !state.telemetry.enabled || !state.telemetry.futures_enabled {
        return;
    }

    let result = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))
        .and_then(|db| {
            insert_telemetry_futures_ratio_rows(&db, symbol, metric_name, rows, captured_at)
        });
    if let Err(error) = result {
        eprintln!(
            "runtime telemetry {metric_name} archive failed for {symbol}: {}",
            error.message
        );
    }
}

fn persist_signal_evaluations_if_enabled(
    state: &AppState,
    signals: &[SignalAssistant],
    captured_at: i64,
) {
    if !state.telemetry.enabled || !state.telemetry.signal_evaluations_enabled {
        return;
    }

    let result = state
        .db
        .lock()
        .map_err(|_| ApiError::internal("Paper database lock is poisoned."))
        .and_then(|db| insert_telemetry_signal_evaluations(&db, signals, captured_at));
    if let Err(error) = result {
        eprintln!(
            "runtime telemetry signal evaluation archive failed: {}",
            error.message
        );
    }
}

fn insert_telemetry_market_tickers(
    connection: &Connection,
    tickers: &[TickerSummary],
    captured_at: i64,
) -> Result<(), ApiError> {
    let tx = connection.unchecked_transaction()?;
    for ticker in tickers {
        tx.execute(
            "INSERT INTO telemetry_market_tickers (
                symbol, snapshot_time, last_price, price_change_percent,
                high_price, low_price, volume, quote_volume, source
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'binance_spot_24hr')
             ON CONFLICT(symbol, snapshot_time) DO UPDATE SET
                last_price = excluded.last_price,
                price_change_percent = excluded.price_change_percent,
                high_price = excluded.high_price,
                low_price = excluded.low_price,
                volume = excluded.volume,
                quote_volume = excluded.quote_volume,
                source = excluded.source",
            params![
                &ticker.symbol,
                captured_at,
                ticker.last_price,
                ticker.price_change_percent,
                ticker.high_price,
                ticker.low_price,
                ticker.volume,
                ticker.quote_volume,
            ],
        )?;
    }
    tx.commit()?;
    Ok(())
}

fn insert_telemetry_candles(
    connection: &Connection,
    symbol: &str,
    interval: &str,
    candles: &[Candle],
    captured_at: i64,
) -> Result<(), ApiError> {
    let tx = connection.unchecked_transaction()?;
    for candle in candles {
        tx.execute(
            "INSERT INTO telemetry_candles (
                symbol, interval, open_time, open, high, low, close, volume,
                fetched_at, source
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 'binance_spot_klines')
             ON CONFLICT(symbol, interval, open_time) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                fetched_at = excluded.fetched_at,
                source = excluded.source",
            params![
                symbol,
                interval,
                candle.open_time,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                captured_at,
            ],
        )?;
    }
    tx.commit()?;
    Ok(())
}

fn insert_telemetry_funding_rates(
    connection: &Connection,
    rows: &[BinanceFundingRate],
    captured_at: i64,
) -> Result<(), ApiError> {
    let tx = connection.unchecked_transaction()?;
    for row in rows {
        let funding_time = parse_json_i64(&row.funding_time)?;
        let funding_rate_bps = parse_f64(&row.funding_rate)? * 10_000.0;
        let mark_price = parse_optional_f64(row.mark_price.as_deref())?;
        tx.execute(
            "INSERT INTO telemetry_funding_rates (
                symbol, funding_time, funding_rate_bps, mark_price, fetched_at, source
             ) VALUES (?1, ?2, ?3, ?4, ?5, 'binance_usdm_funding_rate')
             ON CONFLICT(symbol, funding_time) DO UPDATE SET
                funding_rate_bps = excluded.funding_rate_bps,
                mark_price = excluded.mark_price,
                fetched_at = excluded.fetched_at,
                source = excluded.source",
            params![
                &row.symbol,
                funding_time,
                funding_rate_bps,
                mark_price,
                captured_at,
            ],
        )?;
    }
    tx.commit()?;
    Ok(())
}

fn insert_telemetry_open_interest_rows(
    connection: &Connection,
    symbol: &str,
    rows: &[BinanceOpenInterestHist],
    captured_at: i64,
) -> Result<(), ApiError> {
    let tx = connection.unchecked_transaction()?;
    for row in rows {
        let timestamp = parse_json_i64(&row.timestamp)?;
        let sum_open_interest = parse_optional_f64(row.sum_open_interest.as_deref())?;
        let sum_open_interest_value = parse_f64(&row.sum_open_interest_value)?;
        tx.execute(
            "INSERT INTO telemetry_futures_metric_rows (
                symbol, metric_name, timestamp, period, long_short_ratio,
                buy_sell_ratio, sum_open_interest, sum_open_interest_value,
                fetched_at, source
             ) VALUES (?1, 'open_interest_hist', ?2, '5m', NULL, NULL, ?3, ?4, ?5, 'binance_usdm_open_interest_hist')
             ON CONFLICT(symbol, metric_name, timestamp) DO UPDATE SET
                sum_open_interest = excluded.sum_open_interest,
                sum_open_interest_value = excluded.sum_open_interest_value,
                fetched_at = excluded.fetched_at,
                source = excluded.source",
            params![
                symbol,
                timestamp,
                sum_open_interest,
                sum_open_interest_value,
                captured_at,
            ],
        )?;
    }
    tx.commit()?;
    Ok(())
}

fn insert_telemetry_futures_ratio_rows(
    connection: &Connection,
    symbol: &str,
    metric_name: &str,
    rows: &[BinanceRatioRow],
    captured_at: i64,
) -> Result<(), ApiError> {
    let tx = connection.unchecked_transaction()?;
    for row in rows {
        let timestamp = parse_json_i64(&row.timestamp)?;
        let long_short_ratio = parse_optional_f64(row.long_short_ratio.as_deref())?;
        let buy_sell_ratio = parse_optional_f64(row.buy_sell_ratio.as_deref())?;
        tx.execute(
            "INSERT INTO telemetry_futures_metric_rows (
                symbol, metric_name, timestamp, period, long_short_ratio,
                buy_sell_ratio, sum_open_interest, sum_open_interest_value,
                fetched_at, source
             ) VALUES (?1, ?2, ?3, '5m', ?4, ?5, NULL, NULL, ?6, 'binance_usdm_futures_data')
             ON CONFLICT(symbol, metric_name, timestamp) DO UPDATE SET
                long_short_ratio = excluded.long_short_ratio,
                buy_sell_ratio = excluded.buy_sell_ratio,
                fetched_at = excluded.fetched_at,
                source = excluded.source",
            params![
                symbol,
                metric_name,
                timestamp,
                long_short_ratio,
                buy_sell_ratio,
                captured_at,
            ],
        )?;
    }
    tx.commit()?;
    Ok(())
}

fn insert_telemetry_signal_evaluations(
    connection: &Connection,
    signals: &[SignalAssistant],
    captured_at: i64,
) -> Result<(), ApiError> {
    let tx = connection.unchecked_transaction()?;
    for signal in signals {
        let failed_checks = signal
            .checklist
            .iter()
            .filter(|check| !check.passed)
            .map(|check| check.label.clone())
            .collect::<Vec<_>>();
        let failed_checks_json = to_json_string(&failed_checks)?;
        let checklist_json = to_json_string(&signal.checklist)?;
        let warnings_json = to_json_string(&signal.warnings)?;
        let journal_tags_json = to_json_string(&signal.journal_tags)?;
        let risk_plan = signal.risk_plan.as_ref();
        tx.execute(
            "INSERT INTO telemetry_signal_evaluations (
                strategy_version, symbol, signal_close_time, generated_at, captured_at,
                stage, technical_stage, bias, confidence, ai_score, summary,
                has_risk_plan, entry_price, stop_loss, take_profit_1, take_profit_2,
                suggested_quantity, risk_amount, failed_checks_json, checklist_json,
                warnings_json, journal_tags_json, source
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12,
                       ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22,
                       'runtime_signal_assistant')
             ON CONFLICT(strategy_version, symbol, signal_close_time) DO UPDATE SET
                generated_at = excluded.generated_at,
                captured_at = excluded.captured_at,
                stage = excluded.stage,
                technical_stage = excluded.technical_stage,
                bias = excluded.bias,
                confidence = excluded.confidence,
                ai_score = excluded.ai_score,
                summary = excluded.summary,
                has_risk_plan = excluded.has_risk_plan,
                entry_price = excluded.entry_price,
                stop_loss = excluded.stop_loss,
                take_profit_1 = excluded.take_profit_1,
                take_profit_2 = excluded.take_profit_2,
                suggested_quantity = excluded.suggested_quantity,
                risk_amount = excluded.risk_amount,
                failed_checks_json = excluded.failed_checks_json,
                checklist_json = excluded.checklist_json,
                warnings_json = excluded.warnings_json,
                journal_tags_json = excluded.journal_tags_json,
                source = excluded.source",
            params![
                signal.strategy_version,
                &signal.symbol,
                signal.signal_close_time,
                signal.generated_at,
                captured_at,
                signal.stage.as_label(),
                signal.technical_stage.as_label(),
                signal.bias.as_label(),
                signal.confidence as i64,
                signal.ai_score,
                &signal.summary,
                if risk_plan.is_some() { 1_i64 } else { 0_i64 },
                risk_plan.map(|plan| plan.entry),
                risk_plan.map(|plan| plan.stop_loss),
                risk_plan.map(|plan| plan.take_profit_1),
                risk_plan.map(|plan| plan.take_profit_2),
                risk_plan.map(|plan| plan.suggested_quantity),
                risk_plan.map(|plan| plan.risk_amount),
                failed_checks_json,
                checklist_json,
                warnings_json,
                journal_tags_json,
            ],
        )?;
    }
    tx.commit()?;
    Ok(())
}

fn process_open_orders(
    connection: &mut Connection,
    prices: &HashMap<String, f64>,
    timestamp: i64,
) -> Result<(), ApiError> {
    let mut statement = connection.prepare(
        "SELECT id, symbol, side, quantity, limit_price, stop_loss, take_profit, note
         FROM orders
         WHERE status = 'OPEN'
         ORDER BY created_at ASC",
    )?;

    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, i64>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, f64>(3)?,
            row.get::<_, Option<f64>>(4)?,
            row.get::<_, Option<f64>>(5)?,
            row.get::<_, Option<f64>>(6)?,
            row.get::<_, Option<String>>(7)?,
        ))
    })?;

    let pending = rows.collect::<Result<Vec<_>, _>>()?;
    drop(statement);

    for (order_id, symbol, side_raw, quantity, limit_price, stop_loss, take_profit, note) in pending
    {
        let Some(current_price) = prices.get(&symbol).copied() else {
            continue;
        };
        let Some(limit_price) = limit_price else {
            continue;
        };

        let side = parse_order_side(&side_raw)?;
        let should_fill = match side {
            OrderSide::Buy => current_price <= limit_price,
            OrderSide::Sell => current_price >= limit_price,
        };

        if !should_fill {
            continue;
        }

        let execution = TradeExecution {
            symbol,
            side,
            quantity,
            price: current_price,
            note,
            source: "MANUAL_LIMIT".to_string(),
            source_order_id: Some(order_id),
            attached_stop_loss: stop_loss,
            attached_take_profit: take_profit,
            executed_at: timestamp,
        };

        if let Err(error) = execute_trade(connection, execution) {
            connection.execute(
                "UPDATE orders
                 SET status = 'CANCELLED', cancelled_reason = ?1, cancelled_at = ?2
                 WHERE id = ?3 AND status = 'OPEN'",
                params![error.message, timestamp, order_id],
            )?;
        }
    }

    Ok(())
}

fn process_position_triggers(
    connection: &mut Connection,
    prices: &HashMap<String, f64>,
    timestamp: i64,
) -> Result<(), ApiError> {
    let mut statement = connection.prepare(
        "SELECT symbol, quantity, stop_loss, take_profit, note
         FROM positions
         WHERE quantity > 0",
    )?;

    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, f64>(1)?,
            row.get::<_, Option<f64>>(2)?,
            row.get::<_, Option<f64>>(3)?,
            row.get::<_, Option<String>>(4)?,
        ))
    })?;

    let positions = rows.collect::<Result<Vec<_>, _>>()?;
    drop(statement);

    for (symbol, quantity, stop_loss, take_profit, note) in positions {
        let Some(current_price) = prices.get(&symbol).copied() else {
            continue;
        };

        let source = if stop_loss.is_some() && current_price <= stop_loss.unwrap_or_default() {
            Some("AUTO_STOP_LOSS".to_string())
        } else if take_profit.is_some() && current_price >= take_profit.unwrap_or_default() {
            Some("AUTO_TAKE_PROFIT".to_string())
        } else {
            None
        };

        let Some(source) = source else {
            continue;
        };

        let trigger_note = Some(match note {
            Some(existing) => format!("{source}: {existing}"),
            None => source.clone(),
        });

        let execution = TradeExecution {
            symbol,
            side: OrderSide::Sell,
            quantity,
            price: current_price,
            note: trigger_note,
            source,
            source_order_id: None,
            attached_stop_loss: None,
            attached_take_profit: None,
            executed_at: timestamp,
        };

        execute_trade(connection, execution)?;
    }

    Ok(())
}

struct TradeExecution {
    symbol: String,
    side: OrderSide,
    quantity: f64,
    price: f64,
    note: Option<String>,
    source: String,
    source_order_id: Option<i64>,
    attached_stop_loss: Option<f64>,
    attached_take_profit: Option<f64>,
    executed_at: i64,
}

fn execute_trade(
    connection: &mut Connection,
    execution: TradeExecution,
) -> Result<Trade, ApiError> {
    let TradeExecution {
        symbol,
        side,
        quantity,
        price,
        note,
        source,
        source_order_id,
        attached_stop_loss,
        attached_take_profit,
        executed_at,
    } = execution;

    let tx = connection.transaction()?;
    let account = fetch_account_tx(&tx)?;
    let gross_value = quantity * price;
    let fee_paid = gross_value * account.fee_bps / 10_000.0;
    let mut realized_pnl = 0.0;

    match side {
        OrderSide::Buy => {
            let total_cost = gross_value + fee_paid;
            if account.cash_balance + 1e-9 < total_cost {
                return Err(ApiError::bad_request(format!(
                    "Not enough paper cash. Need {:.2}, available {:.2}.",
                    total_cost, account.cash_balance
                )));
            }

            let current_position = fetch_position_tx(&tx, &symbol)?;
            let previous_quantity = current_position
                .as_ref()
                .map(|item| item.quantity)
                .unwrap_or(0.0);
            let previous_cost = current_position
                .as_ref()
                .map(|item| item.avg_price * item.quantity)
                .unwrap_or(0.0);
            let new_quantity = previous_quantity + quantity;
            let avg_price = (previous_cost + total_cost) / new_quantity;
            let stop_loss =
                attached_stop_loss.or(current_position.as_ref().and_then(|item| item.stop_loss));
            let take_profit = attached_take_profit
                .or(current_position.as_ref().and_then(|item| item.take_profit));
            let position_note = note.clone().or(current_position.and_then(|item| item.note));

            tx.execute(
                "INSERT INTO positions (symbol, quantity, avg_price, stop_loss, take_profit, note, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
                 ON CONFLICT(symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    avg_price = excluded.avg_price,
                    stop_loss = excluded.stop_loss,
                    take_profit = excluded.take_profit,
                    note = excluded.note,
                    updated_at = excluded.updated_at",
                params![
                    symbol,
                    new_quantity,
                    avg_price,
                    stop_loss,
                    take_profit,
                    position_note,
                    executed_at
                ],
            )?;

            tx.execute(
                "UPDATE account SET cash_balance = ?1 WHERE id = 1",
                params![account.cash_balance - total_cost],
            )?;
        }
        OrderSide::Sell => {
            let position = fetch_position_tx(&tx, &symbol)?
                .ok_or_else(|| ApiError::bad_request("No open paper position for that symbol."))?;

            if position.quantity + 1e-9 < quantity {
                return Err(ApiError::bad_request(format!(
                    "Not enough quantity to sell. Trying to sell {:.6}, holding {:.6}.",
                    quantity, position.quantity
                )));
            }

            let cost_basis = position.avg_price * quantity;
            let net_proceeds = gross_value - fee_paid;
            realized_pnl = net_proceeds - cost_basis;
            let remaining_quantity = position.quantity - quantity;

            tx.execute(
                "UPDATE account
                 SET cash_balance = ?1, realized_pnl = realized_pnl + ?2
                 WHERE id = 1",
                params![account.cash_balance + net_proceeds, realized_pnl],
            )?;

            if remaining_quantity <= 1e-9 {
                tx.execute("DELETE FROM positions WHERE symbol = ?1", params![symbol])?;
            } else {
                tx.execute(
                    "UPDATE positions
                     SET quantity = ?1, updated_at = ?2
                     WHERE symbol = ?3",
                    params![remaining_quantity, executed_at, symbol],
                )?;
            }
        }
    }

    tx.execute(
        "INSERT INTO trades (
            symbol, side, quantity, price, gross_value, fee_paid, realized_pnl,
            note, source, source_order_id, executed_at
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
        params![
            symbol,
            side.as_str(),
            quantity,
            price,
            gross_value,
            fee_paid,
            realized_pnl,
            note,
            source,
            source_order_id,
            executed_at
        ],
    )?;
    let trade_id = tx.last_insert_rowid();

    if let Some(order_id) = source_order_id {
        tx.execute(
            "UPDATE orders
             SET status = 'FILLED', filled_at = ?1, fill_price = ?2
             WHERE id = ?3",
            params![executed_at, price, order_id],
        )?;
    }

    tx.commit()?;

    Ok(Trade {
        id: trade_id,
        symbol,
        side: side.as_str().to_string(),
        quantity,
        price,
        gross_value,
        fee_paid,
        realized_pnl,
        note,
        source,
        source_order_id,
        executed_at,
    })
}

fn fetch_account_tx(tx: &Transaction<'_>) -> Result<AccountRecord, ApiError> {
    tx.query_row(
        "SELECT initial_cash, cash_balance, fee_bps, realized_pnl
         FROM account WHERE id = 1",
        [],
        |row| {
            Ok(AccountRecord {
                initial_cash: row.get(0)?,
                cash_balance: row.get(1)?,
                fee_bps: row.get(2)?,
                realized_pnl: row.get(3)?,
            })
        },
    )
    .map_err(ApiError::from)
}

fn fetch_position_tx(tx: &Transaction<'_>, symbol: &str) -> Result<Option<DbPosition>, ApiError> {
    tx.query_row(
        "SELECT symbol, quantity, avg_price, stop_loss, take_profit, note
         FROM positions WHERE symbol = ?1",
        params![symbol],
        |row| {
            Ok(DbPosition {
                symbol: row.get(0)?,
                quantity: row.get(1)?,
                avg_price: row.get(2)?,
                stop_loss: row.get(3)?,
                take_profit: row.get(4)?,
                note: row.get(5)?,
            })
        },
    )
    .optional()
    .map_err(ApiError::from)
}

fn parse_order_side(raw: &str) -> Result<OrderSide, ApiError> {
    match raw {
        "BUY" => Ok(OrderSide::Buy),
        "SELL" => Ok(OrderSide::Sell),
        _ => Err(ApiError::internal("Stored order side is invalid.")),
    }
}

async fn fetch_tickers(
    client: &Client,
    watchlist: &[String],
) -> Result<Vec<TickerSummary>, ApiError> {
    let symbols = serde_json::to_string(watchlist)
        .map_err(|error| ApiError::internal(format!("Failed to build ticker query: {error}")))?;
    let response = client
        .get(format!("{BINANCE_DATA_API}/api/v3/ticker/24hr"))
        .query(&[("symbols", symbols)])
        .send()
        .await
        .map_err(|error| ApiError::upstream(format!("Failed to fetch market snapshot: {error}")))?;

    if !response.status().is_success() {
        return Err(ApiError::upstream(format!(
            "Exchange market snapshot returned {}.",
            response.status()
        )));
    }

    let payload: Vec<BinanceTicker> = response
        .json()
        .await
        .map_err(|error| ApiError::upstream(format!("Failed to decode ticker payload: {error}")))?;

    let mut tickers = Vec::with_capacity(payload.len());
    for item in payload {
        tickers.push(TickerSummary {
            symbol: item.symbol,
            last_price: parse_f64(&item.last_price)?,
            price_change_percent: parse_f64(&item.price_change_percent)?,
            high_price: parse_f64(&item.high_price)?,
            low_price: parse_f64(&item.low_price)?,
            volume: parse_f64(&item.volume)?,
            quote_volume: parse_f64(&item.quote_volume)?,
        });
    }
    tickers.sort_by(|left, right| left.symbol.cmp(&right.symbol));

    Ok(tickers)
}

async fn fetch_last_price(client: &Client, symbol: &str) -> Result<f64, ApiError> {
    let response = client
        .get(format!("{BINANCE_DATA_API}/api/v3/ticker/price"))
        .query(&[("symbol", symbol)])
        .send()
        .await
        .map_err(|error| ApiError::upstream(format!("Failed to fetch price ticker: {error}")))?;

    if !response.status().is_success() {
        return Err(ApiError::upstream(format!(
            "Exchange price ticker returned {} for {symbol}.",
            response.status()
        )));
    }

    let payload: BinancePriceTicker = response.json().await.map_err(|error| {
        ApiError::upstream(format!("Failed to decode price ticker payload: {error}"))
    })?;

    if payload.symbol != symbol {
        return Err(ApiError::upstream("Exchange returned a mismatched symbol."));
    }

    parse_f64(&payload.price)
}

async fn fetch_candles(
    client: &Client,
    symbol: &str,
    interval: &str,
    limit: usize,
) -> Result<Vec<Candle>, ApiError> {
    let response = client
        .get(format!("{BINANCE_DATA_API}/api/v3/klines"))
        .query(&[
            ("symbol", symbol.to_string()),
            ("interval", interval.to_string()),
            ("limit", limit.to_string()),
        ])
        .send()
        .await
        .map_err(|error| ApiError::upstream(format!("Failed to fetch candles: {error}")))?;

    if !response.status().is_success() {
        return Err(ApiError::upstream(format!(
            "Exchange candle request returned {} for {symbol}.",
            response.status()
        )));
    }

    let payload: Vec<Vec<serde_json::Value>> = response
        .json()
        .await
        .map_err(|error| ApiError::upstream(format!("Failed to decode candle payload: {error}")))?;

    let mut candles = Vec::with_capacity(payload.len());
    for row in payload {
        if row.len() < 6 {
            continue;
        }

        let open_time = row[0]
            .as_i64()
            .ok_or_else(|| ApiError::upstream("Candle payload is missing open_time."))?;
        let open = parse_json_f64(&row[1])?;
        let high = parse_json_f64(&row[2])?;
        let low = parse_json_f64(&row[3])?;
        let close = parse_json_f64(&row[4])?;
        let volume = parse_json_f64(&row[5])?;

        candles.push(Candle {
            open_time,
            open,
            high,
            low,
            close,
            volume,
        });
    }

    Ok(candles)
}

async fn fetch_scorecard_context(
    client: &Client,
    symbol: &str,
    watchlist: &[String],
    signal_close_time: i64,
    selected_trigger_closed: &[Candle],
) -> ScorecardContext {
    let mut context = ScorecardContext::empty();

    match fetch_latest_funding_bps(client, symbol, signal_close_time).await {
        Ok(funding_bps) => context.funding_bps = funding_bps,
        Err(error) => context.warnings.push(format!(
            "Funding scorecard podatek ni dosegljiv za {symbol}: {}.",
            error.message
        )),
    }

    match fetch_futures_metric_snapshot(client, symbol, signal_close_time).await {
        Ok(metrics) => context.metrics = metrics,
        Err(error) => context.warnings.push(format!(
            "Futures positioning scorecard podatki niso dosegljivi za {symbol}: {}.",
            error.message
        )),
    }

    let (basket, mut basket_warnings) = build_basket_snapshot(
        client,
        symbol,
        watchlist,
        signal_close_time,
        selected_trigger_closed,
    )
    .await;
    context.basket = basket;
    context.warnings.append(&mut basket_warnings);

    context
}

async fn fetch_latest_funding_bps(
    client: &Client,
    symbol: &str,
    signal_close_time: i64,
) -> Result<Option<(f64, i64)>, ApiError> {
    let lookback_ms = (ACTIVE_PAPER_STRATEGY_FUNDING_MAX_AGE_HOURS * 60.0 * 60.0 * 1000.0) as i64;
    let start_time = signal_close_time.saturating_sub(lookback_ms);
    let rows = fetch_funding_rate_rows(client, symbol, start_time, signal_close_time, 1000).await?;

    let mut latest: Option<(f64, i64)> = None;
    for row in rows {
        if row.symbol != symbol {
            continue;
        }
        let funding_time = parse_json_i64(&row.funding_time)?;
        if funding_time > signal_close_time {
            continue;
        }
        let funding_bps = parse_f64(&row.funding_rate)? * 10_000.0;
        if latest
            .map(|(_, current_time)| funding_time > current_time)
            .unwrap_or(true)
        {
            latest = Some((funding_bps, funding_time));
        }
    }

    Ok(latest)
}

async fn fetch_funding_rate_rows(
    client: &Client,
    symbol: &str,
    start_time: i64,
    end_time: i64,
    limit: usize,
) -> Result<Vec<BinanceFundingRate>, ApiError> {
    let response = client
        .get(format!("{BINANCE_FAPI_API}/fapi/v1/fundingRate"))
        .query(&[
            ("symbol", symbol.to_string()),
            ("startTime", start_time.to_string()),
            ("endTime", end_time.to_string()),
            ("limit", limit.to_string()),
        ])
        .send()
        .await
        .map_err(|error| ApiError::upstream(format!("Failed to fetch funding rate: {error}")))?;

    if !response.status().is_success() {
        return Err(ApiError::upstream(format!(
            "Funding request returned {} for {symbol}.",
            response.status()
        )));
    }

    let rows: Vec<BinanceFundingRate> = response.json().await.map_err(|error| {
        ApiError::upstream(format!("Failed to decode funding payload: {error}"))
    })?;

    Ok(rows)
}

async fn fetch_futures_metric_snapshot(
    client: &Client,
    symbol: &str,
    signal_close_time: i64,
) -> Result<Option<FuturesMetricSnapshot>, ApiError> {
    let (open_interest_rows, global_rows, top_position_rows, taker_rows) = tokio::try_join!(
        fetch_open_interest_rows(client, symbol, 300),
        fetch_futures_ratio_rows(
            client,
            "/futures/data/globalLongShortAccountRatio",
            symbol,
            30
        ),
        fetch_futures_ratio_rows(
            client,
            "/futures/data/topLongShortPositionRatio",
            symbol,
            30
        ),
        fetch_futures_ratio_rows(client, "/futures/data/takerlongshortRatio", symbol, 30),
    )?;

    let Some((current_oi_value, current_oi_time)) =
        latest_open_interest_before(&open_interest_rows, signal_close_time)?
    else {
        return Ok(None);
    };
    let Some((global_ratio, global_time)) =
        latest_long_short_ratio_before(&global_rows, signal_close_time)?
    else {
        return Ok(None);
    };
    let Some((top_position_ratio, top_position_time)) =
        latest_long_short_ratio_before(&top_position_rows, signal_close_time)?
    else {
        return Ok(None);
    };
    let Some((taker_ratio, taker_time)) =
        latest_taker_ratio_before(&taker_rows, signal_close_time)?
    else {
        return Ok(None);
    };

    let max_age_ms = (ACTIVE_PAPER_STRATEGY_METRICS_MAX_AGE_MINUTES * 60.0 * 1000.0) as i64;
    for timestamp in [current_oi_time, global_time, top_position_time, taker_time] {
        let age_ms = signal_close_time - timestamp;
        if age_ms < 0 || age_ms > max_age_ms {
            return Ok(None);
        }
    }

    let previous_cutoff = signal_close_time - 24 * 60 * 60 * 1000;
    let open_interest_24h_change_pct =
        latest_open_interest_before(&open_interest_rows, previous_cutoff)?
            .and_then(|(previous_oi_value, _)| pct_change(previous_oi_value, current_oi_value));
    let timestamp = [current_oi_time, global_time, top_position_time, taker_time]
        .into_iter()
        .min()
        .unwrap_or(signal_close_time);

    Ok(Some(FuturesMetricSnapshot {
        timestamp,
        taker_buy_sell_ratio: taker_ratio,
        global_account_long_short_ratio: global_ratio,
        top_trader_position_long_short_ratio: top_position_ratio,
        open_interest_24h_change_pct,
    }))
}

async fn fetch_open_interest_rows(
    client: &Client,
    symbol: &str,
    limit: usize,
) -> Result<Vec<BinanceOpenInterestHist>, ApiError> {
    let response = client
        .get(format!("{BINANCE_FAPI_API}/futures/data/openInterestHist"))
        .query(&[
            ("symbol", symbol.to_string()),
            ("period", "5m".to_string()),
            ("limit", limit.to_string()),
        ])
        .send()
        .await
        .map_err(|error| {
            ApiError::upstream(format!("Failed to fetch open-interest history: {error}"))
        })?;

    if !response.status().is_success() {
        return Err(ApiError::upstream(format!(
            "Open-interest history request returned {} for {symbol}.",
            response.status()
        )));
    }

    response.json().await.map_err(|error| {
        ApiError::upstream(format!(
            "Failed to decode open-interest history payload: {error}"
        ))
    })
}

async fn fetch_futures_ratio_rows(
    client: &Client,
    path: &str,
    symbol: &str,
    limit: usize,
) -> Result<Vec<BinanceRatioRow>, ApiError> {
    let response = client
        .get(format!("{BINANCE_FAPI_API}{path}"))
        .query(&[
            ("symbol", symbol.to_string()),
            ("period", "5m".to_string()),
            ("limit", limit.to_string()),
        ])
        .send()
        .await
        .map_err(|error| ApiError::upstream(format!("Failed to fetch futures ratio: {error}")))?;

    if !response.status().is_success() {
        return Err(ApiError::upstream(format!(
            "Futures ratio request returned {} for {symbol}.",
            response.status()
        )));
    }

    response.json().await.map_err(|error| {
        ApiError::upstream(format!("Failed to decode futures ratio payload: {error}"))
    })
}

async fn build_basket_snapshot(
    client: &Client,
    symbol: &str,
    watchlist: &[String],
    signal_close_time: i64,
    selected_trigger_closed: &[Candle],
) -> (Option<BasketSnapshot>, Vec<String>) {
    let mut returns = Vec::new();
    let mut warnings = Vec::new();

    for basket_symbol in watchlist {
        let return_pct = if basket_symbol == symbol {
            trigger_return_pct(
                selected_trigger_closed,
                ACTIVE_PAPER_STRATEGY_BASKET_LOOKBACK_HOURS,
            )
        } else {
            match fetch_candles(client, basket_symbol, "15m", 120).await {
                Ok(candles) => {
                    let closed = closed_candles_until(&candles, signal_close_time, "15m");
                    trigger_return_pct(closed, ACTIVE_PAPER_STRATEGY_BASKET_LOOKBACK_HOURS)
                }
                Err(error) => {
                    warnings.push(format!(
                        "Basket scorecard je preskocil {basket_symbol}: {}.",
                        error.message
                    ));
                    None
                }
            }
        };

        if let Some(value) = return_pct {
            returns.push((basket_symbol.clone(), value));
        }
    }

    if returns.is_empty() {
        return (None, warnings);
    }

    let values: Vec<f64> = returns.iter().map(|(_, value)| *value).collect();
    let positive_share_pct = Some(
        values.iter().filter(|value| **value > 0.0).count() as f64 / values.len() as f64 * 100.0,
    );
    let relative_strength_percentile = returns
        .iter()
        .find(|(candidate_symbol, _)| candidate_symbol == symbol)
        .and_then(|(_, current)| percentile_rank(&values, *current));

    (
        Some(BasketSnapshot {
            relative_strength_percentile,
            positive_share_pct,
            sample_size: values.len(),
        }),
        warnings,
    )
}

fn evaluate_ai_scorecard_v2(
    strategy: PaperStrategy,
    symbol: &str,
    signal_close_time: i64,
    trigger_slice: &[Candle],
    btc_trend_slice: &[Candle],
    risk_plan: Option<&SignalRiskPlan>,
    fee_bps: f64,
    context: &ScorecardContext,
) -> AiScorecardEvaluation {
    let mut score = 0_i32;
    let mut components = Vec::new();
    let mut blockers = Vec::new();
    let warnings = context.warnings.clone();

    if symbol == BTC_REFERENCE_SYMBOL {
        blockers.push("exclude_btc".to_string());
        components.push(SignalCheck {
            label: "Approved universe".to_string(),
            passed: false,
            detail: "Promoted candidate excludes BTC entries; BTC ostaja referencni trg."
                .to_string(),
        });
    } else {
        components.push(SignalCheck {
            label: "Approved universe".to_string(),
            passed: true,
            detail: format!("{symbol} je dovoljen kot non-BTC paper kandidat."),
        });
    }

    let Some(plan) = risk_plan else {
        blockers.push("risk_plan".to_string());
        components.push(SignalCheck {
            label: "AI score v2".to_string(),
            passed: false,
            detail: format!(
                "Score 0/{min_score}; scorecard se izracuna sele po veljavnem setup risk planu.",
                min_score = strategy.min_score
            ),
        });
        return AiScorecardEvaluation {
            score,
            components,
            blockers,
            warnings,
        };
    };

    let session = session_bucket(signal_close_time);
    let session_points = match session {
        "london_ny_overlap" => 2,
        "london" => 1,
        "new_york" => -2,
        "off_hours" => -1,
        _ => 0,
    };
    score += session_points;
    components.push(SignalCheck {
        label: "Score session".to_string(),
        passed: session != "off_hours",
        detail: format!("{session}: {session_points:+} point(s)."),
    });

    let fee_drag = estimated_round_trip_fee_r(plan, fee_bps);
    let fee_points = if fee_drag <= 0.35 {
        1
    } else if fee_drag > ACTIVE_PAPER_STRATEGY_MAX_FEE_DRAG_R {
        -2
    } else {
        0
    };
    score += fee_points;
    if fee_drag > ACTIVE_PAPER_STRATEGY_MAX_FEE_DRAG_R {
        blockers.push("fee_drag".to_string());
    }
    components.push(SignalCheck {
        label: "Score fee drag".to_string(),
        passed: fee_drag <= ACTIVE_PAPER_STRATEGY_MAX_FEE_DRAG_R,
        detail: format!(
            "{fee_drag:.2}R estimated round-trip fee drag; max gate {:.2}R; {fee_points:+} point(s).",
            ACTIVE_PAPER_STRATEGY_MAX_FEE_DRAG_R
        ),
    });

    let stop_pct = plan.risk_per_unit / plan.entry;
    if stop_pct < ACTIVE_PAPER_STRATEGY_MIN_STOP_PCT {
        blockers.push("stop_too_tight".to_string());
    }
    components.push(SignalCheck {
        label: "Stop distance".to_string(),
        passed: stop_pct >= ACTIVE_PAPER_STRATEGY_MIN_STOP_PCT,
        detail: format!(
            "Stop distance {:.2}% of entry; minimum gate {:.2}%.",
            stop_pct * 100.0,
            ACTIVE_PAPER_STRATEGY_MIN_STOP_PCT * 100.0
        ),
    });

    let volume_rank = volume_percentile_rank(trigger_slice);
    let volume_points = match volume_rank {
        Some(rank) if (0.50..=0.90).contains(&rank) => 1,
        Some(rank) if rank >= 0.90 || rank < 0.20 => -1,
        _ => 0,
    };
    score += volume_points;
    components.push(SignalCheck {
        label: "Score volume".to_string(),
        passed: volume_points >= 0,
        detail: format!(
            "15m volume percentile {}; {volume_points:+} point(s).",
            format_optional_percentile(volume_rank)
        ),
    });

    let atr_multiple = atr_expansion_multiple(trigger_slice);
    let atr_points = match atr_multiple {
        Some(value) if value <= 1.10 => 1,
        Some(value) if value >= 1.50 => -1,
        _ => 0,
    };
    score += atr_points;
    components.push(SignalCheck {
        label: "Score ATR expansion".to_string(),
        passed: atr_points >= 0,
        detail: format!(
            "30-vs-90 ATR multiple {}; {atr_points:+} point(s).",
            format_optional_number(atr_multiple, 2)
        ),
    });

    let btc_24h = btc_return_pct(btc_trend_slice, 24.0);
    let btc_points = match btc_24h {
        Some(value) if (-5.0..=5.0).contains(&value) => 1,
        Some(value) if value < -10.0 => -2,
        Some(value) if value > 10.0 => -1,
        _ => 0,
    };
    score += btc_points;
    components.push(SignalCheck {
        label: "Score BTC 24h".to_string(),
        passed: btc_points >= 0,
        detail: format!(
            "BTC 24h return {}; {btc_points:+} point(s).",
            format_optional_signed_percent(btc_24h)
        ),
    });

    let relative_strength = context
        .basket
        .as_ref()
        .and_then(|basket| basket.relative_strength_percentile);
    let relative_points = match relative_strength {
        Some(value) if value >= 0.60 => 2,
        Some(value) if value <= 0.30 => -2,
        _ => 0,
    };
    score += relative_points;
    let basket_sample_size = context
        .basket
        .as_ref()
        .map(|basket| basket.sample_size)
        .unwrap_or(0);
    components.push(SignalCheck {
        label: "Score relative strength".to_string(),
        passed: relative_points >= 0,
        detail: format!(
            "24h relative-strength percentile {} across {basket_sample_size} symbols; {relative_points:+} point(s).",
            format_optional_percentile(relative_strength)
        ),
    });

    let basket_share = context
        .basket
        .as_ref()
        .and_then(|basket| basket.positive_share_pct);
    let breadth_points = match basket_share {
        Some(value) if value < 25.0 => -1,
        Some(value) if value > 70.0 => 1,
        _ => 0,
    };
    score += breadth_points;
    components.push(SignalCheck {
        label: "Score basket breadth".to_string(),
        passed: breadth_points >= 0,
        detail: format!(
            "Positive 24h basket share {}; {breadth_points:+} point(s).",
            format_optional_signed_percent(basket_share)
        ),
    });

    let funding_points = match context.funding_bps {
        Some((funding_bps, _)) if funding_bps >= -1.0 => 2,
        Some((funding_bps, _)) if funding_bps >= -2.0 => 1,
        Some((funding_bps, _)) if funding_bps < -5.0 => -3,
        Some(_) => -2,
        None => {
            blockers.push("funding_data".to_string());
            -2
        }
    };
    score += funding_points;
    components.push(SignalCheck {
        label: "Score funding".to_string(),
        passed: context.funding_bps.is_some() && funding_points >= 0,
        detail: match context.funding_bps {
            Some((funding_bps, funding_time)) => format!(
                "Funding {funding_bps:.2} bps at {}; {funding_points:+} point(s).",
                format_utc_time(funding_time)
            ),
            None => format!("Funding missing/stale; {funding_points:+} point(s)."),
        },
    });

    match &context.metrics {
        Some(metrics) => {
            let taker_points = if metrics.taker_buy_sell_ratio >= 1.25 {
                2
            } else if metrics.taker_buy_sell_ratio < 1.0 {
                -1
            } else {
                0
            };
            score += taker_points;
            components.push(SignalCheck {
                label: "Score taker pressure".to_string(),
                passed: taker_points >= 0,
                detail: format!(
                    "Taker buy/sell {:.2}; {taker_points:+} point(s).",
                    metrics.taker_buy_sell_ratio
                ),
            });

            let oi_points = match metrics.open_interest_24h_change_pct {
                Some(value) if (-10.0..=0.0).contains(&value) => 1,
                Some(value) if value > 2.0 || value < -15.0 => -1,
                _ => 0,
            };
            let oi_ablated = strategy.disables_score_component("oi");
            if !oi_ablated {
                score += oi_points;
            }
            components.push(SignalCheck {
                label: "Score OI change".to_string(),
                passed: oi_ablated || oi_points >= 0,
                detail: if oi_ablated {
                    format!(
                        "OI 24h change {}; raw {oi_points:+} point(s), ignored by {}.",
                        format_optional_signed_percent(metrics.open_interest_24h_change_pct),
                        strategy.version
                    )
                } else {
                    format!(
                        "OI 24h change {}; {oi_points:+} point(s).",
                        format_optional_signed_percent(metrics.open_interest_24h_change_pct)
                    )
                },
            });

            let global_points = if metrics.global_account_long_short_ratio <= 1.20 {
                2
            } else if metrics.global_account_long_short_ratio >= 2.00 {
                -2
            } else {
                0
            };
            score += global_points;
            components.push(SignalCheck {
                label: "Score global bias".to_string(),
                passed: global_points >= 0,
                detail: format!(
                    "Global account long/short {:.2}; {global_points:+} point(s).",
                    metrics.global_account_long_short_ratio
                ),
            });

            let top_position_points = if metrics.top_trader_position_long_short_ratio <= 1.40 {
                1
            } else if metrics.top_trader_position_long_short_ratio >= 2.00 {
                -1
            } else {
                0
            };
            score += top_position_points;
            components.push(SignalCheck {
                label: "Score top position".to_string(),
                passed: top_position_points >= 0,
                detail: format!(
                    "Top-trader position long/short {:.2} at {}; {top_position_points:+} point(s).",
                    metrics.top_trader_position_long_short_ratio,
                    format_utc_time(metrics.timestamp)
                ),
            });
        }
        None => {
            blockers.push("metrics_data".to_string());
            score -= 2;
            components.push(SignalCheck {
                label: "Score futures metrics".to_string(),
                passed: false,
                detail: "Futures 5m positioning metrics missing/stale; -2 point(s).".to_string(),
            });
        }
    }

    if score < strategy.min_score {
        blockers.push("score_below_7".to_string());
    }
    components.push(SignalCheck {
        label: "AI score v2".to_string(),
        passed: score >= strategy.min_score,
        detail: format!(
            "Score {score}/{min_score}; paper gate requires >= {min_score}.",
            min_score = strategy.min_score
        ),
    });

    AiScorecardEvaluation {
        score,
        components,
        blockers,
        warnings,
    }
}

fn latest_open_interest_before(
    rows: &[BinanceOpenInterestHist],
    cutoff_time: i64,
) -> Result<Option<(f64, i64)>, ApiError> {
    let mut latest: Option<(f64, i64)> = None;
    for row in rows {
        let timestamp = parse_json_i64(&row.timestamp)?;
        if timestamp > cutoff_time {
            continue;
        }
        let value = parse_f64(&row.sum_open_interest_value)?;
        if latest
            .map(|(_, current_time)| timestamp > current_time)
            .unwrap_or(true)
        {
            latest = Some((value, timestamp));
        }
    }
    Ok(latest)
}

fn latest_long_short_ratio_before(
    rows: &[BinanceRatioRow],
    cutoff_time: i64,
) -> Result<Option<(f64, i64)>, ApiError> {
    latest_ratio_before(rows, cutoff_time, |row| row.long_short_ratio.as_deref())
}

fn latest_taker_ratio_before(
    rows: &[BinanceRatioRow],
    cutoff_time: i64,
) -> Result<Option<(f64, i64)>, ApiError> {
    latest_ratio_before(rows, cutoff_time, |row| row.buy_sell_ratio.as_deref())
}

fn latest_ratio_before(
    rows: &[BinanceRatioRow],
    cutoff_time: i64,
    value_of: impl Fn(&BinanceRatioRow) -> Option<&str>,
) -> Result<Option<(f64, i64)>, ApiError> {
    let mut latest: Option<(f64, i64)> = None;
    for row in rows {
        let Some(raw_value) = value_of(row) else {
            continue;
        };
        let timestamp = parse_json_i64(&row.timestamp)?;
        if timestamp > cutoff_time {
            continue;
        }
        let value = parse_f64(raw_value)?;
        if latest
            .map(|(_, current_time)| timestamp > current_time)
            .unwrap_or(true)
        {
            latest = Some((value, timestamp));
        }
    }
    Ok(latest)
}

fn volume_percentile_rank(trigger_slice: &[Candle]) -> Option<f64> {
    if trigger_slice.len() < 100 {
        return None;
    }
    let lookback = &trigger_slice[trigger_slice.len() - 97..trigger_slice.len() - 1];
    percentile_rank(
        &lookback
            .iter()
            .map(|candle| candle.volume)
            .collect::<Vec<_>>(),
        trigger_slice.last()?.volume,
    )
}

fn atr_expansion_multiple(trigger_slice: &[Candle]) -> Option<f64> {
    if trigger_slice.len() < 120 {
        return None;
    }
    let recent_atr = calculate_atr(&trigger_slice[trigger_slice.len() - 30..], 14)?;
    let baseline_atr = calculate_atr(
        &trigger_slice[trigger_slice.len() - 120..trigger_slice.len() - 30],
        14,
    )?;
    if baseline_atr <= 0.0 {
        return None;
    }
    Some(recent_atr / baseline_atr)
}

fn btc_return_pct(btc_trend_slice: &[Candle], lookback_hours: f64) -> Option<f64> {
    let lookback_candles = (lookback_hours / 4.0).round().max(1.0) as usize;
    close_return_pct(btc_trend_slice, lookback_candles)
}

fn trigger_return_pct(candles: &[Candle], lookback_hours: f64) -> Option<f64> {
    let lookback_candles = (lookback_hours * 4.0).round().max(1.0) as usize;
    close_return_pct(candles, lookback_candles)
}

fn close_return_pct(candles: &[Candle], lookback_candles: usize) -> Option<f64> {
    if lookback_candles == 0 || candles.len() <= lookback_candles {
        return None;
    }
    let start = candles.get(candles.len() - lookback_candles - 1)?.close;
    let end = candles.last()?.close;
    pct_change(start, end)
}

fn pct_change(start: f64, end: f64) -> Option<f64> {
    if start == 0.0 || !start.is_finite() || !end.is_finite() {
        return None;
    }
    Some((end - start) / start * 100.0)
}

fn percentile_rank(values: &[f64], current: f64) -> Option<f64> {
    if values.is_empty() || !current.is_finite() {
        return None;
    }
    Some(values.iter().filter(|value| **value <= current).count() as f64 / values.len() as f64)
}

fn estimated_round_trip_fee_r(risk_plan: &SignalRiskPlan, fee_bps: f64) -> f64 {
    if risk_plan.risk_amount <= 0.0 {
        return 0.0;
    }
    let entry_fee = risk_plan.notional_estimate * fee_bps / 10_000.0;
    let estimated_exit_fee = risk_plan.suggested_quantity * risk_plan.entry * fee_bps / 10_000.0;
    (entry_fee + estimated_exit_fee) / risk_plan.risk_amount
}

fn session_bucket(timestamp_ms: i64) -> &'static str {
    let Some(timestamp) = DateTime::<Utc>::from_timestamp_millis(timestamp_ms) else {
        return "unknown";
    };
    match timestamp.hour() {
        7..=11 => "london",
        12..=15 => "london_ny_overlap",
        16..=21 => "new_york",
        _ => "off_hours",
    }
}

fn format_optional_number(value: Option<f64>, digits: usize) -> String {
    match value {
        Some(value) if value.is_finite() => format!("{value:.precision$}", precision = digits),
        _ => "n/a".to_string(),
    }
}

fn format_optional_percentile(value: Option<f64>) -> String {
    match value {
        Some(value) if value.is_finite() => format!("{:.0}%", value * 100.0),
        _ => "n/a".to_string(),
    }
}

fn format_optional_signed_percent(value: Option<f64>) -> String {
    match value {
        Some(value) if value.is_finite() => format!("{value:+.2}%"),
        _ => "n/a".to_string(),
    }
}

fn format_utc_time(timestamp_ms: i64) -> String {
    DateTime::<Utc>::from_timestamp_millis(timestamp_ms)
        .map(|timestamp| timestamp.format("%H:%M UTC").to_string())
        .unwrap_or_else(|| "unknown UTC".to_string())
}

fn utc_day_start_ms(timestamp_ms: i64) -> i64 {
    DateTime::<Utc>::from_timestamp_millis(timestamp_ms)
        .and_then(|timestamp| timestamp.date_naive().and_hms_opt(0, 0, 0))
        .map(|timestamp| timestamp.and_utc().timestamp_millis())
        .unwrap_or(timestamp_ms)
}

async fn build_signal_assistants(
    client: &Client,
    news_cache: &Arc<Mutex<HashMap<String, CachedNewsStatus>>>,
    watchlist: &[String],
    symbol: &str,
    current_price: f64,
    available_cash: f64,
    fee_bps: f64,
    generated_at: i64,
    strategies: &[PaperStrategy],
) -> Result<Vec<SignalAssistant>, ApiError> {
    let (trend_candles, setup_candles, trigger_candles) = tokio::try_join!(
        fetch_candles(client, symbol, "4h", 160),
        fetch_candles(client, symbol, "1h", 160),
        fetch_candles(client, symbol, "15m", 160),
    )?;
    let trend_closed = closed_candles_until(&trend_candles, generated_at, "4h");
    let setup_closed = closed_candles_until(&setup_candles, generated_at, "1h");
    let trigger_closed = closed_candles_until(&trigger_candles, generated_at, "15m");
    let evaluation = evaluate_signal(
        current_price,
        available_cash,
        fee_bps,
        trend_closed,
        setup_closed,
        trigger_closed,
    );
    let signal_close_time = trigger_closed
        .last()
        .map(|candle| candle.open_time + interval_millis("15m"))
        .unwrap_or(generated_at);
    let session_filter = evaluate_session_filter(signal_close_time);
    let mut btc_warning = None;
    let (btc_trend_candles, btc_trigger_candles) = if symbol == BTC_REFERENCE_SYMBOL {
        (Vec::new(), Vec::new())
    } else {
        match tokio::try_join!(
            fetch_candles(client, BTC_REFERENCE_SYMBOL, "4h", 160),
            fetch_candles(client, BTC_REFERENCE_SYMBOL, "15m", 160),
        ) {
            Ok(candles) => candles,
            Err(error) => {
                btc_warning = Some(format!(
                    "BTC kontekst ni preverjen, ker BTC podatki niso bili dosegljivi: {}.",
                    error.message
                ));
                (Vec::new(), Vec::new())
            }
        }
    };
    let btc_trend_closed = if symbol == BTC_REFERENCE_SYMBOL {
        trend_closed
    } else {
        closed_candles_until(&btc_trend_candles, signal_close_time, "4h")
    };
    let btc_trigger_closed = if symbol == BTC_REFERENCE_SYMBOL {
        trigger_closed
    } else {
        closed_candles_until(&btc_trigger_candles, signal_close_time, "15m")
    };
    let correlation_filter = if symbol == BTC_REFERENCE_SYMBOL {
        CorrelationFilterStatus {
            passed: true,
            detail:
                "BTC je referencni trg. Promoted scorecard BTC korelacije ne uporablja kot gate."
                    .to_string(),
        }
    } else if btc_warning.is_some() {
        CorrelationFilterStatus {
            passed: true,
            detail:
                "BTC correlation je samo diagnostika za promoted scorecard in trenutno ni na voljo."
                    .to_string(),
        }
    } else {
        let mut status = evaluate_correlation_filter(
            symbol,
            trigger_closed,
            btc_trend_closed,
            btc_trigger_closed,
        );
        status.detail = format!(
            "{} Promoted scorecard tega ne uporablja kot entry gate.",
            status.detail
        );
        status.passed = true;
        status
    };
    let news_filter = evaluate_news_filter(client, news_cache, symbol, generated_at).await;
    let mut scorecard_context = if evaluation.risk_plan.is_some() && symbol != BTC_REFERENCE_SYMBOL
    {
        fetch_scorecard_context(client, symbol, watchlist, signal_close_time, trigger_closed).await
    } else {
        ScorecardContext::empty()
    };
    if let Some(warning) = btc_warning {
        scorecard_context.warnings.push(warning);
    }

    Ok(strategies
        .iter()
        .map(|strategy| {
            build_signal_assistant_from_parts(
                *strategy,
                symbol,
                generated_at,
                signal_close_time,
                available_cash,
                fee_bps,
                setup_closed,
                trigger_closed,
                btc_trend_closed,
                &evaluation,
                &session_filter,
                &correlation_filter,
                &news_filter,
                &scorecard_context,
            )
        })
        .collect())
}

fn build_signal_assistant_from_parts(
    strategy: PaperStrategy,
    symbol: &str,
    generated_at: i64,
    signal_close_time: i64,
    available_cash: f64,
    fee_bps: f64,
    setup_closed: &[Candle],
    trigger_closed: &[Candle],
    btc_trend_closed: &[Candle],
    evaluation: &EvaluatedSignal,
    session_filter: &SessionFilterStatus,
    correlation_filter: &CorrelationFilterStatus,
    news_filter: &NewsFilterStatus,
    scorecard_context: &ScorecardContext,
) -> SignalAssistant {
    let scorecard = evaluate_ai_scorecard_v2(
        strategy,
        symbol,
        signal_close_time,
        trigger_closed,
        btc_trend_closed,
        evaluation.risk_plan.as_ref(),
        fee_bps,
        scorecard_context,
    );
    let filter_blockers = collect_filter_blockers(session_filter, news_filter, &scorecard);
    let paper_ready = matches!(evaluation.stage, SignalStage::Ready) && filter_blockers.is_empty();
    let stage = if matches!(evaluation.stage, SignalStage::Ready) && !paper_ready {
        SignalStage::Setup
    } else {
        evaluation.stage
    };
    let risk_detail = format_risk_detail(evaluation.risk_plan.as_ref());
    let journal_tags = build_journal_tags(
        strategy,
        evaluation.bias,
        stage,
        scorecard.score,
        &filter_blockers,
    );

    let mut warnings = vec![
        format!(
            "Paper testing je odobren za {strategy} ({role} paper bot); auto-paper uporablja en globalni slot in lokalne SQLite paper fille.",
            strategy = strategy.version,
            role = strategy.role
        ),
        "Risk plan uporablja 1% razpolozljivega paper casha na entry.".to_string(),
        "Scorecard zahteva sveze javne Binance USD-M funding/positioning podatke; manjkajoci ali zastareli podatki blokirajo entry."
            .to_string(),
        "News gate uporablja javne BEA/Fed/SEC/CoinDesk vire brez prijave kot dodaten live-only blackout filter."
            .to_string(),
    ];
    if !filter_blockers.is_empty() && matches!(evaluation.stage, SignalStage::Ready) {
        warnings.push(format!(
            "Tehnicni setup je READY, vendar promoted paper gate blokira entry: {}.",
            filter_blockers.join(", ")
        ));
    }
    warnings.extend(scorecard.warnings.iter().cloned());
    warnings.extend(news_filter.warnings.iter().cloned());
    if !strategy.disabled_score_components.is_empty() {
        warnings.push(format!(
            "{} ignorira score component(s): {}.",
            strategy.version,
            strategy.disabled_score_components.join(", ")
        ));
    }
    if available_cash <= 0.0 {
        warnings.push("Na paper racunu ni prostega casha za novo pozicijo.".to_string());
    }
    if evaluation.cash_capped {
        warnings.push(
            "Predlagana kolicina je omejena z razpolozljivim cashom, ne samo z 1% risk pravilom."
                .to_string(),
        );
    }
    if matches!(stage, SignalStage::Setup | SignalStage::Ready) && evaluation.risk_plan.is_none() {
        warnings.push(
            "Signal nima veljavnega risk plana. Pred oddajo orderja preveri entry, stop in kolicino."
                .to_string(),
        );
    }

    let stalk_ok = matches!(
        evaluation.stage,
        SignalStage::Stalk | SignalStage::Setup | SignalStage::Ready
    );
    let setup_ok = matches!(evaluation.stage, SignalStage::Setup | SignalStage::Ready);
    let trigger_ok = matches!(evaluation.stage, SignalStage::Ready);
    let mut checklist = vec![
        SignalCheck {
            label: "4h trend".to_string(),
            passed: matches!(evaluation.bias, SignalBias::Bullish),
            detail: format_structure_detail("4h", &evaluation.trend),
        },
        SignalCheck {
            label: "1h setup".to_string(),
            passed: setup_ok,
            detail: format_setup_detail(
                evaluation.stage,
                evaluation.support_level,
                evaluation.distance_to_support,
                calculate_atr(setup_closed, 14),
            ),
        },
        SignalCheck {
            label: "Reclaim state".to_string(),
            passed: stalk_ok,
            detail: format!(
                "{}: STALK pomeni <= {:.1} ATR od supporta; SETUP zahteva zaprt 1h reclaim nad supportom; READY zahteva se 15m momentum.",
                evaluation.stage.as_label(),
                SIGNAL_STALK_ATR_DISTANCE_MAX
            ),
        },
        SignalCheck {
            label: "15m trigger".to_string(),
            passed: trigger_ok,
            detail: format_trigger_detail(&evaluation.trigger),
        },
        SignalCheck {
            label: "Session filter".to_string(),
            passed: session_filter.passed,
            detail: session_filter.detail.clone(),
        },
        SignalCheck {
            label: "Correlation filter".to_string(),
            passed: correlation_filter.passed,
            detail: correlation_filter.detail.clone(),
        },
        SignalCheck {
            label: "News filter".to_string(),
            passed: news_filter.passed,
            detail: news_filter.detail.clone(),
        },
    ];
    checklist.extend(scorecard.components);
    checklist.push(SignalCheck {
        label: "Risk plan".to_string(),
        passed: evaluation.risk_plan.is_some(),
        detail: risk_detail,
    });

    let summary = build_signal_summary(
        strategy,
        symbol,
        evaluation.bias,
        evaluation.stage,
        stage,
        evaluation.support_level,
        &evaluation.trigger,
        scorecard.score,
        &filter_blockers,
    );

    SignalAssistant {
        symbol: symbol.to_string(),
        strategy_version: strategy.version,
        bias: evaluation.bias,
        stage,
        technical_stage: evaluation.stage,
        confidence: evaluation.confidence,
        ai_score: scorecard.score,
        summary,
        generated_at,
        signal_close_time,
        timeframes: SignalTimeframes {
            trend: "4h",
            setup: "1h",
            trigger: "15m + USD-M 5m",
        },
        checklist,
        risk_plan: if paper_ready {
            evaluation.risk_plan.clone()
        } else {
            None
        },
        warnings,
        journal_tags,
    }
}

async fn build_signal_replay(
    client: &Client,
    symbol: &str,
    fee_bps: f64,
    generated_at: i64,
) -> Result<ReplayResponse, ApiError> {
    let (trend_candles, setup_candles, trigger_candles) = tokio::try_join!(
        fetch_candles(client, symbol, "4h", 240),
        fetch_candles(client, symbol, "1h", 480),
        fetch_candles(client, symbol, "15m", SIGNAL_REPLAY_TRIGGER_LIMIT),
    )?;

    if trigger_candles.len() <= SIGNAL_REPLAY_FORWARD_CANDLES + 1 {
        return Err(ApiError::internal(
            "Ni dovolj trigger candle podatkov za replay.",
        ));
    }

    let (btc_trend_candles, btc_trigger_candles) = if symbol == BTC_REFERENCE_SYMBOL {
        (Vec::new(), Vec::new())
    } else {
        tokio::try_join!(
            fetch_candles(client, BTC_REFERENCE_SYMBOL, "4h", 240),
            fetch_candles(
                client,
                BTC_REFERENCE_SYMBOL,
                "15m",
                SIGNAL_REPLAY_TRIGGER_LIMIT
            ),
        )?
    };

    let mut ready_signals = 0_usize;
    let mut setup_signals = 0_usize;
    let mut tp1_hits = 0_usize;
    let mut tp2_hits = 0_usize;
    let mut stop_losses = 0_usize;
    let mut breakeven_exits = 0_usize;
    let mut timeout_exits = 0_usize;
    let mut total_r = 0.0_f64;
    let mut recent_trades = Vec::new();
    let mut session_filtered = 0_usize;
    let mut correlation_filtered = 0_usize;

    for index in 0..trigger_candles
        .len()
        .saturating_sub(SIGNAL_REPLAY_FORWARD_CANDLES + 1)
    {
        let signal_candle = &trigger_candles[index];
        let signal_close_time = signal_candle.open_time + interval_millis("15m");
        let trend_slice = closed_candles_until(&trend_candles, signal_close_time, "4h");
        let setup_slice = closed_candles_until(&setup_candles, signal_close_time, "1h");
        let trigger_slice = &trigger_candles[..=index];

        let evaluation = evaluate_signal(
            signal_candle.close,
            SIGNAL_REPLAY_BASE_CAPITAL,
            fee_bps,
            trend_slice,
            setup_slice,
            trigger_slice,
        );

        if matches!(
            evaluation.stage,
            SignalStage::Stalk | SignalStage::Setup | SignalStage::Ready
        ) {
            setup_signals += 1;
        }

        let Some(risk_plan) = evaluation.risk_plan else {
            continue;
        };
        if !matches!(evaluation.stage, SignalStage::Ready) {
            continue;
        }

        let session_filter = evaluate_session_filter(signal_close_time);
        if !session_filter.passed {
            session_filtered += 1;
            continue;
        }
        if symbol != BTC_REFERENCE_SYMBOL {
            let btc_trend_slice = closed_candles_until(&btc_trend_candles, signal_close_time, "4h");
            let btc_trigger_slice =
                closed_candles_until(&btc_trigger_candles, signal_close_time, "15m");
            let correlation_filter = evaluate_correlation_filter(
                symbol,
                trigger_slice,
                btc_trend_slice,
                btc_trigger_slice,
            );
            if !correlation_filter.passed {
                correlation_filtered += 1;
                continue;
            }
        }

        ready_signals += 1;
        let future_slice = &trigger_candles[index + 1..=index + SIGNAL_REPLAY_FORWARD_CANDLES];
        let trade = simulate_replay_trade(
            signal_close_time,
            evaluation.confidence,
            &risk_plan,
            future_slice,
        );

        match trade.outcome {
            ReplayOutcome::StopLoss => stop_losses += 1,
            ReplayOutcome::TakeProfit2 => {
                tp1_hits += 1;
                tp2_hits += 1;
            }
            ReplayOutcome::Breakeven => {
                tp1_hits += 1;
                breakeven_exits += 1;
            }
            ReplayOutcome::Timeout => timeout_exits += 1,
        }

        total_r += trade.realized_r;
        recent_trades.push(trade);
    }

    recent_trades.reverse();
    recent_trades.truncate(8);

    let win_rate_percent = if ready_signals > 0 {
        (tp1_hits as f64 / ready_signals as f64) * 100.0
    } else {
        0.0
    };
    let average_r = if ready_signals > 0 {
        total_r / ready_signals as f64
    } else {
        0.0
    };

    Ok(ReplayResponse {
        symbol: symbol.to_string(),
        generated_at,
        lookback_trigger_candles: trigger_candles.len(),
        forward_trigger_candles: SIGNAL_REPLAY_FORWARD_CANDLES,
        ready_signals,
        setup_signals,
        tp1_hits,
        tp2_hits,
        stop_losses,
        breakeven_exits,
        timeout_exits,
        win_rate_percent,
        average_r,
        total_r,
        notes: vec![
            "Replay uporablja zaprte 4h, 1h in 15m svecke. In-progress candle ni vkljucen."
                .to_string(),
            "Signal vstopi po close-u 15m trigger svecke. Forward pregled uporablja naslednjih 32 x 15m sveck."
                .to_string(),
            "Po TP1 se simulira zaprtje 50% pozicije in premik preostanka na break-even. Ce TP2 in BE padeta v isti svecki, replay izbere bolj konzervativen izhod."
                .to_string(),
            format!(
                "Replay zdaj uposteva session gate (07:00-22:00 UTC) in BTC correlation gate. Session je zavrnil {session_filtered} tehnicno READY signalov, correlation pa {correlation_filtered}."
            ),
            format!(
                "V2 reclaim pravilo steje STALK/SETUP/READY kandidate: STALK <= {:.1} ATR od supporta, SETUP zaprt 1h reclaim, READY se 15m momentum po reclaimu.",
                SIGNAL_STALK_ATR_DISTANCE_MAX
            ),
            "News blackout ostaja live-only, ker javni RSS viri niso zgodovinski feed za reproducibilen replay."
                .to_string(),
        ],
        recent_trades,
    })
}

fn collect_filter_blockers(
    session_filter: &SessionFilterStatus,
    news_filter: &NewsFilterStatus,
    scorecard: &AiScorecardEvaluation,
) -> Vec<String> {
    let mut blockers = Vec::new();
    if !session_filter.passed {
        blockers.push("session".to_string());
    }
    if !news_filter.passed {
        blockers.push("news".to_string());
    }
    blockers.extend(scorecard.blockers.iter().cloned());
    blockers
}

fn evaluate_session_filter(timestamp_ms: i64) -> SessionFilterStatus {
    let Some(timestamp) = DateTime::<Utc>::from_timestamp_millis(timestamp_ms) else {
        return SessionFilterStatus {
            passed: false,
            detail: "Session gate ni uspel razbrati UTC casa.".to_string(),
        };
    };
    let hour = timestamp.hour();
    let minute = timestamp.minute();
    let window_label = if (12..16).contains(&hour) {
        "London/New York overlap"
    } else if (SIGNAL_SESSION_START_HOUR_UTC..12).contains(&hour) {
        "London session"
    } else if (16..SIGNAL_SESSION_END_HOUR_UTC).contains(&hour) {
        "New York session"
    } else {
        "Asia / off-hours"
    };
    let weekend_note = if matches!(
        timestamp.weekday(),
        chrono::Weekday::Sat | chrono::Weekday::Sun
    ) {
        " Vikend obicajno prinese manj konsistentno likvidnost."
    } else {
        ""
    };
    let passed = (SIGNAL_SESSION_START_HOUR_UTC..SIGNAL_SESSION_END_HOUR_UTC).contains(&hour);
    let detail = if passed {
        format!(
            "{window_label} ({hour:02}:{minute:02} UTC). Novi entryji so dovoljeni med 07:00 in 22:00 UTC.{weekend_note}"
        )
    } else {
        format!(
            "{window_label} ({hour:02}:{minute:02} UTC). Novi entryji so blokirani zunaj 07:00-22:00 UTC.{weekend_note}"
        )
    };

    SessionFilterStatus { passed, detail }
}

fn evaluate_correlation_filter(
    symbol: &str,
    symbol_trigger_candles: &[Candle],
    btc_trend_candles: &[Candle],
    btc_trigger_candles: &[Candle],
) -> CorrelationFilterStatus {
    if symbol == BTC_REFERENCE_SYMBOL {
        return CorrelationFilterStatus {
            passed: true,
            detail: "BTC je referencni trg, zato se BTC-vs-BTC correlation gate preskoci."
                .to_string(),
        };
    }

    let btc_bias = analyze_structure(btc_trend_candles, 2).bias;
    match calculate_return_correlation(
        symbol_trigger_candles,
        btc_trigger_candles,
        SIGNAL_CORRELATION_LOOKBACK_RETURNS,
    ) {
        Some(correlation)
            if correlation >= SIGNAL_CORRELATION_THRESHOLD
                && !matches!(btc_bias, SignalBias::Bullish) =>
        {
            CorrelationFilterStatus {
                passed: false,
                detail: format!(
                    "{symbol} je {:.2} koreliran z BTC, BTC 4h bias pa je {}.",
                    correlation,
                    btc_bias.as_label()
                ),
            }
        }
        Some(correlation) if correlation >= SIGNAL_CORRELATION_THRESHOLD => {
            CorrelationFilterStatus {
                passed: true,
                detail: format!(
                    "{symbol} je {:.2} koreliran z BTC, vendar BTC 4h ostaja bullish.",
                    correlation
                ),
            }
        }
        Some(correlation) => CorrelationFilterStatus {
            passed: true,
            detail: format!(
                "Korelacija z BTC je {:.2}, kar ostaja pod pragom {:.2}.",
                correlation, SIGNAL_CORRELATION_THRESHOLD
            ),
        },
        None => CorrelationFilterStatus {
            passed: false,
            detail: "Ni dovolj poravnanih 15m donosov za BTC correlation gate.".to_string(),
        },
    }
}

fn calculate_return_correlation(
    left: &[Candle],
    right: &[Candle],
    lookback_returns: usize,
) -> Option<f64> {
    let left_returns = close_returns_by_time(left);
    let right_returns = close_returns_by_time(right);
    if left_returns.is_empty() || right_returns.is_empty() {
        return None;
    }

    let right_map: HashMap<i64, f64> = right_returns.into_iter().collect();
    let mut xs = Vec::new();
    let mut ys = Vec::new();

    for (timestamp, left_return) in left_returns.into_iter().rev() {
        if let Some(right_return) = right_map.get(&timestamp) {
            xs.push(left_return);
            ys.push(*right_return);
            if xs.len() >= lookback_returns {
                break;
            }
        }
    }

    xs.reverse();
    ys.reverse();
    if xs.len() < SIGNAL_CORRELATION_MIN_SAMPLES {
        return None;
    }

    pearson_correlation(&xs, &ys)
}

fn close_returns_by_time(candles: &[Candle]) -> Vec<(i64, f64)> {
    candles
        .windows(2)
        .filter_map(|window| {
            let previous = &window[0];
            let current = &window[1];
            if previous.close <= 0.0 {
                return None;
            }

            Some((
                current.open_time,
                (current.close - previous.close) / previous.close,
            ))
        })
        .collect()
}

fn pearson_correlation(xs: &[f64], ys: &[f64]) -> Option<f64> {
    if xs.len() != ys.len() || xs.len() < 2 {
        return None;
    }

    let mean_x = xs.iter().sum::<f64>() / xs.len() as f64;
    let mean_y = ys.iter().sum::<f64>() / ys.len() as f64;
    let mut covariance = 0.0_f64;
    let mut variance_x = 0.0_f64;
    let mut variance_y = 0.0_f64;

    for (x, y) in xs.iter().zip(ys.iter()) {
        let dx = x - mean_x;
        let dy = y - mean_y;
        covariance += dx * dy;
        variance_x += dx * dx;
        variance_y += dy * dy;
    }

    let denominator = (variance_x * variance_y).sqrt();
    if denominator <= 1e-12 {
        return None;
    }

    Some((covariance / denominator).clamp(-1.0, 1.0))
}

async fn evaluate_news_filter(
    client: &Client,
    news_cache: &Arc<Mutex<HashMap<String, CachedNewsStatus>>>,
    symbol: &str,
    now_ms: i64,
) -> NewsFilterStatus {
    if let Ok(cache) = news_cache.lock() {
        if let Some(cached) = cache.get(symbol) {
            let age_ms = now_ms.saturating_sub(cached.fetched_at);
            if age_ms <= NEWS_CACHE_TTL_MINUTES * 60_000 {
                return cached.status.clone();
            }
        }
    }

    let status = match fetch_news_filter_status(client, symbol, now_ms).await {
        Ok(status) => status,
        Err(error) => NewsFilterStatus {
            passed: false,
            detail: "News blackout ni popoln, ker javni viri trenutno niso dosegljivi.".to_string(),
            warnings: vec![format!("News filter napaka: {}", error.message)],
        },
    };

    if let Ok(mut cache) = news_cache.lock() {
        cache.insert(
            symbol.to_string(),
            CachedNewsStatus {
                fetched_at: now_ms,
                status: status.clone(),
            },
        );
    }

    status
}

async fn fetch_news_filter_status(
    client: &Client,
    symbol: &str,
    now_ms: i64,
) -> Result<NewsFilterStatus, ApiError> {
    let (bea_result, fed_result, sec_result, coindesk_result) = tokio::join!(
        fetch_bea_blackout_events(client, now_ms),
        fetch_fed_blackout_events(client, now_ms),
        fetch_sec_blackout_events(client, symbol, now_ms),
        fetch_coindesk_blackout_events(client, symbol, now_ms),
    );

    let mut source_failures = Vec::new();
    let mut active_events = Vec::new();

    match bea_result {
        Ok(events) => active_events.extend(events),
        Err(error) => source_failures.push(format!("BEA schedule ni dosegljiv: {}", error.message)),
    }
    match fed_result {
        Ok(events) => active_events.extend(events),
        Err(error) => {
            source_failures.push(format!("Fed monetary RSS ni dosegljiv: {}", error.message))
        }
    }
    match sec_result {
        Ok(events) => active_events.extend(events),
        Err(error) => source_failures.push(format!("SEC RSS ni dosegljiv: {}", error.message)),
    }

    let mut warnings = Vec::new();
    match coindesk_result {
        Ok(events) => active_events.extend(events),
        Err(error) => warnings.push(format!(
            "CoinDesk soft feed ni dosegljiv, zato je breaking-news plast oslabljena: {}.",
            error.message
        )),
    }

    if !source_failures.is_empty() {
        warnings.extend(source_failures);
        return Ok(NewsFilterStatus {
            passed: false,
            detail: "News blackout ni popoln, ker obvezni javni viri niso bili dosegljivi."
                .to_string(),
            warnings,
        });
    }

    if !active_events.is_empty() {
        warnings.extend(
            active_events
                .iter()
                .take(3)
                .map(|event| format!("News blackout: {event}")),
        );
        return Ok(NewsFilterStatus {
            passed: false,
            detail: format!("Aktiven blackout dogodek: {}", active_events[0]),
            warnings,
        });
    }

    Ok(NewsFilterStatus {
        passed: true,
        detail: "Ni aktivnega BEA/Fed/SEC/CoinDesk blackout dogodka.".to_string(),
        warnings,
    })
}

async fn fetch_bea_blackout_events(client: &Client, now_ms: i64) -> Result<Vec<String>, ApiError> {
    let payload = client
        .get(BEA_RELEASE_SCHEDULE_URL)
        .send()
        .await
        .map_err(|error| ApiError::upstream(format!("BEA request failed: {error}")))?
        .error_for_status()
        .map_err(|error| ApiError::upstream(format!("BEA returned an error: {error}")))?
        .json::<serde_json::Value>()
        .await
        .map_err(|error| ApiError::upstream(format!("BEA JSON parse failed: {error}")))?;

    let important_reports = [
        ("Gross Domestic Product", "BEA GDP"),
        (
            "Personal Income and Outlays",
            "BEA Personal Income and Outlays (PCE)",
        ),
        (
            "U.S. International Trade in Goods and Services",
            "BEA U.S. International Trade",
        ),
    ];
    let mut active_events = Vec::new();
    let lead_window_ms = NEWS_SCHEDULE_LOOKAHEAD_MINUTES * 60_000;
    let lag_window_ms = NEWS_RELEASE_BLACKOUT_MINUTES * 60_000;

    for (report_name, short_label) in important_reports {
        let Some(value) = payload.get(report_name) else {
            continue;
        };
        let series: BeaReleaseSeries = serde_json::from_value(value.clone())
            .map_err(|error| ApiError::upstream(format!("BEA payload shape changed: {error}")))?;
        for release_date in series.release_dates {
            let Ok(release_time) = DateTime::parse_from_rfc3339(&release_date) else {
                continue;
            };
            let release_ms = release_time.timestamp_millis();
            let delta = release_ms - now_ms;
            if (-lag_window_ms..=lead_window_ms).contains(&delta) {
                active_events.push(format!(
                    "{} {}",
                    short_label,
                    format_relative_event_timing(release_ms, now_ms)
                ));
            }
        }
    }

    Ok(active_events)
}

async fn fetch_fed_blackout_events(client: &Client, now_ms: i64) -> Result<Vec<String>, ApiError> {
    let headlines = fetch_rss_headlines(client, FED_MONETARY_RSS_URL).await?;
    Ok(headlines
        .into_iter()
        .filter(|headline| {
            is_recent_timestamp(
                headline.published_at,
                now_ms,
                NEWS_HEADLINE_BLACKOUT_MINUTES,
            )
        })
        .map(|headline| {
            format!(
                "Fed monetary release: {} ({}).",
                headline.title,
                format_relative_minutes(headline.published_at, now_ms)
            )
        })
        .collect())
}

async fn fetch_sec_blackout_events(
    client: &Client,
    symbol: &str,
    now_ms: i64,
) -> Result<Vec<String>, ApiError> {
    let headlines = fetch_rss_headlines(client, SEC_PRESS_RSS_URL).await?;
    Ok(headlines
        .into_iter()
        .filter(|headline| {
            is_recent_timestamp(
                headline.published_at,
                now_ms,
                NEWS_HEADLINE_BLACKOUT_MINUTES,
            ) && is_sec_crypto_headline(&headline.title, symbol)
        })
        .map(|headline| {
            format!(
                "SEC release: {} ({}).",
                headline.title,
                format_relative_minutes(headline.published_at, now_ms)
            )
        })
        .collect())
}

async fn fetch_coindesk_blackout_events(
    client: &Client,
    symbol: &str,
    now_ms: i64,
) -> Result<Vec<String>, ApiError> {
    let headlines = fetch_rss_headlines(client, COINDESK_RSS_URL).await?;
    Ok(headlines
        .into_iter()
        .filter(|headline| {
            is_recent_timestamp(headline.published_at, now_ms, NEWS_SOFT_BLACKOUT_MINUTES)
                && is_soft_crypto_breaking_headline(&headline.title, symbol)
        })
        .map(|headline| {
            format!(
                "CoinDesk alert: {} ({}).",
                headline.title,
                format_relative_minutes(headline.published_at, now_ms)
            )
        })
        .collect())
}

async fn fetch_rss_headlines(client: &Client, url: &str) -> Result<Vec<NewsHeadline>, ApiError> {
    let body = client
        .get(url)
        .send()
        .await
        .map_err(|error| ApiError::upstream(format!("RSS request failed for {url}: {error}")))?
        .error_for_status()
        .map_err(|error| ApiError::upstream(format!("RSS returned an error for {url}: {error}")))?
        .text()
        .await
        .map_err(|error| ApiError::upstream(format!("RSS body read failed for {url}: {error}")))?;

    let document: RssDocument = from_str(body.trim_start_matches('\u{feff}'))
        .map_err(|error| ApiError::upstream(format!("RSS parse failed for {url}: {error}")))?;

    Ok(document
        .channel
        .item
        .into_iter()
        .filter_map(|item| {
            let title = item.title?.trim().to_string();
            if title.is_empty() {
                return None;
            }
            let published_at = parse_news_timestamp(item.pub_date.as_deref()?)?;
            Some(NewsHeadline {
                title,
                published_at,
            })
        })
        .collect())
}

fn parse_news_timestamp(raw: &str) -> Option<i64> {
    DateTime::parse_from_rfc2822(raw)
        .map(|timestamp| timestamp.timestamp_millis())
        .or_else(|_| {
            DateTime::parse_from_rfc3339(raw).map(|timestamp| timestamp.timestamp_millis())
        })
        .ok()
}

fn is_recent_timestamp(timestamp_ms: i64, now_ms: i64, max_age_minutes: i64) -> bool {
    let max_age_ms = max_age_minutes * 60_000;
    let age = now_ms - timestamp_ms;
    (0..=max_age_ms).contains(&age)
}

fn is_sec_crypto_headline(title: &str, symbol: &str) -> bool {
    let lowercase = title.to_ascii_lowercase();
    let crypto_keywords = [
        "crypto",
        "bitcoin",
        "ethereum",
        "solana",
        "binance",
        "bnb",
        "coinbase",
        "digital asset",
        "stablecoin",
        "etf",
        "blockchain",
        "token",
    ];

    contains_any(&lowercase, &crypto_keywords)
        || symbol_news_terms(symbol)
            .iter()
            .any(|term| lowercase.contains(term.as_str()))
}

fn is_soft_crypto_breaking_headline(title: &str, symbol: &str) -> bool {
    let lowercase = title.to_ascii_lowercase();
    let broad_market_keywords = [
        "hack",
        "exploit",
        "breach",
        "outage",
        "liquidation",
        "stablecoin",
        "tariff",
        "inflation",
        "cpi",
        "pce",
        "fed",
        "powell",
        "sec",
    ];
    let symbol_scoped_keywords = [
        "etf",
        "approval",
        "lawsuit",
        "delist",
        "listing",
        "token unlock",
    ];
    let symbol_match = symbol_news_terms(symbol)
        .iter()
        .any(|term| lowercase.contains(term.as_str()));

    contains_any(&lowercase, &broad_market_keywords)
        || (symbol_match && contains_any(&lowercase, &symbol_scoped_keywords))
}

fn contains_any(haystack: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| haystack.contains(needle))
}

fn symbol_news_terms(symbol: &str) -> Vec<String> {
    match symbol {
        "BTCUSDT" => vec![
            "bitcoin".to_string(),
            "btc".to_string(),
            "spot bitcoin".to_string(),
        ],
        "ETHUSDT" => vec![
            "ethereum".to_string(),
            "eth".to_string(),
            "ether".to_string(),
        ],
        "SOLUSDT" => vec!["solana".to_string(), "sol".to_string()],
        "BNBUSDT" => vec![
            "bnb".to_string(),
            "binance".to_string(),
            "binance coin".to_string(),
        ],
        _ => vec![symbol
            .strip_suffix("USDT")
            .unwrap_or(symbol)
            .to_ascii_lowercase()],
    }
}

fn format_relative_event_timing(event_ms: i64, now_ms: i64) -> String {
    let clock = DateTime::<Utc>::from_timestamp_millis(event_ms)
        .map(|timestamp| timestamp.format("%H:%M UTC").to_string())
        .unwrap_or_else(|| "neznan UTC cas".to_string());
    if event_ms >= now_ms {
        format!(
            "izide ob {clock} ({}).",
            format_relative_minutes(event_ms, now_ms)
        )
    } else {
        format!(
            "je izsel ob {clock} ({}).",
            format_relative_minutes(event_ms, now_ms)
        )
    }
}

fn format_relative_minutes(event_ms: i64, now_ms: i64) -> String {
    let minutes = ((event_ms - now_ms).abs() / 60_000).max(1);
    if event_ms >= now_ms {
        format!("cez {minutes} min")
    } else {
        format!("pred {minutes} min")
    }
}

fn evaluate_signal(
    current_price: f64,
    available_cash: f64,
    fee_bps: f64,
    trend_candles: &[Candle],
    setup_candles: &[Candle],
    trigger_candles: &[Candle],
) -> EvaluatedSignal {
    let trend = analyze_structure(trend_candles, 2);
    let setup = analyze_structure(setup_candles, 2);
    let atr_1h = calculate_atr(setup_candles, 14);
    let atr_15m = calculate_atr(trigger_candles, 14);
    let support_level = match (setup.last_pivot_low, setup.previous_pivot_high) {
        (Some(last_low), Some(previous_high)) => Some(last_low.max(previous_high)),
        (Some(last_low), None) => Some(last_low),
        (None, Some(previous_high)) => Some(previous_high),
        (None, None) => None,
    };
    let setup_reference_price = setup_candles
        .last()
        .map(|candle| candle.close)
        .unwrap_or(current_price);
    let distance_to_support = support_level.map(|support| setup_reference_price - support);
    let trend_ok = matches!(trend.bias, SignalBias::Bullish);
    let setup_bias_ok = matches!(setup.bias, SignalBias::Bullish | SignalBias::Neutral);
    let near_support = distance_to_support
        .zip(atr_1h)
        .map(|(distance, atr)| distance.abs() <= atr * SIGNAL_STALK_ATR_DISTANCE_MAX)
        .unwrap_or(false);
    let reclaim_ok = distance_to_support
        .zip(atr_1h)
        .map(|(distance, atr)| distance >= 0.0 && distance <= atr * SIGNAL_RECLAIM_ATR_DISTANCE_MAX)
        .unwrap_or(false);
    let stalk_ok = trend_ok && setup_bias_ok && support_level.is_some() && near_support;
    let setup_ok = trend_ok && setup_bias_ok && support_level.is_some() && reclaim_ok;

    let trigger = analyze_trigger(trigger_candles);
    let trigger_ok = setup_ok && trigger.momentum_close;
    let (risk_plan, cash_capped) = if setup_ok {
        build_risk_plan(
            current_price,
            support_level,
            atr_1h,
            atr_15m,
            available_cash,
            fee_bps,
        )
    } else {
        (None, false)
    };

    let stage = if trend_ok && setup_ok && trigger_ok && risk_plan.is_some() {
        SignalStage::Ready
    } else if trend_ok && setup_ok {
        SignalStage::Setup
    } else if stalk_ok {
        SignalStage::Stalk
    } else {
        SignalStage::Wait
    };

    let confidence = calculate_signal_confidence(
        trend_ok,
        stalk_ok,
        setup_ok,
        trigger_ok,
        risk_plan.is_some(),
    );

    EvaluatedSignal {
        bias: trend.bias,
        stage,
        confidence,
        trend,
        support_level,
        distance_to_support,
        trigger,
        risk_plan,
        cash_capped,
    }
}

fn unavailable_signal_assistant(
    strategy: PaperStrategy,
    symbol: &str,
    generated_at: i64,
    reason: String,
) -> SignalAssistant {
    SignalAssistant {
        symbol: symbol.to_string(),
        strategy_version: strategy.version,
        bias: SignalBias::Neutral,
        stage: SignalStage::Wait,
        technical_stage: SignalStage::Wait,
        confidence: 0,
        ai_score: 0,
        summary: "Signal assistant trenutno ni na voljo.".to_string(),
        generated_at,
        signal_close_time: generated_at,
        timeframes: SignalTimeframes {
            trend: "4h",
            setup: "1h",
            trigger: "15m + USD-M 5m",
        },
        checklist: Vec::new(),
        risk_plan: None,
        warnings: vec![reason],
        journal_tags: vec!["assistant_unavailable".to_string()],
    }
}

fn analyze_structure(candles: &[Candle], span: usize) -> StructureSnapshot {
    let highs = find_pivot_highs(candles, span);
    let lows = find_pivot_lows(candles, span);
    let previous_pivot_high = highs.iter().rev().nth(1).map(|(_, price)| *price);
    let last_pivot_high = highs.last().map(|(_, price)| *price);
    let previous_pivot_low = lows.iter().rev().nth(1).map(|(_, price)| *price);
    let last_pivot_low = lows.last().map(|(_, price)| *price);
    let slope_up = candles
        .last()
        .zip(candles.get(candles.len().saturating_sub(13)))
        .map(|(last, earlier)| last.close > earlier.close)
        .unwrap_or(false);
    let slope_down = candles
        .last()
        .zip(candles.get(candles.len().saturating_sub(13)))
        .map(|(last, earlier)| last.close < earlier.close)
        .unwrap_or(false);

    let bullish = previous_pivot_high
        .zip(last_pivot_high)
        .zip(previous_pivot_low.zip(last_pivot_low))
        .map(|((prev_high, last_high), (prev_low, last_low))| {
            last_high > prev_high && last_low > prev_low && slope_up
        })
        .unwrap_or(false);
    let bearish = previous_pivot_high
        .zip(last_pivot_high)
        .zip(previous_pivot_low.zip(last_pivot_low))
        .map(|((prev_high, last_high), (prev_low, last_low))| {
            last_high < prev_high && last_low < prev_low && slope_down
        })
        .unwrap_or(false);

    let bias = if bullish {
        SignalBias::Bullish
    } else if bearish {
        SignalBias::Bearish
    } else {
        SignalBias::Neutral
    };

    StructureSnapshot {
        bias,
        last_pivot_high,
        previous_pivot_high,
        last_pivot_low,
        previous_pivot_low,
        slope_up,
    }
}

fn find_pivot_highs(candles: &[Candle], span: usize) -> Vec<(usize, f64)> {
    let mut pivots = Vec::new();
    if candles.len() < span * 2 + 1 {
        return pivots;
    }

    for index in span..(candles.len() - span) {
        let price = candles[index].high;
        let is_pivot = (index - span..=index + span)
            .all(|candidate| candidate == index || candles[candidate].high < price);
        if is_pivot {
            pivots.push((index, price));
        }
    }

    pivots
}

fn find_pivot_lows(candles: &[Candle], span: usize) -> Vec<(usize, f64)> {
    let mut pivots = Vec::new();
    if candles.len() < span * 2 + 1 {
        return pivots;
    }

    for index in span..(candles.len() - span) {
        let price = candles[index].low;
        let is_pivot = (index - span..=index + span)
            .all(|candidate| candidate == index || candles[candidate].low > price);
        if is_pivot {
            pivots.push((index, price));
        }
    }

    pivots
}

fn calculate_atr(candles: &[Candle], period: usize) -> Option<f64> {
    if candles.len() <= period {
        return None;
    }

    let mut true_ranges = Vec::with_capacity(candles.len().saturating_sub(1));
    for index in 1..candles.len() {
        let current = &candles[index];
        let previous_close = candles[index - 1].close;
        let range_1 = current.high - current.low;
        let range_2 = (current.high - previous_close).abs();
        let range_3 = (current.low - previous_close).abs();
        true_ranges.push(range_1.max(range_2).max(range_3));
    }

    let atr_slice = &true_ranges[true_ranges.len().saturating_sub(period)..];
    Some(atr_slice.iter().sum::<f64>() / atr_slice.len() as f64)
}

#[derive(Debug)]
struct TriggerSnapshot {
    momentum_close: bool,
    close_above_previous_high: bool,
    body_ratio: f64,
    close_location: f64,
}

fn closed_candles_until<'a>(
    candles: &'a [Candle],
    cutoff_time: i64,
    interval: &str,
) -> &'a [Candle] {
    let millis = interval_millis(interval);
    let count = candles.partition_point(|candle| candle.open_time + millis <= cutoff_time);
    &candles[..count]
}

fn interval_millis(interval: &str) -> i64 {
    match interval {
        "1m" => 60_000,
        "5m" => 5 * 60_000,
        "15m" => 15 * 60_000,
        "1h" => 60 * 60_000,
        "4h" => 4 * 60 * 60_000,
        _ => 60_000,
    }
}

fn analyze_trigger(candles: &[Candle]) -> TriggerSnapshot {
    let Some(last) = candles.last() else {
        return TriggerSnapshot {
            momentum_close: false,
            close_above_previous_high: false,
            body_ratio: 0.0,
            close_location: 0.0,
        };
    };
    let previous = candles.iter().rev().nth(1);
    let range = (last.high - last.low).max(1e-9);
    let body_ratio = ((last.close - last.open).abs() / range).clamp(0.0, 1.0);
    let close_location = ((last.close - last.low) / range).clamp(0.0, 1.0);
    let close_above_previous_high = previous
        .map(|candle| last.close > candle.high)
        .unwrap_or(false);
    let momentum_close = last.close > last.open
        && body_ratio >= 0.55
        && close_location >= 0.7
        && close_above_previous_high;

    TriggerSnapshot {
        momentum_close,
        close_above_previous_high,
        body_ratio,
        close_location,
    }
}

fn build_risk_plan(
    entry: f64,
    support_level: Option<f64>,
    atr_1h: Option<f64>,
    atr_15m: Option<f64>,
    available_cash: f64,
    fee_bps: f64,
) -> (Option<SignalRiskPlan>, bool) {
    let (support_level, atr_1h, atr_15m) = match (support_level, atr_1h, atr_15m) {
        (Some(support_level), Some(atr_1h), Some(atr_15m)) => (support_level, atr_1h, atr_15m),
        _ => return (None, false),
    };
    if entry <= 0.0 || available_cash <= 0.0 {
        return (None, false);
    }

    let structural_stop = support_level - atr_1h * 0.25;
    let atr_stop = entry - atr_15m * 1.5;
    let stop_loss = structural_stop.min(atr_stop);
    if stop_loss <= 0.0 || stop_loss >= entry {
        return (None, false);
    }

    let risk_per_unit = entry - stop_loss;
    if risk_per_unit <= 0.0 {
        return (None, false);
    }

    let desired_risk_amount = available_cash * 0.01;
    let quantity_by_risk = desired_risk_amount / risk_per_unit;
    let quantity_by_cash = max_affordable_quantity(available_cash, entry, fee_bps);
    if quantity_by_cash <= 0.0 {
        return (None, false);
    }
    let suggested_quantity = quantity_by_risk.min(quantity_by_cash);
    if !suggested_quantity.is_finite() || suggested_quantity <= 0.0 {
        return (None, false);
    }

    let risk_amount = suggested_quantity * risk_per_unit;
    let take_profit_1 = entry + risk_per_unit;
    let take_profit_2 = entry + risk_per_unit * 2.0;
    let notional_estimate = suggested_quantity * entry;

    (
        Some(SignalRiskPlan {
            entry,
            stop_loss,
            take_profit_1,
            take_profit_2,
            risk_per_unit,
            risk_amount,
            suggested_quantity,
            notional_estimate,
            capital_at_risk_percent: 1.0,
        }),
        quantity_by_risk > quantity_by_cash + 1e-9,
    )
}

fn max_affordable_quantity(available_cash: f64, price: f64, fee_bps: f64) -> f64 {
    if available_cash <= 0.0 || price <= 0.0 {
        return 0.0;
    }

    let fee_multiplier = 1.0 + (fee_bps / 10_000.0);
    if !fee_multiplier.is_finite() || fee_multiplier <= 0.0 {
        return 0.0;
    }

    available_cash / (price * fee_multiplier)
}

fn simulate_replay_trade(
    opened_at: i64,
    confidence: u8,
    risk_plan: &SignalRiskPlan,
    future_candles: &[Candle],
) -> ReplayTradeSample {
    let mut closed_at = opened_at;
    let mut outcome = ReplayOutcome::Timeout;
    let mut realized_r = 0.0_f64;
    let mut bars_held = future_candles.len();
    let mut tp1_hit_index = None;

    for (index, candle) in future_candles.iter().enumerate() {
        let hit_stop = candle.low <= risk_plan.stop_loss;
        let hit_tp1 = candle.high >= risk_plan.take_profit_1;

        if hit_stop && hit_tp1 {
            closed_at = candle.open_time + interval_millis("15m");
            outcome = ReplayOutcome::StopLoss;
            realized_r = -1.0;
            bars_held = index + 1;
            break;
        }
        if hit_stop {
            closed_at = candle.open_time + interval_millis("15m");
            outcome = ReplayOutcome::StopLoss;
            realized_r = -1.0;
            bars_held = index + 1;
            break;
        }
        if hit_tp1 {
            tp1_hit_index = Some(index);
            break;
        }
    }

    if tp1_hit_index.is_some() && !matches!(outcome, ReplayOutcome::StopLoss) {
        let tp1_index = tp1_hit_index.unwrap_or_default();
        let mut exit_found = false;
        for (offset, candle) in future_candles.iter().enumerate().skip(tp1_index) {
            let hit_break_even = candle.low <= risk_plan.entry;
            let hit_tp2 = candle.high >= risk_plan.take_profit_2;
            closed_at = candle.open_time + interval_millis("15m");
            bars_held = offset + 1;

            if hit_break_even && hit_tp2 {
                outcome = ReplayOutcome::Breakeven;
                realized_r = 0.5;
                exit_found = true;
                break;
            }
            if hit_tp2 {
                outcome = ReplayOutcome::TakeProfit2;
                realized_r = 1.5;
                exit_found = true;
                break;
            }
            if hit_break_even {
                outcome = ReplayOutcome::Breakeven;
                realized_r = 0.5;
                exit_found = true;
                break;
            }
        }

        if !exit_found {
            if let Some(last) = future_candles.last() {
                closed_at = last.open_time + interval_millis("15m");
                bars_held = future_candles.len();
                outcome = ReplayOutcome::Timeout;
                realized_r = 0.5 + 0.5 * ((last.close - risk_plan.entry) / risk_plan.risk_per_unit);
            }
        }
    } else if matches!(outcome, ReplayOutcome::Timeout) {
        if let Some(last) = future_candles.last() {
            closed_at = last.open_time + interval_millis("15m");
            bars_held = future_candles.len();
            realized_r = (last.close - risk_plan.entry) / risk_plan.risk_per_unit;
        }
    }

    ReplayTradeSample {
        opened_at,
        closed_at,
        outcome,
        entry: risk_plan.entry,
        stop_loss: risk_plan.stop_loss,
        take_profit_1: risk_plan.take_profit_1,
        take_profit_2: risk_plan.take_profit_2,
        realized_r,
        bars_held,
        confidence,
    }
}

fn format_structure_detail(label: &str, structure: &StructureSnapshot) -> String {
    match (
        structure.previous_pivot_high,
        structure.last_pivot_high,
        structure.previous_pivot_low,
        structure.last_pivot_low,
    ) {
        (Some(prev_high), Some(last_high), Some(prev_low), Some(last_low)) => format!(
            "{label} pivoti: HH {:.4} -> {:.4}, HL {:.4} -> {:.4}, slope {}.",
            prev_high,
            last_high,
            prev_low,
            last_low,
            if structure.slope_up {
                "gor"
            } else {
                "ni potrjen"
            }
        ),
        _ => format!("{label} nima dovolj pivotov za zanesljiv HH/HL odcitek."),
    }
}

fn format_setup_detail(
    stage: SignalStage,
    support_level: Option<f64>,
    distance_to_support: Option<f64>,
    atr_1h: Option<f64>,
) -> String {
    match (support_level, distance_to_support, atr_1h) {
        (Some(support), Some(distance), Some(atr)) if distance >= 0.0 => format!(
            "{}: zadnji zaprt 1h close je {:.4} nad support zono {:.4}. 1h ATR je {:.4}.",
            stage.as_label(),
            distance,
            support,
            atr
        ),
        (Some(support), Some(distance), Some(atr)) => format!(
            "{}: zadnji zaprt 1h close je {:.4} pod support zono {:.4}. 1h ATR je {:.4}.",
            stage.as_label(),
            distance.abs(),
            support,
            atr
        ),
        _ => "1h support zona ali ATR se ni na voljo.".to_string(),
    }
}

fn format_trigger_detail(trigger: &TriggerSnapshot) -> String {
    format!(
        "Momentum close: {}, body {:.0}% svecke, close location {:.0}%, close nad prejsnjim high {}.",
        if trigger.momentum_close { "da" } else { "ne" },
        trigger.body_ratio * 100.0,
        trigger.close_location * 100.0,
        if trigger.close_above_previous_high { "da" } else { "ne" }
    )
}

fn format_risk_detail(risk_plan: Option<&SignalRiskPlan>) -> String {
    match risk_plan {
        Some(plan) => format!(
            "Entry {:.4}, SL {:.4}, TP1 {:.4}, TP2 {:.4}, qty {:.6}.",
            plan.entry,
            plan.stop_loss,
            plan.take_profit_1,
            plan.take_profit_2,
            plan.suggested_quantity
        ),
        None => "Risk plan ni izracunan.".to_string(),
    }
}

fn build_signal_summary(
    strategy: PaperStrategy,
    symbol: &str,
    bias: SignalBias,
    technical_stage: SignalStage,
    displayed_stage: SignalStage,
    support_level: Option<f64>,
    trigger: &TriggerSnapshot,
    ai_score: i32,
    filter_blockers: &[String],
) -> String {
    if matches!(technical_stage, SignalStage::Ready)
        && !matches!(displayed_stage, SignalStage::Ready)
    {
        return format!(
            "{symbol} ima tehnicno pripravljen long setup, vendar {} blokira paper entry: {}. Trenutni AI score je {ai_score}.",
            strategy.version,
            filter_blockers.join(", ")
        );
    }

    match displayed_stage {
        SignalStage::Ready => format!(
            "{symbol} ima bullish 4h trend, zaprt 1h reclaim nad supportom {:.4}, 15m momentum close in AI score {ai_score}. Setup je odobren za rocni paper long.",
            support_level.unwrap_or_default()
        ),
        SignalStage::Setup => format!(
            "{symbol} ima {} 4h kontekst in zaprt 1h reclaim. Caka se 15m momentum trigger po reclaimu.",
            bias.as_label()
        ),
        SignalStage::Stalk => format!(
            "{symbol} ima bullish 4h kontekst in je blizu 1h supporta, vendar 1h reclaim close se ni potrjen. To je samo opazovanje."
        ),
        SignalStage::Wait => {
            if matches!(bias, SignalBias::Bullish) {
                format!(
                    "{symbol} ima del bullish konteksta, vendar manjka cist setup ali momentum close. Zadnji trigger body ratio je {:.0}%.",
                    trigger.body_ratio * 100.0
                )
            } else {
                format!(
                    "{symbol} nima dovolj cistega long konteksta. 4h bias je {}.",
                    bias.as_label()
                )
            }
        }
    }
}

fn build_journal_tags(
    strategy: PaperStrategy,
    bias: SignalBias,
    stage: SignalStage,
    ai_score: i32,
    filter_blockers: &[String],
) -> Vec<String> {
    let mut tags = vec![
        strategy.version.to_string(),
        format!("stage_{}", stage.as_label().to_ascii_lowercase()),
        format!("bias_{}", bias.as_label()),
        format!("ai_score_{ai_score}"),
    ];
    tags.extend(
        filter_blockers
            .iter()
            .map(|blocker| format!("blocked_{blocker}")),
    );
    tags
}

fn calculate_signal_confidence(
    trend_ok: bool,
    stalk_ok: bool,
    setup_ok: bool,
    trigger_ok: bool,
    risk_ok: bool,
) -> u8 {
    let mut score = 15_i32;
    if trend_ok {
        score += 25;
    }
    if stalk_ok {
        score += 15;
    }
    if setup_ok {
        score += 20;
    }
    if trigger_ok {
        score += 15;
    }
    if risk_ok {
        score += 10;
    }

    score.clamp(0, 95) as u8
}

fn parse_f64(raw: &str) -> Result<f64, ApiError> {
    raw.parse::<f64>()
        .map_err(|error| ApiError::upstream(format!("Failed to parse exchange number: {error}")))
}

fn parse_optional_f64(raw: Option<&str>) -> Result<Option<f64>, ApiError> {
    raw.map(parse_f64).transpose()
}

fn parse_json_f64(value: &serde_json::Value) -> Result<f64, ApiError> {
    match value {
        serde_json::Value::String(raw) => parse_f64(raw),
        serde_json::Value::Number(number) => number
            .as_f64()
            .ok_or_else(|| ApiError::upstream("Exchange number is out of range.")),
        _ => Err(ApiError::upstream(
            "Exchange returned an invalid numeric field.",
        )),
    }
}

fn to_json_string<T: Serialize>(value: &T) -> Result<String, ApiError> {
    serde_json::to_string(value)
        .map_err(|error| ApiError::internal(format!("Failed to encode telemetry JSON: {error}")))
}

fn parse_json_i64(value: &serde_json::Value) -> Result<i64, ApiError> {
    match value {
        serde_json::Value::String(raw) => raw.parse::<i64>().map_err(|error| {
            ApiError::upstream(format!("Failed to parse exchange integer: {error}"))
        }),
        serde_json::Value::Number(number) => number
            .as_i64()
            .ok_or_else(|| ApiError::upstream("Exchange integer is out of range.")),
        _ => Err(ApiError::upstream(
            "Exchange returned an invalid integer field.",
        )),
    }
}
