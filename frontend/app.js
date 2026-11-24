/* TrendLine Quant Lab Frontend (Supports both Local FastAPI & Static GitHub Pages Mode) */

const IS_STATIC = Boolean(window.STATIC_MODE);

function safeSym(symbol) {
  return symbol.replaceAll("/", "_").replaceAll(".", "_");
}

async function sha256Hex(str) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

const state = {
  assets: [],
  themes: [],
  strategies: [],
  exitRules: [],
  settings: null,
  selectedSymbol: "005930.KS",
  chartMarketFilter: "ALL",
  chartThemeFilter: "ALL",
  chartStrategy: "S5",
  exitRule: "default",
  chartYears: 6,
  shortWindow: 45,
  longWindow: 180,
  priceSource: "wick",
  scaleMode: "linear",
  researchMarket: "ALL",
  matrixThemeFilter: "ALL",
  scannerThemeFilter: "ALL",
  researchData: null,
  exitCompareData: null,
  scannerData: null,
  exitTestStrategy: "S3",
  matrixStrategy: "S5",
  scannerStrategy: "S5",
  chartPayload: null,
};

let tvChart = null;
let seriesMap = {};
let singleEquityChart = null;
let researchReturnChart = null;
let researchWinRateChart = null;

const $ = (id) => document.getElementById(id);

function showToast(msg, duration = 3200) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hidden"), duration);
}

function fmtPrice(val, currency = "USD") {
  if (val === null || val === undefined || Number.isNaN(val)) return "-";
  if (currency === "KRW") return Math.round(val).toLocaleString("ko-KR") + "원";
  if (Math.abs(val) >= 100) return "$" + Number(val).toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (Math.abs(val) >= 1) return "$" + Number(val).toFixed(2);
  return "$" + Number(val).toFixed(4);
}

function fmtPct(val, showPlus = true) {
  if (val === null || val === undefined || Number.isNaN(val)) return "-";
  const sign = showPlus && val > 0 ? "+" : "";
  return `${sign}${Number(val).toFixed(2)}%`;
}

function pctClass(val) {
  if (val > 0) return "pos";
  if (val < 0) return "neg";
  return "";
}

async function apiFetch(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

/* ==================== INIT ==================== */
async function ensureUnlocked(meta) {
  if (!IS_STATIC || !meta.passcode_required || !meta.passcode_sha256) return;
  const storageKey = "tlql_unlock_" + meta.passcode_sha256.slice(0, 12);
  if (localStorage.getItem(storageKey) === meta.passcode_sha256) return;

  const overlay = $("lockOverlay");
  const input = $("lockPassInput");
  const btn = $("lockUnlockBtn");
  const errEl = $("lockError");
  overlay.classList.remove("hidden");

  await new Promise((resolve) => {
    const attempt = async () => {
      const val = input.value.trim();
      if (!val) return;
      const hash = await sha256Hex(val);
      if (hash === meta.passcode_sha256) {
        localStorage.setItem(storageKey, hash);
        overlay.classList.add("hidden");
        resolve();
      } else {
        errEl.textContent = "비밀번호가 올바르지 않습니다.";
        input.value = "";
        input.focus();
      }
    };
    btn.onclick = attempt;
    input.onkeydown = (e) => {
      if (e.key === "Enter") attempt();
    };
    input.focus();
  });
}

function configureStaticModeUI(meta) {
  if (!IS_STATIC) return;
  $("syncBtn").style.display = "none";
  $("cacheStatusBadge").textContent = `매일 10:00 자동갱신 · ${meta.generated_at || ""}`;
  $("cacheStatusBadge").classList.add("ready");
  // Hide local-only controls that require live backend recomputation
  ["applyChartParamsBtn", "toggleCustomBuilderBtn", "refreshResearchBtn", "runScannerBtn", "sendAlertsNowBtn"].forEach((id) => {
    if ($(id)) $(id).style.display = "none";
  });
  const alertCard = document.querySelector(".alert-settings-card");
  if (alertCard) {
    alertCard.innerHTML = `
      <div class="card-title">🌐 클라우드 자동 알림 안내</div>
      <div class="cli-tip">
        <div class="cli-tip-title">매일 오전 10:00 (KST) 자동 실행</div>
        <p>GitHub Actions 클라우드 서버가 맥(Mac)이 꺼져 있어도 매일 오전 10시에 150개 종목을 최신화하고, 웹페이지 갱신 및 텔레그램 알림을 자동 발송합니다.</p>
        <p style="margin-top:6px;">텔레그램 토큰·비밀번호 변경은 GitHub 저장소 <b>Settings → Secrets → Actions</b>에서 언제든 수정할 수 있습니다.</p>
      </div>`;
  }
}

async function init() {
  bindEvents();
  try {
    const meta = IS_STATIC ? await apiFetch("./data/meta.json") : await apiFetch("/api/assets");
    await ensureUnlocked(meta);

    state.assets = meta.assets;
    state.themes = meta.themes || [];
    state.strategies = meta.strategies;
    state.exitRules = meta.exit_rules || [];
    state.settings = meta.settings;

    state.shortWindow = meta.settings.short_window || 45;
    state.longWindow = meta.settings.long_window || 180;
    state.priceSource = meta.settings.price_source || "wick";
    state.scaleMode = meta.settings.scale_mode || "linear";
    state.chartStrategy = meta.settings.active_strategy === "AUTO_BEST" ? "S3" : (meta.settings.active_strategy || "S3");
    state.exitRule = meta.settings.exit_rule || "default";
    state.matrixStrategy = state.chartStrategy;
    state.scannerStrategy = meta.settings.active_strategy || "AUTO_BEST";
    state.exitTestStrategy = state.chartStrategy;

    $("shortWinInput").value = state.shortWindow;
    $("longWinInput").value = state.longWindow;
    $("priceSourceSelect").value = state.priceSource;
    $("scaleModeSelect").value = state.scaleMode;
    $("nearPctInput").value = meta.settings.near_threshold_pct || 3.0;

    populateStrategySelects();
    populateExitSelects();
    populateThemeSelects();
    if (!IS_STATIC) {
      populateSettingsForm(meta.settings);
      updateCacheBadge(meta.cache);
    } else {
      configureStaticModeUI(meta);
    }
    renderAssetList();

    if (!IS_STATIC && meta.cache.cached === 0) {
      showToast("150개 종목 초기 데이터를 불러오는 중입니다...");
      await syncMarketData(false);
    }

    await loadChart(state.selectedSymbol);
  } catch (err) {
    showToast("초기화 오류: " + err.message, 5000);
  }
}

function updateCacheBadge(cache) {
  const badge = $("cacheStatusBadge");
  badge.textContent = `데이터 ${cache.cached}/${cache.total}종목 준비`;
  badge.classList.toggle("ready", cache.ready);
}

function populateStrategySelects(includeCustom = false) {
  const list = [...state.strategies];
  if (includeCustom) {
    list.push({ id: "S6", name: "커스텀 전략", short_name: "S6 커스텀" });
  }
  ["chartStrategySelect", "matrixStrategySelect", "scannerStrategySelect", "exitTestStrategySelect"].forEach((id) => {
    const sel = $(id);
    if (!sel) return;
    const prev = sel.value;
    let opts = id === "exitTestStrategySelect" ? state.strategies : list;
    if (id === "scannerStrategySelect") {
      opts = [{ id: "AUTO_BEST", name: "🏆 시장별 최적 자동매칭 (코스피·코스닥·미국·코인)" }, ...opts];
    }
    sel.innerHTML = opts
      .map((s) => `<option value="${s.id}">${s.id === "AUTO_BEST" ? s.name : s.id + ". " + s.name}</option>`)
      .join("");
    if (prev && opts.some((s) => s.id === prev)) {
      sel.value = prev;
    }
  });
  $("chartStrategySelect").value = state.chartStrategy;
  $("matrixStrategySelect").value = state.matrixStrategy;
  $("scannerStrategySelect").value = state.scannerStrategy;
  $("exitTestStrategySelect").value = state.exitTestStrategy;
}

function populateExitSelects() {
  ["chartExitSelect", "researchExitSelect", "scannerExitSelect"].forEach((id) => {
    const sel = $(id);
    if (!sel) return;
    sel.innerHTML = state.exitRules
      .map((e) => `<option value="${e.id}">${e.short_name}</option>`)
      .join("");
    sel.value = state.exitRule;
  });
}

function populateThemeSelects() {
  const html =
    `<option value="ALL">전체 테마 (10대 테마)</option>` +
    state.themes.map((t) => `<option value="${t.id}">${t.label}</option>`).join("");
  ["chartThemeFilter", "matrixThemeFilter", "scannerThemeFilter"].forEach((id) => {
    const sel = $(id);
    if (sel) sel.innerHTML = html;
  });
}

function populateSettingsForm(settings) {
  const a = settings.alerts || {};
  $("cfgMacos").checked = !!a.macos_enabled;
  $("cfgNotifyNear").checked = a.notify_near_breakout !== false;
  $("cfgTelegram").checked = !!a.telegram_enabled;
  $("cfgTgToken").value = a.telegram_bot_token || "";
  $("cfgTgChatId").value = a.telegram_chat_id || "";
  $("cfgDiscord").checked = !!a.discord_enabled;
  $("cfgDiscordUrl").value = a.discord_webhook_url || "";
}

/* ==================== EVENTS ==================== */
function bindEvents() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $("tab-" + btn.dataset.tab).classList.add("active");

      if (btn.dataset.tab === "research" && !state.researchData) {
        await loadResearch(false);
        await loadExitComparison();
      } else if (btn.dataset.tab === "scanner") {
        await loadScanner();
      } else if (btn.dataset.tab === "chart" && tvChart) {
        setTimeout(() => tvChart.timeScale().fitContent(), 50);
      }
    });
  });

  $("syncBtn").addEventListener("click", () => syncMarketData(true));

  $("assetSearch").addEventListener("input", renderAssetList);
  $("chartThemeFilter").addEventListener("change", (e) => {
    state.chartThemeFilter = e.target.value;
    renderAssetList();
  });
  $("matrixThemeFilter").addEventListener("change", (e) => {
    state.matrixThemeFilter = e.target.value;
    renderAssetMatrix();
  });
  $("scannerThemeFilter").addEventListener("change", (e) => {
    state.scannerThemeFilter = e.target.value;
    renderScannerView();
  });
  $("chartMarketPills").addEventListener("click", (e) => {
    if (!e.target.classList.contains("pill")) return;
    $("chartMarketPills").querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    e.target.classList.add("active");
    state.chartMarketFilter = e.target.dataset.market;
    renderAssetList();
  });

  $("chartStrategySelect").addEventListener("change", (e) => {
    state.chartStrategy = e.target.value;
    loadChart(state.selectedSymbol);
  });

  $("chartExitSelect").addEventListener("change", (e) => {
    setGlobalExitRule(e.target.value, true, false);
  });

  $("researchExitSelect").addEventListener("change", (e) => {
    setGlobalExitRule(e.target.value, false, true);
  });

  $("scannerExitSelect").addEventListener("change", (e) => {
    setGlobalExitRule(e.target.value, false, false);
    loadScanner();
  });

  $("exitTestStrategySelect").addEventListener("change", (e) => {
    state.exitTestStrategy = e.target.value;
    loadExitComparison();
  });

  $("runExitCompareBtn").addEventListener("click", loadExitComparison);

  $("chartPeriodGroup").addEventListener("click", (e) => {
    if (!e.target.classList.contains("seg-btn")) return;
    $("chartPeriodGroup").querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
    e.target.classList.add("active");
    state.chartYears = Number(e.target.dataset.years);
    loadChart(state.selectedSymbol);
  });

  $("applyChartParamsBtn").addEventListener("click", () => {
    state.shortWindow = Number($("shortWinInput").value) || 45;
    state.longWindow = Number($("longWinInput").value) || 180;
    state.priceSource = $("priceSourceSelect").value;
    state.scaleMode = $("scaleModeSelect").value;
    state.researchData = null;
    loadChart(state.selectedSymbol);
  });

  ["togMA20", "togMA200", "togLongUpper", "togLongLower", "togShortUpper", "togShortLower", "togMarkers"].forEach((id) => {
    $(id).addEventListener("change", applyChartVisibility);
  });

  // Research tab events
  $("researchMarketPills").addEventListener("click", (e) => {
    if (!e.target.classList.contains("pill")) return;
    $("researchMarketPills").querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    e.target.classList.add("active");
    state.researchMarket = e.target.dataset.market;
    renderResearchViews();
    renderExitComparison();
  });

  $("refreshResearchBtn").addEventListener("click", () => loadResearch(false));
  $("toggleCustomBuilderBtn").addEventListener("click", () => {
    $("customBuilderPanel").classList.toggle("hidden");
  });
  $("runCustomBtn").addEventListener("click", () => loadResearch(true));

  $("matrixStrategySelect").addEventListener("change", (e) => {
    state.matrixStrategy = e.target.value;
    renderThemeSummary();
    renderAssetMatrix();
  });
  $("matrixSortSelect").addEventListener("change", renderAssetMatrix);

  // Scanner & Alerts
  $("scannerStrategySelect").addEventListener("change", (e) => {
    state.scannerStrategy = e.target.value;
    loadScanner();
  });
  $("runScannerBtn").addEventListener("click", loadScanner);
  $("sendAlertsNowBtn").addEventListener("click", sendAlertsNow);
  $("saveSettingsBtn").addEventListener("click", saveUserSettings);
  $("testAlertBtn").addEventListener("click", testAlert);
}

async function syncMarketData(force = false) {
  const btn = $("syncBtn");
  btn.disabled = true;
  btn.textContent = "⏳ 150종목 수집 중...";
  try {
    const res = await apiFetch(`/api/sync?force=${force}`, { method: "POST" });
    updateCacheBadge(res.cache);
    state.researchData = null;
    showToast(`시세 업데이트 완료 (${res.sync.updated.length}종목 갱신)`);
    await loadChart(state.selectedSymbol);
  } catch (err) {
    showToast("시세 업데이트 실패: " + err.message, 5000);
  } finally {
    btn.disabled = false;
    btn.textContent = "↻ 150종목 시세 최신화";
  }
}

/* ==================== TAB 1: CHART LAB ==================== */
function renderAssetList() {
  const q = $("assetSearch").value.trim().toLowerCase();
  const filtered = state.assets.filter((a) => {
    if (state.chartMarketFilter !== "ALL" && a.market !== state.chartMarketFilter) return false;
    if (state.chartThemeFilter !== "ALL" && a.theme !== state.chartThemeFilter) return false;
    if (
      q &&
      !a.name.toLowerCase().includes(q) &&
      !a.symbol.toLowerCase().includes(q) &&
      !(a.theme || "").toLowerCase().includes(q)
    ) {
      return false;
    }
    return true;
  });

  $("assetList").innerHTML = filtered
    .map(
      (a) => `
      <div class="asset-item ${a.symbol === state.selectedSymbol ? "active" : ""}" data-sym="${a.symbol}">
        <div>
          <div class="asset-item-name">${a.name}</div>
          <div class="asset-item-sym">${a.symbol} · ${a.theme || ""}</div>
        </div>
        <span class="mkt-tag mkt-${a.market}">${a.market}</span>
      </div>`
    )
    .join("");

  $("assetList").querySelectorAll(".asset-item").forEach((el) => {
    el.addEventListener("click", () => {
      state.selectedSymbol = el.dataset.sym;
      renderAssetList();
      loadChart(state.selectedSymbol);
    });
  });
}

async function loadChart(symbol) {
  try {
    let data;
    if (IS_STATIC) {
      const full = await apiFetch(`./data/charts/${safeSym(symbol)}.json`);
      // Client-side period slicing for 2Y / 4Y / 6Y in static mode
      const lastDateStr = full.candles[full.candles.length - 1]?.time || "2026-01-01";
      const d = new Date(lastDateStr);
      d.setFullYear(d.getFullYear() - state.chartYears);
      const cutoff = d.toISOString().slice(0, 10);
      data = {
        ...full,
        candles: full.candles.filter((x) => x.time >= cutoff),
        volumes: full.volumes.filter((x) => x.time >= cutoff),
        ma20: full.ma20.filter((x) => x.time >= cutoff),
        ma200: full.ma200.filter((x) => x.time >= cutoff),
      };
      if (full.recommended_rule) {
        $("chartStrategySelect").value = full.recommended_rule.strategy_id;
        $("chartExitSelect").value = full.recommended_rule.exit_rule;
      }
    } else {
      const qs = new URLSearchParams({
        strategy_id: state.chartStrategy,
        exit_rule: state.exitRule,
        years: state.chartYears,
        short_window: state.shortWindow,
        long_window: state.longWindow,
        price_source: state.priceSource,
        scale_mode: state.scaleMode,
      });
      data = await apiFetch(`/api/chart/${encodeURIComponent(symbol)}?${qs}`);
    }
    state.chartPayload = data;
    renderTradingViewChart(data);
    renderSingleBacktestPanels(data);
  } catch (err) {
    showToast("차트 로딩 실패: " + err.message, 4500);
  }
}

function renderTradingViewChart(data) {
  const { asset, candles, volumes, ma20, ma200, trendlines, backtest } = data;
  $("chartAssetName").textContent = asset.name;
  $("chartAssetMeta").textContent = `${asset.symbol} · ${asset.market} · 일봉 (${asset.currency})`;

  const container = $("tvChartContainer");
  container.innerHTML = "";

  tvChart = LightweightCharts.createChart(container, {
    layout: {
      background: { type: "solid", color: "#05070a" },
      textColor: "#a0aec0",
      fontSize: 11.5,
    },
    grid: {
      vertLines: { color: "rgba(38, 49, 68, 0.45)", style: 2 },
      horzLines: { color: "rgba(38, 49, 68, 0.45)", style: 2 },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: {
      borderColor: "#222c3c",
      mode: state.scaleMode === "log" ? 1 : 0,
    },
    timeScale: {
      borderColor: "#222c3c",
      timeVisible: false,
      rightOffset: 8,
    },
    width: container.clientWidth,
    height: container.clientHeight,
  });

  const candleSeries = tvChart.addCandlestickSeries({
    upColor: "#26a69a",
    downColor: "#ef5350",
    borderUpColor: "#26a69a",
    borderDownColor: "#ef5350",
    wickUpColor: "#26a69a",
    wickDownColor: "#ef5350",
  });
  candleSeries.setData(candles);

  const volSeries = tvChart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "",
  });
  volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  volSeries.setData(volumes);

  const ma20Series = tvChart.addLineSeries({
    color: "#2962ff",
    lineWidth: 2.5,
    priceLineVisible: true,
    lastValueVisible: true,
    title: "MA20",
  });
  ma20Series.setData(ma20);

  const ma200Series = tvChart.addLineSeries({
    color: "#00897b",
    lineWidth: 2.8,
    priceLineVisible: true,
    lastValueVisible: true,
    title: "MA200",
  });
  ma200Series.setData(ma200);

  const lineConfigs = {
    long_upper: { color: "#2979ff", lineWidth: 2.4, lineStyle: 0, title: "장기 상단" },
    long_lower: { color: "#00e676", lineWidth: 2.2, lineStyle: 0, title: "장기 하단" },
    short_upper: { color: "#ff9800", lineWidth: 1.8, lineStyle: 2, title: "단기 상단" },
    short_lower: { color: "#ba68c8", lineWidth: 1.8, lineStyle: 2, title: "단기 하단" },
  };

  seriesMap = { candleSeries, ma20Series, ma200Series };
  Object.entries(lineConfigs).forEach(([key, cfg]) => {
    const s = tvChart.addLineSeries({
      ...cfg,
      crosshairMarkerVisible: false,
      lastValueVisible: true,
      priceLineVisible: false,
    });
    if (trendlines[key] && trendlines[key].points) {
      s.setData(trendlines[key].points);
    }
    seriesMap[key] = s;
  });

  // Buy / Sell markers
  const markers = [];
  (backtest.trades || []).forEach((tr) => {
    markers.push({
      time: tr.entry_date,
      position: "belowBar",
      color: "#00e676",
      shape: "arrowUp",
      text: "매수",
    });
    if (!tr.open) {
      markers.push({
        time: tr.exit_date,
        position: "aboveBar",
        color: "#ef5350",
        shape: "arrowDown",
        text: `${tr.return_pct > 0 ? "+" : ""}${tr.return_pct}%`,
      });
    }
  });
  markers.sort((a, b) => (a.time > b.time ? 1 : -1));
  seriesMap._markers = markers;

  applyChartVisibility();

  // Crosshair OHLCV + MA legend
  const lastCandle = candles[candles.length - 1];
  const updateLegend = (c, m20v, m200v) => {
    if (!c) return;
    const cur = asset.currency;
    $("ohlcLegend").innerHTML =
      `<span>${c.time}</span> &nbsp;` +
      `시 <b>${fmtPrice(c.open, cur)}</b> · 고 <b>${fmtPrice(c.high, cur)}</b> · 저 <b>${fmtPrice(c.low, cur)}</b> · 종 <b class="${c.close >= c.open ? "pos" : "neg"}">${fmtPrice(c.close, cur)}</b>` +
      (m20v ? ` &nbsp;|&nbsp; <span style="color:#6997ff">MA20 ${fmtPrice(m20v, cur)}</span>` : "") +
      (m200v ? ` &nbsp;<span style="color:#26a69a">MA200 ${fmtPrice(m200v, cur)}</span>` : "");
  };
  updateLegend(lastCandle, ma20[ma20.length - 1]?.value, ma200[ma200.length - 1]?.value);

  tvChart.subscribeCrosshairMove((param) => {
    if (!param || !param.time) {
      updateLegend(lastCandle, ma20[ma20.length - 1]?.value, ma200[ma200.length - 1]?.value);
      return;
    }
    const c = param.seriesData.get(candleSeries);
    const m20v = param.seriesData.get(ma20Series)?.value;
    const m200v = param.seriesData.get(ma200Series)?.value;
    if (c) updateLegend({ ...c, time: param.time }, m20v, m200v);
  });

  // Trendline summary strip + MA200 slope state
  const cur = asset.currency;
  const lastClose = lastCandle ? lastCandle.close : 0;
  const m200s = data.ma200_status || {};
  const m200Badge =
    m200s.state === "up"
      ? `<span class="pos">MA200 상승 ↗ (${m200s.chg10_pct >= 0 ? "+" : ""}${m200s.chg10_pct}%)</span>`
      : m200s.state === "flat"
      ? `<span style="color:#ffd54f">MA200 평평 → (${m200s.chg10_pct}%)</span>`
      : m200s.state === "down"
      ? `<span class="neg">MA200 하락 ↘ (${m200s.chg10_pct}%)</span>`
      : `<span class="muted">MA200 계산중</span>`;
  const m200PosBadge = m200s.above ? `<span class="pos">위</span>` : `<span class="neg">아래</span>`;

  const fmtTL = (label, color, seg) => {
    if (!seg) return `<span><b style="color:${color}">${label}</b>: 계산불가</span>`;
    const diff = lastClose > 0 ? ((seg.end_price - lastClose) / lastClose) * 100 : 0;
    const dir = seg.direction === "down" ? "하락" : "상승";
    return `<span><b style="color:${color}">${label}</b>(${dir}): ${fmtPrice(seg.end_price, cur)} <span class="${diff <= 0 ? "pos" : "muted"}">(${diff >= 0 ? "+" : ""}${diff.toFixed(1)}%)</span></span>`;
  };
  $("trendlineInfoBar").innerHTML = [
    `<span><b>매매 필터</b>: 주가 ${m200PosBadge} · ${m200Badge}</span>`,
    fmtTL("장기 상단", "#2979ff", trendlines.long_upper),
    fmtTL("장기 하단", "#00e676", trendlines.long_lower),
    fmtTL("단기 상단", "#ff9800", trendlines.short_upper),
    fmtTL("단기 하단", "#ba68c8", trendlines.short_lower),
  ].join("");

  tvChart.timeScale().fitContent();

  window.onresize = () => {
    if (tvChart && container.clientWidth > 0) {
      tvChart.applyOptions({ width: container.clientWidth });
    }
  };
}

function applyChartVisibility() {
  if (!seriesMap.candleSeries) return;
  seriesMap.ma20Series.applyOptions({ visible: $("togMA20").checked });
  seriesMap.ma200Series.applyOptions({ visible: $("togMA200").checked });
  seriesMap.long_upper.applyOptions({ visible: $("togLongUpper").checked });
  seriesMap.long_lower.applyOptions({ visible: $("togLongLower").checked });
  seriesMap.short_upper.applyOptions({ visible: $("togShortUpper").checked });
  seriesMap.short_lower.applyOptions({ visible: $("togShortLower").checked });
  seriesMap.candleSeries.setMarkers($("togMarkers").checked ? seriesMap._markers || [] : []);
}

function renderSingleBacktestPanels(data) {
  const { asset, backtest, multi_period } = data;
  $("singleMultiPeriodGrid").innerHTML = ["2Y", "4Y", "6Y"]
    .map((pk) => {
      const m = multi_period[pk];
      if (!m || m.error) return `<div class="mini-kpi"><div class="mini-kpi-head">${pk}</div>-</div>`;
      return `
        <div class="mini-kpi">
          <div class="mini-kpi-head">
            <span>${pk.replace("Y", "년")} 성과</span>
            <span>승률 ${m.win_rate_pct}%</span>
          </div>
          <div class="mini-kpi-val ${pctClass(m.total_return_pct)}">${fmtPct(m.total_return_pct)}</div>
          <div class="mini-kpi-sub">단순보유 ${fmtPct(m.bnh_return_pct)} · MDD ${m.mdd_pct}% · ${m.total_signals}회</div>
        </div>`;
    })
    .join("");

  // Equity curve
  const eq = backtest.equity_curve || [];
  if (singleEquityChart) singleEquityChart.destroy();
  singleEquityChart = new Chart($("singleEquityChart"), {
    type: "line",
    data: {
      labels: eq.map((p) => p.time),
      datasets: [
        {
          label: `${backtest.strategy_id} 전략 누적수익(%)`,
          data: eq.map((p) => p.strategy),
          borderColor: "#2979ff",
          backgroundColor: "rgba(41, 121, 255, 0.12)",
          fill: true,
          borderWidth: 2,
          pointRadius: 0,
        },
        {
          label: "단순 보유(Buy & Hold %)",
          data: eq.map((p) => p.bnh),
          borderColor: "#78909c",
          borderDash: [4, 4],
          borderWidth: 1.5,
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#b7c6de", font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: "#7f8fa6", maxTicksLimit: 6 }, grid: { display: false } },
        y: { ticks: { color: "#7f8fa6", callback: (v) => v + "%" }, grid: { color: "rgba(34,44,60,0.5)" } },
      },
    },
  });

  // Trades table
  const trades = backtest.trades || [];
  $("tradesCountBadge").textContent = `총 ${trades.length}건 · 승률 ${backtest.win_rate_pct}%`;
  if (trades.length === 0) {
    $("tradesTableBody").innerHTML = `<tr><td colspan="6" class="muted" style="text-align:center;padding:24px;">선택한 기간에 발생한 매매 신호가 없습니다.</td></tr>`;
  } else {
    $("tradesTableBody").innerHTML = [...trades]
      .reverse()
      .map(
        (tr) => `
        <tr>
          <td>${tr.entry_date}</td>
          <td>${tr.open ? '<span class="sig-badge sig-BUY">보유중</span>' : tr.exit_date}</td>
          <td class="num">${fmtPrice(tr.entry_price, asset.currency)}</td>
          <td class="num">${fmtPrice(tr.exit_price, asset.currency)}</td>
          <td class="num ${pctClass(tr.return_pct)}">${fmtPct(tr.return_pct)}</td>
          <td class="muted">${tr.entry_reason} → ${tr.exit_reason}</td>
        </tr>`
      )
      .join("");
  }
}

/* ==================== TAB 2: 30-ASSET RESEARCH ==================== */
async function loadResearch(includeCustom = false) {
  const btn = includeCustom ? $("runCustomBtn") : $("refreshResearchBtn");
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = "⏳ 30종목 2·4·6년 계산 중...";
  try {
    let data;
    if (includeCustom) {
      const payload = {
        short_window: state.shortWindow,
        long_window: state.longWindow,
        price_source: state.priceSource,
        scale_mode: state.scaleMode,
        custom_params: {
          horizon: $("cpHorizon").value,
          require_descending: $("cpReqDesc").checked,
          ma200_filter: $("cpMa200").value,
          ma20_filter: $("cpMa20").checked,
          ma20_rising: $("cpMa20Rising").checked,
          vol_mult: Number($("cpVolMult").value) || 1.0,
          confirm_bars: Number($("cpConfirm").value) || 1,
          exit_mode: $("cpExitMode").value,
          stop_loss_pct: Number($("cpStopLoss").value) || 0,
          take_profit_pct: Number($("cpTakeProfit").value) || 0,
        },
      };
      data = await apiFetch("/api/research/custom", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      populateStrategySelects(true);
      state.matrixStrategy = "S6";
      $("matrixStrategySelect").value = "S6";
      showToast("S6 커스텀 전략 30종목 백테스트 완료!");
    } else if (IS_STATIC) {
      data = await apiFetch(`./data/research_${state.exitRule || "default"}.json`);
      populateStrategySelects(false);
    } else {
      const qs = new URLSearchParams({
        short_window: state.shortWindow,
        long_window: state.longWindow,
        price_source: state.priceSource,
        scale_mode: state.scaleMode,
        exit_rule: state.exitRule,
      });
      data = await apiFetch(`/api/research?${qs}`);
      populateStrategySelects(false);
    }
    state.researchData = data;
    renderResearchViews();
  } catch (err) {
    showToast("연구 계산 오류: " + err.message, 5000);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

function renderResearchViews() {
  if (!state.researchData) return;
  const { recommendations, strategies } = state.researchData;
  const mkt = state.researchMarket;
  const scopeNames = {
    ALL: "전체 250종목",
    KOSPI: "코스피 70종목",
    KOSDAQ: "코스닥 70종목",
    US: "미국주식 80종목",
    CRYPTO: "코인 30종목",
  };
  $("researchScopeLabel").textContent = `${scopeNames[mkt] || mkt} 기준 (왕복 수수료 0.2% 반영)`;

  // Recommendation cards
  const cardDefs = [
    { key: "ALL", title: "🏆 전체 250종목 최적", highlight: true },
    { key: "KOSPI", title: "🇰🇷 코스피 70 최적" },
    { key: "KOSDAQ", title: "🚀 코스닥 70 최적" },
    { key: "US", title: "🇺🇸 미국 80 최적" },
    { key: "CRYPTO", title: "🪙 코인 30 최적" },
  ];
  $("recommendationCards").innerHTML = cardDefs
    .map((c) => {
      const r = recommendations[c.key];
      return `
        <div class="rec-card ${c.highlight ? "highlight" : ""}">
          <div class="rec-label">${c.title}</div>
          <div class="rec-name">${r.strategy_id}. ${r.strategy_name}</div>
          <div class="rec-stats">
            <span>6년 승률 <b>${r.avg_win_rate_6y}%</b></span>
            <span>2년 <b class="${pctClass(r.avg_return_2y)}">${fmtPct(r.avg_return_2y)}</b></span>
            <span>4년 <b class="${pctClass(r.avg_return_4y)}">${fmtPct(r.avg_return_4y)}</b></span>
            <span>6년 <b class="${pctClass(r.avg_return_6y)}">${fmtPct(r.avg_return_6y)}</b></span>
          </div>
          <button class="btn btn-secondary btn-sm apply-best-btn" data-sid="${r.strategy_id}" style="margin-top:4px;">
            🔔 이 전략으로 알림 적용
          </button>
        </div>`;
    })
    .join("");

  $("recommendationCards").querySelectorAll(".apply-best-btn").forEach((b) => {
    b.addEventListener("click", () => applyStrategyToScanner(b.dataset.sid));
  });

  // Charts: 2Y / 4Y / 6Y Return & Win Rate
  const labels = strategies.map((s) => s.short_name);
  const bnh2 = strategies[0]?.periods["2Y"][mkt]?.avg_bnh_pct ?? 0;
  const bnh4 = strategies[0]?.periods["4Y"][mkt]?.avg_bnh_pct ?? 0;
  const bnh6 = strategies[0]?.periods["6Y"][mkt]?.avg_bnh_pct ?? 0;

  if (researchReturnChart) researchReturnChart.destroy();
  researchReturnChart = new Chart($("researchReturnChart"), {
    type: "bar",
    data: {
      labels: [...labels, "단순보유(B&H)"],
      datasets: [
        {
          label: "2년 평균 수익률(%)",
          data: [...strategies.map((s) => s.periods["2Y"][mkt].avg_return_pct), bnh2],
          backgroundColor: "rgba(41, 121, 255, 0.78)",
        },
        {
          label: "4년 평균 수익률(%)",
          data: [...strategies.map((s) => s.periods["4Y"][mkt].avg_return_pct), bnh4],
          backgroundColor: "rgba(0, 188, 212, 0.78)",
        },
        {
          label: "6년 평균 수익률(%)",
          data: [...strategies.map((s) => s.periods["6Y"][mkt].avg_return_pct), bnh6],
          backgroundColor: "rgba(0, 230, 118, 0.78)",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#c5d1e6" } } },
      scales: {
        x: { ticks: { color: "#b7c6de" }, grid: { display: false } },
        y: { ticks: { color: "#8b9bb4", callback: (v) => v + "%" }, grid: { color: "rgba(34,44,60,0.5)" } },
      },
    },
  });

  if (researchWinRateChart) researchWinRateChart.destroy();
  researchWinRateChart = new Chart($("researchWinRateChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "2년 평균 승률(%)",
          data: strategies.map((s) => s.periods["2Y"][mkt].avg_win_rate_pct),
          backgroundColor: "rgba(255, 152, 0, 0.75)",
        },
        {
          label: "4년 평균 승률(%)",
          data: strategies.map((s) => s.periods["4Y"][mkt].avg_win_rate_pct),
          backgroundColor: "rgba(186, 104, 200, 0.78)",
        },
        {
          label: "6년 평균 승률(%)",
          data: strategies.map((s) => s.periods["6Y"][mkt].avg_win_rate_pct),
          backgroundColor: "rgba(38, 166, 154, 0.85)",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#c5d1e6" } } },
      scales: {
        x: { ticks: { color: "#b7c6de" }, grid: { display: false } },
        y: { min: 0, max: 100, ticks: { color: "#8b9bb4", callback: (v) => v + "%" }, grid: { color: "rgba(34,44,60,0.5)" } },
      },
    },
  });

  // Strategy summary table
  $("strategySummaryBody").innerHTML = strategies
    .map((s) => {
      const p2 = s.periods["2Y"][mkt];
      const p4 = s.periods["4Y"][mkt];
      const p6 = s.periods["6Y"][mkt];
      const avgScore = ((p2.score + p4.score + p6.score) / 3).toFixed(1);
      return `
        <tr>
          <td>
            <b>${s.id}. ${s.name}</b>
            <div class="muted">${s.description}</div>
          </td>
          <td class="num">${p2.avg_win_rate_pct}%</td>
          <td class="num ${pctClass(p2.avg_return_pct)}">${fmtPct(p2.avg_return_pct)}</td>
          <td class="num">${p4.avg_win_rate_pct}%</td>
          <td class="num ${pctClass(p4.avg_return_pct)}">${fmtPct(p4.avg_return_pct)}</td>
          <td class="num"><b>${p6.avg_win_rate_pct}%</b></td>
          <td class="num ${pctClass(p6.avg_return_pct)}"><b>${fmtPct(p6.avg_return_pct)}</b></td>
          <td class="num muted">${fmtPct(p6.avg_bnh_pct)}</td>
          <td class="num neg">${p6.avg_mdd_pct}%</td>
          <td class="num">${p6.avg_profit_factor}</td>
          <td class="num"><b>${avgScore}</b></td>
          <td><button class="btn btn-secondary btn-sm apply-row-btn" data-sid="${s.id}">적용</button></td>
        </tr>`;
    })
    .join("");

  $("strategySummaryBody").querySelectorAll(".apply-row-btn").forEach((b) => {
    b.addEventListener("click", () => applyStrategyToScanner(b.dataset.sid));
  });

  renderThemeSummary();
  renderAssetMatrix();
}

function renderThemeSummary() {
  if (!state.researchData) return;
  const sid = state.matrixStrategy;
  const strat = state.researchData.strategies.find((s) => s.id === sid) || state.researchData.strategies[0];
  if (!strat) return;
  const th2 = strat.periods["2Y"]?.THEMES || {};
  const th4 = strat.periods["4Y"]?.THEMES || {};
  const th6 = strat.periods["6Y"]?.THEMES || {};
  $("themeSummaryStrategyLabel").textContent = `${strat.id}. ${strat.name} 기준 (행 클릭 시 아래 종목표 필터)`;

  const rows = state.themes
    .map((th) => ({ th, p2: th2[th.id], p4: th4[th.id], p6: th6[th.id] }))
    .filter((r) => r.p6 && r.p6.count > 0)
    .sort((a, b) => b.p6.avg_return_pct - a.p6.avg_return_pct);

  $("themeSummaryBody").innerHTML = rows
    .map(
      ({ th, p2, p4, p6 }) => `
      <tr style="cursor:pointer" data-theme="${th.id}">
        <td><b>${th.label}</b></td>
        <td class="num muted">${p6.count}개</td>
        <td class="num">${p2.avg_win_rate_pct}%</td>
        <td class="num ${pctClass(p2.avg_return_pct)}">${fmtPct(p2.avg_return_pct)}</td>
        <td class="num">${p4.avg_win_rate_pct}%</td>
        <td class="num ${pctClass(p4.avg_return_pct)}">${fmtPct(p4.avg_return_pct)}</td>
        <td class="num"><b>${p6.avg_win_rate_pct}%</b></td>
        <td class="num ${pctClass(p6.avg_return_pct)}"><b>${fmtPct(p6.avg_return_pct)}</b></td>
        <td class="num muted">${fmtPct(p6.avg_bnh_pct)}</td>
        <td class="num neg">${p6.avg_mdd_pct}%</td>
        <td class="num"><b>${p6.avg_profit_factor}</b></td>
      </tr>`
    )
    .join("");

  $("themeSummaryBody").querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      state.matrixThemeFilter = tr.dataset.theme;
      $("matrixThemeFilter").value = tr.dataset.theme;
      renderAssetMatrix();
    });
  });
}

function renderAssetMatrix() {
  if (!state.researchData) return;
  const sid = state.matrixStrategy;
  const bucket = state.researchData.per_asset[sid];
  if (!bucket) return;

  const mkt = state.researchMarket;
  const thf = state.matrixThemeFilter;
  const rows = state.assets
    .filter((a) => (mkt === "ALL" || a.market === mkt) && (thf === "ALL" || a.theme === thf))
    .map((a) => ({
      asset: a,
      y2: bucket["2Y"]?.[a.symbol],
      y4: bucket["4Y"]?.[a.symbol],
      y6: bucket["6Y"]?.[a.symbol],
    }))
    .filter((r) => r.y6);

  const sortBy = $("matrixSortSelect").value;
  rows.sort((a, b) => {
    if (sortBy === "ret6y") return b.y6.total_return_pct - a.y6.total_return_pct;
    if (sortBy === "wr6y") return b.y6.win_rate_pct - a.y6.win_rate_pct;
    if (sortBy === "ret2y") return (b.y2?.total_return_pct ?? -999) - (a.y2?.total_return_pct ?? -999);
    if (sortBy === "mdd6y") return b.y6.mdd_pct - a.y6.mdd_pct;
    return a.asset.market.localeCompare(b.asset.market);
  });

  $("assetMatrixBody").innerHTML = rows
    .map(
      ({ asset, y2, y4, y6 }) => `
      <tr data-sym="${asset.symbol}">
        <td><b>${asset.name}</b> <span class="muted">${asset.symbol}</span></td>
        <td><span class="mkt-tag mkt-${asset.market}">${asset.market}</span><span class="theme-tag">${asset.theme || ""}</span></td>
        <td class="num">${y2 ? y2.win_rate_pct + "%" : "-"}</td>
        <td class="num ${y2 ? pctClass(y2.total_return_pct) : ""}">${y2 ? fmtPct(y2.total_return_pct) : "-"}</td>
        <td class="num">${y4 ? y4.win_rate_pct + "%" : "-"}</td>
        <td class="num ${y4 ? pctClass(y4.total_return_pct) : ""}">${y4 ? fmtPct(y4.total_return_pct) : "-"}</td>
        <td class="num"><b>${y6.win_rate_pct}%</b></td>
        <td class="num ${pctClass(y6.total_return_pct)}"><b>${fmtPct(y6.total_return_pct)}</b></td>
        <td class="num muted">${fmtPct(y6.bnh_return_pct)}</td>
        <td class="num neg">${y6.mdd_pct}%</td>
        <td class="num">${y6.total_signals}회</td>
      </tr>`
    )
    .join("");

  $("assetMatrixBody").querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      jumpToChart(tr.dataset.sym, sid === "S6" ? state.chartStrategy : sid);
    });
  });
}

function jumpToChart(symbol, strategyId) {
  state.selectedSymbol = symbol;
  if (strategyId && strategyId !== "S6") {
    state.chartStrategy = strategyId;
    $("chartStrategySelect").value = strategyId;
  }
  document.querySelector('.tab-btn[data-tab="chart"]').click();
  renderAssetList();
  loadChart(symbol);
}

async function applyStrategyToScanner(sid) {
  if (sid === "S6") {
    showToast("S1~S5 전략을 기본 알림 전략으로 지정할 수 있습니다.");
    return;
  }
  state.scannerStrategy = sid;
  $("scannerStrategySelect").value = sid;
  if (!IS_STATIC && state.settings) {
    state.settings.active_strategy = sid;
    await apiFetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.settings),
    });
  }
  showToast(`전략 [${sid}]이(가) 신호 스캐너에 적용되었습니다!`);
  document.querySelector('.tab-btn[data-tab="scanner"]').click();
}

async function setGlobalExitRule(exitId, reloadChartNow = false, reloadResearchNow = false) {
  state.exitRule = exitId;
  ["chartExitSelect", "researchExitSelect", "scannerExitSelect"].forEach((id) => {
    if ($(id)) $(id).value = exitId;
  });
  if (reloadChartNow) await loadChart(state.selectedSymbol);
  if (reloadResearchNow) await loadResearch(false);
}

async function loadExitComparison() {
  const btn = $("runExitCompareBtn");
  if (btn) btn.disabled = true;
  try {
    if (IS_STATIC) {
      const validSid = ["S1", "S2", "S3", "S5"].includes(state.exitTestStrategy) ? state.exitTestStrategy : "S3";
      state.exitCompareData = await apiFetch(`./data/exits_${validSid}.json`);
    } else {
      const qs = new URLSearchParams({
        strategy_id: state.exitTestStrategy,
        short_window: state.shortWindow,
        long_window: state.longWindow,
        price_source: state.priceSource,
        scale_mode: state.scaleMode,
      });
      state.exitCompareData = await apiFetch(`/api/research/exits?${qs}`);
    }
    renderExitComparison();
  } catch (err) {
    showToast("청산 규칙 비교 오류: " + err.message, 4500);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderExitComparison() {
  if (!state.exitCompareData) return;
  const mkt = state.researchMarket;
  const bestId = state.exitCompareData.best_by_market?.[mkt]?.exit_id;
  $("exitCompareBody").innerHTML = state.exitCompareData.exits
    .map((ex) => {
      const p2 = ex.periods["2Y"][mkt];
      const p4 = ex.periods["4Y"][mkt];
      const p6 = ex.periods["6Y"][mkt];
      const badge = ex.id === bestId ? ` <span class="sig-badge sig-BUY">최적</span>` : "";
      return `
        <tr>
          <td>
            <b>${ex.name}</b>${badge}
            <div class="muted">${ex.description}</div>
          </td>
          <td class="num">${p2.avg_win_rate_pct}%</td>
          <td class="num ${pctClass(p2.avg_return_pct)}">${fmtPct(p2.avg_return_pct)}</td>
          <td class="num">${p4.avg_win_rate_pct}%</td>
          <td class="num ${pctClass(p4.avg_return_pct)}">${fmtPct(p4.avg_return_pct)}</td>
          <td class="num"><b>${p6.avg_win_rate_pct}%</b></td>
          <td class="num ${pctClass(p6.avg_return_pct)}"><b>${fmtPct(p6.avg_return_pct)}</b></td>
          <td class="num neg">${p6.avg_mdd_pct}%</td>
          <td class="num"><b>${p6.avg_profit_factor}</b></td>
          <td class="num muted">${p6.avg_hold_days}일</td>
          <td><button class="btn btn-secondary btn-sm apply-exit-btn" data-eid="${ex.id}">적용</button></td>
        </tr>`;
    })
    .join("");

  $("exitCompareBody").querySelectorAll(".apply-exit-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      await setGlobalExitRule(b.dataset.eid, false, true);
      showToast(`청산 규칙 [${b.dataset.eid}]이(가) 전체 대시보드에 적용되었습니다!`);
    });
  });
}

/* ==================== TAB 3: SIGNAL SCANNER & ALERTS ==================== */
async function loadScanner() {
  const btn = $("runScannerBtn");
  if (btn) btn.disabled = true;
  try {
    let data;
    if (IS_STATIC) {
      const validSid = ["AUTO_BEST", "S1", "S2", "S3", "S5"].includes(state.scannerStrategy)
        ? state.scannerStrategy
        : "AUTO_BEST";
      data = await apiFetch(`./data/scanner_${validSid}.json`);
      try {
        const rep = await apiFetch("./data/latest_report.json");
        $("dailyReportCard").classList.remove("hidden");
        $("dailyReportTitle").textContent = "📋 " + rep.title;
        $("dailyReportTime").textContent = rep.generated_at || "";
        $("dailyReportBody").textContent = rep.full_text || "";
      } catch (_) {}
    } else {
      const qs = new URLSearchParams({
        strategy_id: state.scannerStrategy,
        exit_rule: state.exitRule,
        short_window: state.shortWindow,
        long_window: state.longWindow,
        price_source: state.priceSource,
        scale_mode: state.scaleMode,
        near_threshold_pct: Number($("nearPctInput").value) || 3.0,
      });
      data = await apiFetch(`/api/scanner?${qs}`);
    }
    state.scannerData = data;
    renderScannerView();
  } catch (err) {
    showToast("스캐너 오류: " + err.message, 4500);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderScannerView() {
  const data = state.scannerData;
  if (!data) return;

  $("scannerKpis").innerHTML = `
    <div class="kpi-box"><div><div class="muted">🟢 신규 매수</div><div class="muted">${data.strategy_name}</div></div><div class="kpi-num pos">${data.counts.BUY}</div></div>
    <div class="kpi-box"><div><div class="muted">🔴 청산 매도</div><div class="muted">최근 2일 이탈</div></div><div class="kpi-num neg">${data.counts.SELL}</div></div>
    <div class="kpi-box"><div><div class="muted">🟡 돌파 임박</div><div class="muted">추세선 ${$("nearPctInput").value}% 이내</div></div><div class="kpi-num" style="color:#ffd54f">${data.counts.NEAR}</div></div>
    <div class="kpi-box"><div><div class="muted">🔵 보유 / ⚪ 관망</div><div class="muted">${data.scanned_at}</div></div><div class="kpi-num" style="color:#82b1ff">${data.counts.HOLD}<span style="font-size:15px;color:#8b9bb4"> / ${data.counts.WATCH}</span></div></div>
  `;

  // Theme heat bar
  const themes = data.themes || [];
  $("scannerThemeBar").innerHTML = themes
    .map(
      (th) => `
      <div class="theme-heat-card ${state.scannerThemeFilter === th.id ? "active" : ""}" data-theme="${th.id}">
        <div class="theme-heat-name">${th.label}</div>
        <div class="theme-heat-meta">
          <span class="pos">매수 ${th.BUY}</span> ·
          <span style="color:#ffd54f">임박 ${th.NEAR}</span> ·
          <span class="neg">매도 ${th.SELL}</span><br/>
          MA200 강세 <b>${th.ma200_ok_pct}%</b> (${th.total}종목)
        </div>
      </div>`
    )
    .join("");

  $("scannerThemeBar").querySelectorAll(".theme-heat-card").forEach((el) => {
    el.addEventListener("click", () => {
      state.scannerThemeFilter = state.scannerThemeFilter === el.dataset.theme ? "ALL" : el.dataset.theme;
      $("scannerThemeFilter").value = state.scannerThemeFilter;
      renderScannerView();
    });
  });

  const filteredItems = data.items.filter(
    (it) => state.scannerThemeFilter === "ALL" || it.theme === state.scannerThemeFilter
  );

  const badgeText = { BUY: "🟢 매수", SELL: "🔴 매도", NEAR: "🟡 임박", HOLD: "🔵 보유", WATCH: "⚪ 관망" };
  $("scannerTableBody").innerHTML = filteredItems
    .map(
      (it) => `
      <tr data-sym="${it.symbol}">
        <td><span class="sig-badge sig-${it.signal}">${badgeText[it.signal]}</span></td>
        <td><b>${it.name}</b> <span class="muted">${it.symbol}</span></td>
        <td><span class="mkt-tag mkt-${it.market}">${it.market}</span><span class="theme-tag">${it.theme || ""}</span></td>
        <td class="num">${fmtPrice(it.close, it.currency)}</td>
        <td class="num ${pctClass(it.change_pct)}">${fmtPct(it.change_pct)}</td>
        <td>
          <span class="${it.above_ma20 ? "pos" : "neg"}">20${it.above_ma20 ? "▲" : "▼"}</span> ·
          <span class="${it.above_ma200 ? "pos" : "neg"}">200${it.above_ma200 ? "▲" : "▼"}</span>
          <span class="${it.ma200_state === "up" ? "pos" : it.ma200_state === "flat" ? "" : "neg"}" style="${it.ma200_state === "flat" ? "color:#ffd54f" : ""}">
            ${it.ma200_state === "up" ? "↗" : it.ma200_state === "flat" ? "→" : "↘"}
          </span>
        </td>
        <td class="num ${it.dist_short_upper_pct !== null && it.dist_short_upper_pct <= 0 ? "pos" : "muted"}">
          ${it.dist_short_upper_pct !== null ? fmtPct(it.dist_short_upper_pct) : "-"}
        </td>
        <td class="num ${it.dist_long_upper_pct !== null && it.dist_long_upper_pct <= 0 ? "pos" : "muted"}">
          ${it.dist_long_upper_pct !== null ? fmtPct(it.dist_long_upper_pct) : "-"}
        </td>
        <td class="muted">${it.reason}</td>
      </tr>`
    )
    .join("");

  $("scannerTableBody").querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => jumpToChart(tr.dataset.sym, state.scannerStrategy === "AUTO_BEST" ? "S3" : state.scannerStrategy));
  });
}

async function saveUserSettings() {
  const payload = {
    short_window: state.shortWindow,
    long_window: state.longWindow,
    price_source: state.priceSource,
    scale_mode: state.scaleMode,
    fee_rate: 0.001,
    near_threshold_pct: Number($("nearPctInput").value) || 3.0,
    active_strategy: state.scannerStrategy,
    exit_rule: state.exitRule,
    alerts: {
      macos_enabled: $("cfgMacos").checked,
      notify_near_breakout: $("cfgNotifyNear").checked,
      telegram_enabled: $("cfgTelegram").checked,
      telegram_bot_token: $("cfgTgToken").value.trim(),
      telegram_chat_id: $("cfgTgChatId").value.trim(),
      discord_enabled: $("cfgDiscord").checked,
      discord_webhook_url: $("cfgDiscordUrl").value.trim(),
    },
  };
  try {
    state.settings = await apiFetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("alertFeedback").textContent = "✓ 알림 및 전략 설정이 저장되었습니다.";
    showToast("설정 저장 완료!");
  } catch (err) {
    $("alertFeedback").textContent = "저장 실패: " + err.message;
  }
}

async function testAlert() {
  await saveUserSettings();
  try {
    const res = await apiFetch("/api/alerts/test", { method: "POST" });
    const summary = (res.results || [])
      .map((r) => `${r.channel}: ${r.ok ? "성공" : "실패(" + r.error + ")"}`)
      .join(" / ");
    $("alertFeedback").textContent = summary || "활성화된 알림 채널이 없습니다.";
    showToast("테스트 알림 발송 완료: " + summary);
  } catch (err) {
    $("alertFeedback").textContent = "테스트 실패: " + err.message;
  }
}

async function sendAlertsNow() {
  const btn = $("sendAlertsNowBtn");
  btn.disabled = true;
  try {
    const res = await apiFetch(`/api/alerts/send?strategy_id=${state.scannerStrategy}`, { method: "POST" });
    if (!res.notified) {
      showToast(res.message || "발송할 신호가 없습니다.");
    } else {
      const okCnt = (res.alert_results || []).filter((r) => r.ok).length;
      showToast(`신호 ${res.triggered_count}건 알림 발송 완료 (${okCnt}개 채널 성공)`);
    }
  } catch (err) {
    showToast("알림 발송 오류: " + err.message, 4500);
  } finally {
    btn.disabled = false;
  }
}

init();
