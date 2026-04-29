const appState = {
  symbol: "BTCUSDT",
  interval: "1m",
  watchlist: [],
  refreshTimer: null,
  signalAssistant: null,
  secondarySignalAssistants: [],
  replayReport: null,
  replaySymbol: null,
  replayLoading: false,
};

const summaryCards = document.querySelector("#summaryCards");
const marketCards = document.querySelector("#marketCards");
const updatedAt = document.querySelector("#updatedAt");
const marketStatus = document.querySelector("#marketStatus");
const chartTitle = document.querySelector("#chartTitle");
const chartMeta = document.querySelector("#chartMeta");
const signalSummary = document.querySelector("#signalSummary");
const signalCards = document.querySelector("#signalCards");
const signalChecklist = document.querySelector("#signalChecklist");
const signalRiskPlan = document.querySelector("#signalRiskPlan");
const signalWarnings = document.querySelector("#signalWarnings");
const secondarySignals = document.querySelector("#secondarySignals");
const prefillSignalTrade = document.querySelector("#prefillSignalTrade");
const replayUpdatedAt = document.querySelector("#replayUpdatedAt");
const replaySummary = document.querySelector("#replaySummary");
const replayCards = document.querySelector("#replayCards");
const replayNotes = document.querySelector("#replayNotes");
const replayTradesBody = document.querySelector("#replayTradesBody");
const runReplay = document.querySelector("#runReplay");
const positionsBody = document.querySelector("#positionsBody");
const ordersBody = document.querySelector("#ordersBody");
const tradesBody = document.querySelector("#tradesBody");
const tradeForm = document.querySelector("#tradeForm");
const tradeSymbol = document.querySelector("#tradeSymbol");
const tradeSide = document.querySelector("#tradeSide");
const tradeOrderKind = document.querySelector("#tradeOrderKind");
const tradeQuantity = document.querySelector("#tradeQuantity");
const tradeLimitPrice = document.querySelector("#tradeLimitPrice");
const tradeStopLoss = document.querySelector("#tradeStopLoss");
const tradeTakeProfit = document.querySelector("#tradeTakeProfit");
const tradeNote = document.querySelector("#tradeNote");
const tradeFeedback = document.querySelector("#tradeFeedback");
const resetAccount = document.querySelector("#resetAccount");
const chartCanvas = document.querySelector("#priceChart");
const intervalButtons = Array.from(document.querySelectorAll(".interval-button"));

async function fetchDashboard() {
  setStatus("Osvezujem market data ...");
  const params = new URLSearchParams({
    symbol: appState.symbol,
    interval: appState.interval,
  });

  const response = await fetch(`/api/dashboard?${params.toString()}`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ error: "Unknown error." }));
    throw new Error(payload.error || "Dashboard loading failed.");
  }

  return response.json();
}

async function fetchReplay(symbol) {
  const params = new URLSearchParams({ symbol });
  const response = await fetch(`/api/replay?${params.toString()}`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ error: "Replay loading failed." }));
    throw new Error(payload.error || "Replay loading failed.");
  }

  return response.json();
}

function renderDashboard(data) {
  appState.watchlist = data.watchlist;
  appState.symbol = data.selected_symbol;
  appState.signalAssistant = data.signal_assistant || null;
  appState.secondarySignalAssistants = data.secondary_signal_assistants || [];
  syncTradeSymbolOptions(data.watchlist);
  renderSummary(data.paper);
  renderMarket(data.tickers);
  renderChart(data.candles, data.selected_symbol, data.interval);
  renderSignalAssistant(data.signal_assistant);
  renderSecondarySignalAssistants(appState.secondarySignalAssistants);
  renderPositions(data.paper.positions);
  renderOrders(data.paper.open_orders);
  renderTrades(data.paper.trades);
  updatedAt.textContent = `Posodobljeno ${formatDateTime(data.updated_at)}`;
  setStatus("Povezano z javnim market feedom");
}

function renderReplay(report) {
  if (!report) {
    replayUpdatedAt.textContent = "";
    replaySummary.textContent = "Replay se se ni zagnal za izbrani simbol.";
    replayCards.innerHTML = "";
    replayNotes.innerHTML = "";
    replayTradesBody.innerHTML = `<tr><td class="empty-state" colspan="8">Ni replay rezultatov.</td></tr>`;
    return;
  }

  replayUpdatedAt.textContent = `Replay ${formatDateTime(report.generated_at)}`;
  replaySummary.textContent = `${report.symbol}: ${report.ready_signals} ready signalov iz ${report.lookback_trigger_candles} zadnjih 15m candle-ov. Replay uporablja ${report.forward_trigger_candles} prihodnjih 15m candle-ov za vsak signal.`;
  replayCards.innerHTML = [
    {
      label: "Ready",
      value: report.ready_signals,
      subvalue: `Stalk/setup ${report.setup_signals}`,
    },
    {
      label: "TP1 win rate",
      value: `${report.win_rate_percent.toFixed(1)}%`,
      subvalue: `TP1 ${report.tp1_hits} | Stop ${report.stop_losses}`,
    },
    {
      label: "Average R",
      value: formatSignedNumber(report.average_r),
      subvalue: `TP2 ${report.tp2_hits} | BE ${report.breakeven_exits}`,
    },
    {
      label: "Total R",
      value: formatSignedNumber(report.total_r),
      subvalue: `Timeout ${report.timeout_exits}`,
    },
  ]
    .map(
      (item) => `
        <article class="signal-card">
          <span class="signal-card-label">${item.label}</span>
          <span class="signal-card-value">${item.value}</span>
          <span class="signal-card-subvalue">${item.subvalue}</span>
        </article>
      `
    )
    .join("");

  replayNotes.innerHTML = (report.notes || [])
    .map(
      (item) => `
        <article class="signal-item">
          <div class="signal-item-label">
            <span class="signal-dot"></span>
            <span>Replay note</span>
          </div>
          <span class="signal-item-detail">${escapeHtml(item)}</span>
        </article>
      `
    )
    .join("");

  if (!report.recent_trades?.length) {
    replayTradesBody.innerHTML = `<tr><td class="empty-state" colspan="8">Ni dovolj ready signalov za replay.</td></tr>`;
    return;
  }

  replayTradesBody.innerHTML = report.recent_trades
    .map(
      (trade) => `
        <tr>
          <td>${formatDateTime(trade.opened_at)}</td>
          <td>${formatReplayOutcome(trade.outcome)}</td>
          <td class="${trade.realized_r >= 0 ? "change-positive" : "change-negative"}">${formatSignedNumber(trade.realized_r)}</td>
          <td>${formatReplayHeld(trade.bars_held)}</td>
          <td>${formatMoney(trade.entry)}</td>
          <td>${formatMoney(trade.stop_loss)}</td>
          <td>${formatMoney(trade.take_profit_1)}</td>
          <td>${formatMoney(trade.take_profit_2)}</td>
        </tr>
      `
    )
    .join("");
}

function renderSummary(paper) {
  const summary = [
    {
      label: "Equity",
      value: formatMoney(paper.summary.equity),
      subvalue: `Cash ${formatMoney(paper.cash_balance)}`,
    },
    {
      label: "Exposure",
      value: formatMoney(paper.summary.positions_value),
      subvalue: `Unrealized ${formatSignedMoney(paper.summary.unrealized_pnl)}`,
    },
    {
      label: "Total PnL",
      value: formatSignedMoney(paper.summary.total_pnl),
      subvalue: `Realized ${formatSignedMoney(paper.realized_pnl)}`,
    },
    {
      label: "Open workflow",
      value: `${paper.summary.open_order_count} open orders`,
      subvalue: `${paper.summary.trade_count} recent trades | Fee ${paper.fee_bps.toFixed(1)} bps`,
    },
  ];

  summaryCards.innerHTML = summary
    .map(
      (item) => `
        <article class="summary-card">
          <span class="summary-label">${item.label}</span>
          <span class="summary-value">${item.value}</span>
          <span class="summary-subvalue">${item.subvalue}</span>
        </article>
      `
    )
    .join("");
}

function renderMarket(tickers) {
  marketCards.innerHTML = tickers
    .map((ticker) => {
      const changeClass = ticker.price_change_percent >= 0 ? "change-positive" : "change-negative";
      const activeClass = ticker.symbol === appState.symbol ? "active" : "";
      return `
        <article class="market-card ${activeClass}" data-symbol="${ticker.symbol}">
          <div class="market-topline">
            <span class="market-label">${ticker.symbol}</span>
            <strong class="${changeClass}">${formatSignedPercent(ticker.price_change_percent)}</strong>
          </div>
          <span class="market-price">${formatMoney(ticker.last_price)}</span>
          <p class="market-meta">
            24h range ${formatMoney(ticker.low_price)} - ${formatMoney(ticker.high_price)}
          </p>
          <p class="market-meta">
            Quote vol ${compactNumber(ticker.quote_volume)}
          </p>
        </article>
      `;
    })
    .join("");

  document.querySelectorAll(".market-card").forEach((card) => {
    card.addEventListener("click", () => {
      appState.symbol = card.dataset.symbol;
      tradeSymbol.value = appState.symbol;
      loadAndRender();
    });
  });
}

function renderChart(candles, symbol, interval) {
  chartTitle.textContent = `${symbol} / ${interval}`;

  if (!candles.length) {
    chartMeta.textContent = "Ni candle podatkov.";
    clearChart();
    return;
  }

  const closes = candles.map((candle) => candle.close);
  const latest = closes.at(-1);
  const previous = closes.at(-2) ?? latest;
  const change = latest - previous;
  const changePercent = previous === 0 ? 0 : (change / previous) * 100;
  chartMeta.textContent = `Last ${formatMoney(latest)} | Candle move ${formatSignedMoney(change)} (${formatSignedPercent(changePercent)})`;

  drawChart(candles);
}

function renderSignalAssistant(signal) {
  if (!signal) {
    signalSummary.textContent = "Signal assistant ni na voljo.";
    signalCards.innerHTML = "";
    signalChecklist.innerHTML = "";
    signalRiskPlan.innerHTML = "";
    signalWarnings.innerHTML = "";
    secondarySignals.innerHTML = "";
    prefillSignalTrade.disabled = true;
    return;
  }

  signalSummary.textContent = signal.summary;
  signalCards.innerHTML = [
    {
      label: "Stage",
      value: formatSignalStage(signal.stage),
      subvalue: `Bias ${formatSignalBias(signal.bias)}`,
    },
    {
      label: "Confidence",
      value: `${signal.confidence}%`,
      subvalue: `Posodobljeno ${formatDateTime(signal.generated_at)}`,
    },
    {
      label: "Timeframes",
      value: `${signal.timeframes.trend} / ${signal.timeframes.setup} / ${signal.timeframes.trigger}`,
      subvalue: "Trend / setup / trigger",
    },
    {
      label: "Strategy",
      value: signal.strategy_version || "signal assistant",
      subvalue: (signal.journal_tags || []).join(" | ") || "No tags",
    },
    {
      label: "Mode",
      value: signal.risk_plan ? "Approved paper gate" : "Watch only",
      subvalue: "Guarded auto-paper",
    },
  ]
    .map(
      (item) => `
        <article class="signal-card">
          <span class="signal-card-label">${item.label}</span>
          <span class="signal-card-value">${item.value}</span>
          <span class="signal-card-subvalue">${item.subvalue}</span>
        </article>
      `
    )
    .join("");

  signalChecklist.innerHTML = (signal.checklist || [])
    .map(
      (item) => `
        <article class="signal-item">
          <div class="signal-item-label">
            <span class="signal-dot ${item.passed ? "is-positive" : "is-negative"}"></span>
            <span>${escapeHtml(item.label)}</span>
          </div>
          <span class="signal-item-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  signalRiskPlan.innerHTML = signal.risk_plan
    ? `
      <article class="signal-item">
        <div class="signal-item-label">
          <span class="signal-dot is-positive"></span>
          <span>Predlagan paper long</span>
        </div>
        <span class="signal-item-detail">
          Entry ${formatMoney(signal.risk_plan.entry)}<br />
          Stop ${formatMoney(signal.risk_plan.stop_loss)}<br />
          TP1 ${formatMoney(signal.risk_plan.take_profit_1)}<br />
          TP2 ${formatMoney(signal.risk_plan.take_profit_2)}<br />
          Qty ${formatQuantity(signal.risk_plan.suggested_quantity)}<br />
          Risk ${formatMoney(signal.risk_plan.risk_amount)} (${signal.risk_plan.capital_at_risk_percent.toFixed(1)}%)<br />
          Notional ${formatMoney(signal.risk_plan.notional_estimate)}
        </span>
      </article>
    `
    : `
      <article class="signal-item">
        <div class="signal-item-label">
          <span class="signal-dot"></span>
          <span>Brez aktivnega plana</span>
        </div>
        <span class="signal-item-detail">Signal se se sestavlja ali pa ni dovolj cist za nov paper trade.</span>
      </article>
    `;

  signalWarnings.innerHTML = (signal.warnings || [])
    .map(
      (item) => `
        <article class="signal-item">
          <div class="signal-item-label">
            <span class="signal-dot"></span>
            <span>Opomba</span>
          </div>
          <span class="signal-item-detail">${escapeHtml(item)}</span>
        </article>
      `
    )
    .join("");

  prefillSignalTrade.disabled = !signal.risk_plan;
}

function renderSecondarySignalAssistants(signals) {
  if (!secondarySignals) {
    return;
  }
  if (!signals.length) {
    secondarySignals.innerHTML = "";
    return;
  }

  secondarySignals.innerHTML = signals
    .map((signal) => {
      const topWarnings = (signal.warnings || []).slice(0, 2);
      const riskPlan = signal.risk_plan
        ? `Entry ${formatMoney(signal.risk_plan.entry)} | Stop ${formatMoney(signal.risk_plan.stop_loss)} | TP1 ${formatMoney(signal.risk_plan.take_profit_1)} | Qty ${formatQuantity(signal.risk_plan.suggested_quantity)}`
        : "Brez aktivnega plana";
      return `
        <article class="secondary-bot">
          <div class="secondary-bot-head">
            <div>
              <span class="signal-card-label">Secondary paper bot</span>
              <strong>${escapeHtml(signal.strategy_version || "paper_strategy")}</strong>
            </div>
            <span class="signal-pill ${signal.risk_plan ? "is-positive" : ""}">${signal.risk_plan ? "Approved gate" : "Watch"}</span>
          </div>
          <p class="secondary-bot-summary">${escapeHtml(signal.summary || "")}</p>
          <div class="secondary-bot-grid">
            <span>Stage ${formatSignalStage(signal.stage)}</span>
            <span>Score ${signal.ai_score ?? 0}</span>
            <span>${escapeHtml(riskPlan)}</span>
          </div>
          ${
            topWarnings.length
              ? `<div class="secondary-bot-warnings">${topWarnings.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`
              : ""
          }
        </article>
      `;
    })
    .join("");
}

function renderPositions(positions) {
  if (!positions.length) {
    positionsBody.innerHTML = `<tr><td class="empty-state" colspan="9">Ni odprtih paper pozicij.</td></tr>`;
    return;
  }

  positionsBody.innerHTML = positions
    .map((position) => {
      const pnlClass = position.unrealized_pnl >= 0 ? "change-positive" : "change-negative";
      return `
        <tr>
          <td>${position.symbol}</td>
          <td>${formatQuantity(position.quantity)}</td>
          <td>${formatMoney(position.avg_price)}</td>
          <td>${formatMoney(position.current_price)}</td>
          <td>${formatNullableMoney(position.stop_loss)}</td>
          <td>${formatNullableMoney(position.take_profit)}</td>
          <td>${formatMoney(position.market_value)}</td>
          <td class="${pnlClass}">${formatSignedMoney(position.unrealized_pnl)}</td>
          <td>${escapeHtml(position.note || "") || "-"}</td>
        </tr>
      `;
    })
    .join("");
}

function renderOrders(orders) {
  if (!orders.length) {
    ordersBody.innerHTML = `<tr><td class="empty-state" colspan="10">Ni odprtih orderjev.</td></tr>`;
    return;
  }

  ordersBody.innerHTML = orders
    .map((order) => `
      <tr>
        <td>${formatDateTime(order.created_at)}</td>
        <td>${order.order_kind}</td>
        <td>${order.side}</td>
        <td>${order.symbol}</td>
        <td>${formatQuantity(order.quantity)}</td>
        <td>${formatNullableMoney(order.limit_price)}</td>
        <td>${formatNullableMoney(order.stop_loss)}</td>
        <td>${formatNullableMoney(order.take_profit)}</td>
        <td>${escapeHtml(order.note || "") || "-"}</td>
        <td><button class="table-button" data-cancel-order="${order.id}" type="button">Cancel</button></td>
      </tr>
    `)
    .join("");

  document.querySelectorAll("[data-cancel-order]").forEach((button) => {
    button.addEventListener("click", async () => {
      const orderId = Number(button.dataset.cancelOrder);
      await cancelOrder(orderId);
    });
  });
}

function renderTrades(trades) {
  if (!trades.length) {
    tradesBody.innerHTML = `<tr><td class="empty-state" colspan="9">Trade log je se prazen.</td></tr>`;
    return;
  }

  tradesBody.innerHTML = trades
    .map((trade) => {
      const pnlClass = trade.realized_pnl >= 0 ? "change-positive" : "change-negative";
      return `
        <tr>
          <td>${formatDateTime(trade.executed_at)}</td>
          <td>${trade.source}</td>
          <td>${trade.side}</td>
          <td>${trade.symbol}</td>
          <td>${formatQuantity(trade.quantity)}</td>
          <td>${formatMoney(trade.price)}</td>
          <td>${formatMoney(trade.fee_paid)}</td>
          <td class="${pnlClass}">${formatSignedMoney(trade.realized_pnl)}</td>
          <td>${escapeHtml(trade.note || "") || "-"}</td>
        </tr>
      `;
    })
    .join("");
}

function syncTradeSymbolOptions(symbols) {
  if (!symbols.length) {
    return;
  }

  if (tradeSymbol.options.length !== symbols.length) {
    tradeSymbol.innerHTML = symbols
      .map((symbol) => `<option value="${symbol}">${symbol}</option>`)
      .join("");
  }

  if (!appState.symbol && symbols.length) {
    appState.symbol = symbols[0];
  }

  tradeSymbol.value = appState.symbol;
}

function syncOrderFormState() {
  const limitMode = tradeOrderKind.value === "limit";
  tradeLimitPrice.disabled = !limitMode;
  tradeLimitPrice.required = limitMode;
  tradeLimitPrice.placeholder = limitMode ? "Required for limit" : "Only for limit";

  const isBuy = tradeSide.value === "buy";
  tradeStopLoss.disabled = !isBuy;
  tradeTakeProfit.disabled = !isBuy;
  if (!isBuy) {
    tradeStopLoss.value = "";
    tradeTakeProfit.value = "";
  }
}

async function submitTrade(event) {
  event.preventDefault();

  const quantity = Number(tradeQuantity.value);
  if (!Number.isFinite(quantity) || quantity <= 0) {
    tradeFeedback.textContent = "Vnesi veljavno kolicino.";
    return;
  }

  const payload = {
    symbol: tradeSymbol.value,
    side: tradeSide.value,
    order_kind: tradeOrderKind.value,
    quantity,
    limit_price: toOptionalNumber(tradeLimitPrice.value),
    stop_loss: toOptionalNumber(tradeStopLoss.value),
    take_profit: toOptionalNumber(tradeTakeProfit.value),
    note: tradeNote.value.trim() || null,
  };

  tradeFeedback.textContent = "Oddajam paper order ...";

  const response = await fetch("/api/paper/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: "Order failed." }));
    tradeFeedback.textContent = body.error || "Order failed.";
    return;
  }

  const result = await response.json();
  tradeFeedback.textContent = result.message;
  if (result.trade?.symbol) {
    appState.symbol = result.trade.symbol;
  }
  tradeForm.reset();
  tradeQuantity.value = "0.01";
  syncTradeSymbolOptions(appState.watchlist);
  syncOrderFormState();
  await loadAndRender();
}

async function cancelOrder(orderId) {
  const response = await fetch(`/api/paper/orders/${orderId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: "Cancelled manually from UI." }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: "Cancel failed." }));
    tradeFeedback.textContent = body.error || "Cancel failed.";
    return;
  }

  tradeFeedback.textContent = `Order #${orderId} cancelled.`;
  await loadAndRender();
}

async function resetPaperAccount() {
  const confirmed = window.confirm("Resetiram paper account in izbrisem vse paper pozicije, orderje in trade log?");
  if (!confirmed) {
    return;
  }

  const response = await fetch("/api/paper/reset", { method: "POST" });
  if (!response.ok) {
    tradeFeedback.textContent = "Reset ni uspel.";
    return;
  }

  tradeFeedback.textContent = "Paper account je resetiran.";
  tradeForm.reset();
  tradeQuantity.value = "0.01";
  syncTradeSymbolOptions(appState.watchlist);
  syncOrderFormState();
  await loadAndRender();
}

async function loadReplay(force = false) {
  if (appState.replayLoading) {
    return;
  }
  if (!force && appState.replaySymbol === appState.symbol && appState.replayReport) {
    return;
  }

  appState.replayLoading = true;
  runReplay.disabled = true;
  replaySummary.textContent = `Poganjam replay za ${appState.symbol} ...`;

  try {
    const report = await fetchReplay(appState.symbol);
    appState.replayReport = report;
    appState.replaySymbol = report.symbol;
    renderReplay(report);
  } catch (error) {
    appState.replayReport = null;
    appState.replaySymbol = null;
    replayUpdatedAt.textContent = "";
    replaySummary.textContent = error.message;
    replayCards.innerHTML = "";
    replayNotes.innerHTML = "";
    replayTradesBody.innerHTML = `<tr><td class="empty-state" colspan="8">Replay ni uspel.</td></tr>`;
    console.error(error);
  } finally {
    appState.replayLoading = false;
    runReplay.disabled = false;
  }
}

async function loadAndRender() {
  try {
    const previousReplaySymbol = appState.replaySymbol;
    const data = await fetchDashboard();
    renderDashboard(data);
    if (!appState.replayReport || previousReplaySymbol !== appState.symbol) {
      void loadReplay();
    }
  } catch (error) {
    setStatus("Napaka pri osvezevanju");
    tradeFeedback.textContent = error.message;
    console.error(error);
  }
}

function setStatus(message) {
  marketStatus.textContent = message;
}

function clearChart() {
  const ctx = chartCanvas.getContext("2d");
  ctx.clearRect(0, 0, chartCanvas.width, chartCanvas.height);
}

function drawChart(candles) {
  const ctx = chartCanvas.getContext("2d");
  const width = chartCanvas.width;
  const height = chartCanvas.height;
  const padding = 28;
  const values = candles.map((candle) => candle.close);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  ctx.clearRect(0, 0, width, height);

  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "rgba(255, 150, 82, 0.34)");
  gradient.addColorStop(1, "rgba(255, 150, 82, 0.02)");
  ctx.fillStyle = gradient;
  ctx.strokeStyle = "rgba(255, 150, 82, 0.95)";
  ctx.lineWidth = 3;

  ctx.beginPath();
  values.forEach((value, index) => {
    const x = padding + (index / Math.max(values.length - 1, 1)) * (width - padding * 2);
    const y = height - padding - ((value - min) / range) * (height - padding * 2);
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });

  ctx.stroke();

  ctx.lineTo(width - padding, height - padding);
  ctx.lineTo(padding, height - padding);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = "rgba(145, 163, 195, 0.22)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = padding + i * ((height - padding * 2) / 3);
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(width - padding, y);
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(237, 244, 255, 0.8)";
  ctx.font = '12px "Aptos", "Trebuchet MS", sans-serif';
  ctx.fillText(formatMoney(max), padding, 18);
  ctx.fillText(formatMoney(min), padding, height - 10);
}

function formatMoney(value) {
  const digits = Math.abs(value) >= 1000 ? 2 : 4;
  return new Intl.NumberFormat("sl-SI", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
  }).format(value);
}

function formatNullableMoney(value) {
  return value == null ? "-" : formatMoney(value);
}

function formatSignedMoney(value) {
  const formatted = formatMoney(Math.abs(value));
  return `${value >= 0 ? "+" : "-"}${formatted}`;
}

function formatSignedPercent(value) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatSignedNumber(value) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}

function formatSignalStage(value) {
  switch (value) {
    case "ready":
      return "READY";
    case "setup":
      return "SETUP";
    case "stalk":
      return "STALK";
    default:
      return "WAIT";
  }
}

function formatSignalBias(value) {
  switch (value) {
    case "bullish":
      return "bullish";
    case "bearish":
      return "bearish";
    default:
      return "neutral";
  }
}

function formatReplayOutcome(value) {
  switch (value) {
    case "take_profit2":
      return "TP2";
    case "breakeven":
      return "TP1 -> BE";
    case "stop_loss":
      return "SL";
    default:
      return "Timeout";
  }
}

function formatReplayHeld(bars) {
  const minutes = bars * 15;
  if (minutes >= 60) {
    return `${(minutes / 60).toFixed(1)}h`;
  }
  return `${minutes}m`;
}

function formatQuantity(value) {
  return value.toLocaleString("sl-SI", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
}

function compactNumber(value) {
  return new Intl.NumberFormat("sl-SI", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatDateTime(timestamp) {
  return new Intl.DateTimeFormat("sl-SI", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(timestamp));
}

function toOptionalNumber(rawValue) {
  if (rawValue == null || rawValue === "") {
    return null;
  }

  const parsed = Number(rawValue);
  return Number.isFinite(parsed) ? parsed : null;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function prefillTradeFromSignal() {
  const signal = appState.signalAssistant;
  if (!signal?.risk_plan) {
    tradeFeedback.textContent = "Signal nima veljavnega risk plana za prefill.";
    return;
  }

  appState.symbol = signal.symbol;
  tradeSymbol.value = signal.symbol;
  tradeSide.value = "buy";
  tradeOrderKind.value = "market";
  tradeQuantity.value = signal.risk_plan.suggested_quantity.toFixed(6);
  tradeLimitPrice.value = "";
  tradeStopLoss.value = signal.risk_plan.stop_loss.toFixed(6);
  tradeTakeProfit.value = signal.risk_plan.take_profit_1.toFixed(6);
  tradeNote.value = `${signal.strategy_version || "Signal assistant"} ${formatSignalStage(signal.stage)} | ${signal.summary}`;
  syncOrderFormState();
  tradeFeedback.textContent = "Signal setup je prenesen v paper order form. Pred oddajo se rocno preveri novice in korelacije.";
}

intervalButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    appState.interval = button.dataset.interval;
    intervalButtons.forEach((item) => item.classList.toggle("active", item === button));
    await loadAndRender();
  });
});

tradeSymbol.addEventListener("change", async () => {
  appState.symbol = tradeSymbol.value;
  appState.replayReport = null;
  appState.replaySymbol = null;
  renderReplay(null);
  await loadAndRender();
});

tradeSide.addEventListener("change", syncOrderFormState);
tradeOrderKind.addEventListener("change", syncOrderFormState);

tradeForm.addEventListener("submit", submitTrade);
resetAccount.addEventListener("click", resetPaperAccount);
prefillSignalTrade.addEventListener("click", prefillTradeFromSignal);
runReplay.addEventListener("click", async () => {
  await loadReplay(true);
});

syncOrderFormState();
renderReplay(null);
loadAndRender();
appState.refreshTimer = window.setInterval(loadAndRender, 5000);
