/* TrendLine Quant Lab Frontend (Supports both Local FastAPI & Static GitHub Pages Mode) */

const IS_STATIC = Boolean(window.STATIC_MODE);

function safeSym(symbol) {
  return symbol.replaceAll("/", "_").replaceAll(".", "_").replaceAll("^", "IDX_").replaceAll("=", "_");
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
  top30MarketFilter: "ALL",
  top30ThemeFilter: "ALL",
  top30RatingFilter: "ALL",
  top30OversoldOnly: false,
  top30RisingsOnly: false,
  scannerOversoldOnly: false,
  matrixThemeFilter: "ALL",
  scannerThemeFilter: "ALL",
  myHoldings: [], // [{ symbol, avgPrice, qty, buyDate, customStop }]
  myWatchlist: [], // [symbol, ...]
  scannerMap: {}, // symbol -> scanner item
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
  if (currency === "PT") return Number(val).toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (currency === "PCT") return Number(val).toFixed(2) + "%";
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
  $("cacheStatusBadge").textContent = `매일 08:30·15:00 자동갱신 · ${meta.generated_at || ""}`;
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
        <div class="cli-tip-title">매일 08:30 (미국·코인) · 평일 15:00 (한국·종합) 자동 실행</div>
        <p>GitHub Actions 클라우드 서버가 맥(Mac)이 꺼져 있어도 아침 8시 30분(미국·코인)과 평일 오후 3시(한국 장중 예비·종합)에 전체 종목을 최신화하고, 웹페이지 갱신 및 텔레그램 알림을 자동 발송합니다.</p>
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
    loadUserPortfolioStorage();
    populatePortfolioSymbolSelect();
    if (!IS_STATIC) {
      populateSettingsForm(meta.settings);
      updateCacheBadge(meta.cache);
    } else {
      configureStaticModeUI(meta);
    }
    renderAssetList();

    if (!IS_STATIC && meta.cache.cached === 0) {
      showToast("전체 종목 초기 데이터를 불러오는 중입니다...");
      await syncMarketData(false);
    }

    // Load Top 30 leaderboard first since it is the default landing tab
    await loadScanner();
    renderPortfolioTab();
  } catch (err) {
    showToast("초기화 오류: " + err.message, 5000);
  }
}

/* ==================== PORTFOLIO & WATCHLIST STORAGE ==================== */
const HOLDINGS_KEY = "tlql_holdings_v1";
const WATCHLIST_KEY = "tlql_watchlist_v1";

function loadUserPortfolioStorage() {
  try {
    state.myHoldings = JSON.parse(localStorage.getItem(HOLDINGS_KEY) || "[]");
    if (!Array.isArray(state.myHoldings)) state.myHoldings = [];
  } catch (_) {
    state.myHoldings = [];
  }
  try {
    state.myWatchlist = JSON.parse(localStorage.getItem(WATCHLIST_KEY) || "[]");
    if (!Array.isArray(state.myWatchlist)) state.myWatchlist = [];
  } catch (_) {
    state.myWatchlist = [];
  }
  updateNavHoldCount();
}

function saveUserPortfolioStorage() {
  localStorage.setItem(HOLDINGS_KEY, JSON.stringify(state.myHoldings));
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(state.myWatchlist));
  updateNavHoldCount();
}

function updateNavHoldCount() {
  if ($("navHoldCount")) $("navHoldCount").textContent = String(state.myHoldings.length);
}

function getHolding(symbol) {
  return state.myHoldings.find((h) => h.symbol === symbol) || null;
}

function isStarred(symbol) {
  return state.myWatchlist.includes(symbol);
}

function toggleStar(symbol) {
  if (isStarred(symbol)) {
    state.myWatchlist = state.myWatchlist.filter((s) => s !== symbol);
  } else {
    state.myWatchlist.push(symbol);
  }
  saveUserPortfolioStorage();
  updateChartPortfolioButtons();
  renderTop30Board();
  renderPortfolioTab();
  renderScannerView();
}

function populatePortfolioSymbolSelect() {
  const sel = $("pfSymbolSelect");
  if (!sel) return;
  sel.innerHTML = state.assets
    .map((a) => `<option value="${a.symbol}">[${a.market}] ${a.name} (${a.symbol}) · ${a.theme}</option>`)
    .join("");
}

function evaluateHoldingStatus(h, it) {
  if (!it) {
    return {
      code: "HOLD_OK",
      label: "🔵 보유중",
      badgeClass: "sig-HOLD",
      detail: "시세 불러오는 중",
      pnlPct: 0,
      pnlAmt: 0,
      dayAmt: 0,
      stopLoss: h.customStop || 0,
      target1: 0,
      alertLevel: 0,
    };
  }
  const avg = Number(h.avgPrice) || it.close;
  const qty = Number(h.qty) || 0;
  const pnlPct = avg > 0 ? ((it.close / avg) - 1) * 100 : 0;
  const pnlAmt = (it.close - avg) * qty;
  const prevClose = it.close / (1 + (it.change_pct || 0) / 100);
  const dayAmt = (it.close - prevClose) * qty;
  const tp = it.trade_plan || {};
  const stopLoss = h.customStop && Number(h.customStop) > 0 ? Number(h.customStop) : (tp.stop_loss || avg * 0.92);
  const target1 = tp.target_1 || avg * 1.18;

  // Personalized sell / hold rules strictly tied to user's actual held stock
  if (it.close <= stopLoss) {
    return {
      code: "SELL_STOP",
      label: "🔴 손절·매도 경보",
      badgeClass: "rate-SELL_WARN",
      detail: `손절가(${fmtPrice(stopLoss, it.currency)}) 하회`,
      pnlPct, pnlAmt, dayAmt, stopLoss, target1, alertLevel: 3,
    };
  }
  if (it.signal === "SELL" || (!it.above_ma200 && !it.above_ma20)) {
    return {
      code: "SELL_TREND",
      label: "🔴 추세이탈 매도권고",
      badgeClass: "rate-SELL_WARN",
      detail: it.signal === "SELL" ? it.reason : "MA200·MA20 모두 하회",
      pnlPct, pnlAmt, dayAmt, stopLoss, target1, alertLevel: 3,
    };
  }
  if (!it.above_ma20 && pnlPct < 0) {
    return {
      code: "SELL_WARN",
      label: "🟠 약세·매도검토",
      badgeClass: "rate-WATCH_BUY",
      detail: "MA20 이탈 + 손실 구간 (손절선 주시)",
      pnlPct, pnlAmt, dayAmt, stopLoss, target1, alertLevel: 2,
    };
  }
  if ((it.close >= target1 && pnlPct >= 10) || (it.rsi14 !== null && it.rsi14 >= 76 && pnlPct >= 12)) {
    return {
      code: "TAKE_PROFIT",
      label: "🟣 분할 익절 검토",
      badgeClass: "sig-HOLD",
      detail: it.rsi14 >= 76 ? `RSI 과열(${it.rsi14}) + 수익 +${pnlPct.toFixed(1)}%` : `1차 목표가 도달 (+${pnlPct.toFixed(1)}%)`,
      pnlPct, pnlAmt, dayAmt, stopLoss, target1, alertLevel: 1,
    };
  }
  return {
    code: "HOLD_OK",
    label: "🟢 정상 보유 유지",
    badgeClass: "rate-BUY",
    detail: it.above_ma200 ? "MA200 위 추세 유지" : "손절선 위 보유 유지",
    pnlPct, pnlAmt, dayAmt, stopLoss, target1, alertLevel: 0,
  };
}

function getDisplayRating(it) {
  // Personalized rule: Hold/Sell badges ONLY for user's own holdings!
  // Non-held stocks show clean buy/oversold/watch ratings.
  const h = getHolding(it.symbol);
  if (h) {
    const st = evaluateHoldingStatus(h, it);
    return {
      badgeClass: st.badgeClass,
      label: `${st.label} (${st.pnlPct >= 0 ? "+" : ""}${st.pnlPct.toFixed(1)}%)`,
      isHeld: true,
    };
  }
  if (it.rating === "STRONG_BUY") return { badgeClass: "rate-STRONG_BUY", label: "🔥 강력 매수", isHeld: false };
  if (it.rating === "BUY") return { badgeClass: "rate-BUY", label: "🟢 매수", isHeld: false };
  if (it.rating === "WATCH_BUY") return { badgeClass: "rate-WATCH_BUY", label: "🟡 매수 관심", isHeld: false };
  if (it.rsi14 !== null && it.rsi14 <= 36) return { badgeClass: "rsi-oversold", label: "💎 과매도 주시", isHeld: false };
  return { badgeClass: "rate-HOLD_WATCH", label: "⚪ 관망", isHeld: false };
}

function renderRsiBadge(it) {
  const rsi = it.rsi14;
  const wk = it.weekly_bull ? `<span class="pos" title="주봉 20주선 상승">주↗</span>` : `<span class="neg" title="주봉 20주선 약세">주↘</span>`;
  if (rsi === null || rsi === undefined) return `- ${wk}`;
  if (rsi <= 30) return `<span class="rsi-oversold">💎 ${rsi.toFixed(1)}</span> ${wk}`;
  if (rsi <= 36) return `<span class="rsi-oversold">💠 ${rsi.toFixed(1)}</span> ${wk}`;
  if (rsi <= 46) return `<span class="rsi-dip">${rsi.toFixed(1)}</span> ${wk}`;
  if (rsi >= 75) return `<span class="rsi-overbought">⚠️ ${rsi.toFixed(1)}</span> ${wk}`;
  return `<span class="muted">${rsi.toFixed(1)}</span> ${wk}`;
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
  ["top30ThemeFilter", "chartThemeFilter", "matrixThemeFilter", "scannerThemeFilter"].forEach((id) => {
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
  setupChartFocus();
  setupDrawing();
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $("tab-" + btn.dataset.tab).classList.add("active");

      if (btn.dataset.tab === "top30") {
        if (!state.scannerData) await loadScanner();
        renderTop30Board();
      } else if (btn.dataset.tab === "portfolio") {
        if (!state.scannerData) await loadScanner();
        renderPortfolioTab();
      } else if (btn.dataset.tab === "research" && !state.researchData) {
        await loadResearch(false);
        await loadExitComparison();
      } else if (btn.dataset.tab === "scanner") {
        await loadScanner();
      } else if (btn.dataset.tab === "chart") {
        if (!state.chartPayload) {
          await loadChart(state.selectedSymbol);
        } else if (tvChart) {
          setTimeout(() => {
            const c = $("tvChartContainer");
            if (c && c.clientWidth > 0) tvChart.applyOptions({ width: c.clientWidth });
            tvChart.timeScale().fitContent();
          }, 50);
        }
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

  $("top30MarketPills").addEventListener("click", (e) => {
    if (!e.target.classList.contains("pill")) return;
    $("top30MarketPills").querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    e.target.classList.add("active");
    state.top30MarketFilter = e.target.dataset.market;
    renderTop30Board();
  });
  $("top30ThemeFilter").addEventListener("change", (e) => {
    state.top30ThemeFilter = e.target.value;
    renderTop30Board();
  });
  $("top30RatingFilter").addEventListener("change", (e) => {
    state.top30RatingFilter = e.target.value;
    renderTop30Board();
  });
  $("top30OversoldOnly").addEventListener("change", (e) => {
    state.top30OversoldOnly = e.target.checked;
    renderTop30Board();
  });
  $("top30RisingsOnly").addEventListener("change", (e) => {
    state.top30RisingsOnly = e.target.checked;
    renderTop30Board();
  });
  $("scannerOversoldOnly").addEventListener("change", (e) => {
    state.scannerOversoldOnly = e.target.checked;
    renderScannerView();
  });

  // Portfolio & Chart buttons
  $("pfAddBtn").addEventListener("click", handleAddHolding);
  $("exportPortfolioBtn").addEventListener("click", exportPortfolioJson);
  $("importPortfolioBtn").addEventListener("click", importPortfolioJson);
  $("chartStarBtn").addEventListener("click", () => toggleStar(state.selectedSymbol));
  $("chartAddHoldingBtn").addEventListener("click", () => {
    const sym = state.selectedSymbol;
    const it = state.scannerMap[sym];
    $("pfSymbolSelect").value = sym;
    if (it) $("pfAvgPrice").value = it.close;
    document.querySelector('.tab-btn[data-tab="portfolio"]').click();
    $("pfAvgPrice").focus();
  });
  $("calcCapitalInput").addEventListener("input", renderTradePlanCard);
  $("calcRiskPctInput").addEventListener("input", renderTradePlanCard);
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
    updateChartPortfolioButtons();
    renderTradePlanCard();
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
    autoSize: true,
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
    title: "20일선",
  });
  ma20Series.setData(ma20);

  const ma200Series = tvChart.addLineSeries({
    color: "#00897b",
    lineWidth: 2.8,
    priceLineVisible: true,
    lastValueVisible: true,
    title: "200일선",
  });
  ma200Series.setData(ma200);

  const lineConfigs = {
    long_upper: { color: "#2979ff", lineWidth: 2.4, lineStyle: 0, title: "장기 상단" },
    long_lower: { color: "#00e676", lineWidth: 2.2, lineStyle: 0, title: "장기 하단" },
    short_upper: { color: "#ff9800", lineWidth: 1.8, lineStyle: 2, title: "단기 상단" },
    short_lower: { color: "#ba68c8", lineWidth: 1.8, lineStyle: 2, title: "단기 하단" },
  };

  seriesMap = { candleSeries, ma20Series, ma200Series };

  // Draw Stop-Loss & Target 1 price lines on chart from scanner trade plan
  const scanItem = state.scannerMap[asset.symbol];
  if (scanItem && scanItem.trade_plan) {
    const tp = scanItem.trade_plan;
    candleSeries.createPriceLine({
      price: tp.stop_loss,
      color: "#ef5350",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: `손절 (${tp.stop_basis})`,
    });
    candleSeries.createPriceLine({
      price: tp.target_1,
      color: "#00e676",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: `1차목표 (1:${tp.rr_ratio})`,
    });
  }
  const myH = getHolding(asset.symbol);
  if (myH && Number(myH.avgPrice) > 0) {
    candleSeries.createPriceLine({
      price: Number(myH.avgPrice),
      color: "#ffd54f",
      lineWidth: 2,
      lineStyle: 0,
      axisLabelVisible: true,
      title: "내 매수가",
    });
  }
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

  updateFocusLabel();
  attachDrawings(asset.symbol, candles, candleSeries);
}

// ==================== 직접 선 긋기 ====================
// 선은 종목별로 이 브라우저(localStorage)에 저장됩니다.
const DRAW_KEY = "tl_drawings_v1";
const draw = {
  tool: null,       // seg | ray | hline | erase
  color: "#ffeb3b",
  first: null,      // 첫 번째 점 {t, p}
  temp: null,       // 미리보기 시리즈
  items: [],        // {type, a, b, color, _obj}
  symbol: null,
  candles: [],
  idx: new Map(),
  series: null,
};

function loadAllDrawings() {
  try { return JSON.parse(localStorage.getItem(DRAW_KEY) || "{}"); } catch { return {}; }
}
function saveDrawings() {
  if (!draw.symbol) return;
  const all = loadAllDrawings();
  const list = draw.items.map(({ type, a, b, color }) => ({ type, a, b, color }));
  if (list.length) all[draw.symbol] = list; else delete all[draw.symbol];
  localStorage.setItem(DRAW_KEY, JSON.stringify(all));
}

function drawIsLog() { return state.scaleMode === "log"; }

// 두 점을 지나는 직선의 i번째 봉 위치 값 (로그 스케일이면 로그 기준 직선)
function lineValueAt(a, b, i) {
  const ia = draw.idx.get(a.t), ib = draw.idx.get(b.t);
  if (ia == null || ib == null || ia === ib) return null;
  const k = (i - ia) / (ib - ia);
  if (drawIsLog() && a.p > 0 && b.p > 0) return Math.exp(Math.log(a.p) + k * (Math.log(b.p) - Math.log(a.p)));
  return a.p + k * (b.p - a.p);
}

function linePoints(type, a, b) {
  const ia = draw.idx.get(a.t), ib = draw.idx.get(b.t);
  if (ia == null || ib == null || ia === ib) return null;
  const [p1, p2] = ia < ib ? [a, b] : [b, a];
  const pts = [{ time: p1.t, value: p1.p }, { time: p2.t, value: p2.p }];
  if (type === "ray") {
    const last = draw.candles.length - 1;
    const i2 = Math.max(ia, ib);
    if (last > i2) pts.push({ time: draw.candles[last].time, value: lineValueAt(a, b, last) });
  }
  return pts;
}

function makeLineSeries(color, dashed) {
  return tvChart.addLineSeries({
    color, lineWidth: 2, lineStyle: dashed ? 2 : 0,
    lastValueVisible: false, priceLineVisible: false,
    crosshairMarkerVisible: false, autoscaleInfoProvider: () => null,
  });
}

function renderDrawItem(it) {
  if (it.type === "hline") {
    it._obj = draw.series.createPriceLine({
      price: it.a.p, color: it.color, lineWidth: 2, lineStyle: 0,
      axisLabelVisible: true, title: "내 선",
    });
  } else {
    const pts = linePoints(it.type, it.a, it.b);
    if (!pts) return false;
    it._obj = makeLineSeries(it.color, false);
    it._obj.setData(pts);
  }
  return true;
}

function removeDrawObj(it) {
  if (!it._obj) return;
  try {
    if (it.type === "hline") draw.series.removePriceLine(it._obj);
    else tvChart.removeSeries(it._obj);
  } catch (err) {
    // 지우기에 실패하면 저장된 선 기준으로 차트를 새로 그려 확실히 지웁니다
    console.warn("선 지우기 실패 → 차트 다시 그림", err);
    draw.needRedraw = true;
  }
  it._obj = null;
}

function redrawIfNeeded() {
  if (!draw.needRedraw) return;
  draw.needRedraw = false;
  if (state.chartPayload) renderTradingViewChart(state.chartPayload);
}

function attachDrawings(symbol, candles, candleSeries) {
  draw.symbol = symbol;
  draw.candles = candles;
  draw.series = candleSeries;
  draw.idx = new Map(candles.map((c, i) => [c.time, i]));
  draw.first = null;
  draw.temp = null;
  draw.items = (loadAllDrawings()[symbol] || []).filter((it) => {
    const ok = renderDrawItem(it);
    return ok;
  });
  tvChart.subscribeClick(onDrawClick);
  tvChart.subscribeCrosshairMove(onDrawMove);
  setDrawTool(draw.tool === "erase" ? "erase" : null);
}

// 클릭 위치 → {t, p} (자석: 가까운 봉의 고가/저가에 붙이기)
function pointFromParam(param) {
  if (!param || !param.point || param.logical == null || !draw.candles.length) return null;
  const i = Math.max(0, Math.min(draw.candles.length - 1, Math.round(param.logical)));
  const c = draw.candles[i];
  let p = draw.series.coordinateToPrice(param.point.y);
  if (p == null) return null;
  if ($("drawMagnet").checked && draw.tool !== "erase") {
    const yH = draw.series.priceToCoordinate(c.high), yL = draw.series.priceToCoordinate(c.low);
    const dH = Math.abs(param.point.y - yH), dL = Math.abs(param.point.y - yL);
    if (Math.min(dH, dL) <= 14) p = dH <= dL ? c.high : c.low;
  }
  return { t: c.time, p: Number(p.toPrecision(8)) };
}

function setDrawHint(txt) { $("drawHint").textContent = txt || ""; }

function setDrawTool(tool) {
  draw.tool = tool;
  draw.first = null;
  drawMoveKey = "";
  cancelAnimationFrame(drawMoveRaf);
  if (draw.temp) { try { tvChart.removeSeries(draw.temp); } catch {} draw.temp = null; }
  document.querySelectorAll("#drawBar .draw-btn[data-tool]").forEach((b) =>
    b.classList.toggle("active", b.dataset.tool === tool));
  const cont = $("tvChartContainer");
  if (cont) cont.style.cursor = tool ? (tool === "erase" ? "not-allowed" : "crosshair") : "";
  const hints = {
    seg: "첫 번째 점을 클릭하세요 (Esc 취소)",
    ray: "첫 번째 점을 클릭하세요 — 오늘까지 연장됩니다 (Esc 취소)",
    hline: "수평선을 그을 가격을 클릭하세요 (Esc 취소)",
    erase: "지울 선을 클릭하세요 (Esc 종료)",
  };
  setDrawHint(tool ? hints[tool] : (draw.items.length ? `이 종목에 그린 선 ${draw.items.length}개` : ""));
}

function distToSeg(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const L = dx * dx + dy * dy;
  let t = L ? ((px - x1) * dx + (py - y1) * dy) / L : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function eraseAt(param) {
  if (!param || !param.point) return;
  const ts = tvChart.timeScale();
  let best = -1, bestD = 10;
  draw.items.forEach((it, k) => {
    let d = Infinity;
    if (it.type === "hline") {
      const y = draw.series.priceToCoordinate(it.a.p);
      if (y != null) d = Math.abs(param.point.y - y);
    } else {
      const pts = linePoints(it.type, it.a, it.b) || [];
      for (let j = 0; j + 1 < pts.length; j++) {
        const x1 = ts.timeToCoordinate(pts[j].time), y1 = draw.series.priceToCoordinate(pts[j].value);
        const x2 = ts.timeToCoordinate(pts[j + 1].time), y2 = draw.series.priceToCoordinate(pts[j + 1].value);
        if ([x1, y1, x2, y2].some((v) => v == null)) continue;
        d = Math.min(d, distToSeg(param.point.x, param.point.y, x1, y1, x2, y2));
      }
    }
    if (d < bestD) { bestD = d; best = k; }
  });
  if (best >= 0) {
    removeDrawObj(draw.items[best]);
    draw.items.splice(best, 1);
    saveDrawings();
    redrawIfNeeded();
    setDrawHint(`선을 지웠습니다 · 남은 선 ${draw.items.length}개 (Esc 종료)`);
  }
}

function onDrawClick(param) {
  if (!draw.tool) return;
  const snap = { point: param && param.point ? { ...param.point } : null, logical: param ? param.logical : null };
  setTimeout(() => handleDrawClick(snap), 0);
}

function handleDrawClick(param) {
  if (!draw.tool) return;
  if (draw.tool === "erase") { eraseAt(param); return; }
  const pt = pointFromParam(param);
  if (!pt) return;
  if (draw.tool === "hline") {
    const it = { type: "hline", a: pt, b: null, color: draw.color };
    if (renderDrawItem(it)) { draw.items.push(it); saveDrawings(); }
    setDrawTool(null);
    return;
  }
  if (!draw.first) {
    draw.first = pt;
    setDrawHint("두 번째 점을 클릭하세요 (Esc 취소)");
    return;
  }
  if (draw.idx.get(pt.t) === draw.idx.get(draw.first.t)) {
    setDrawHint("같은 날짜입니다 — 다른 날짜를 클릭하세요");
    return;
  }
  const it = { type: draw.tool, a: draw.first, b: pt, color: draw.color };
  if (renderDrawItem(it)) { draw.items.push(it); saveDrawings(); }
  setDrawTool(null);
}

// 차트 콜백 안에서 시리즈를 바로 바꾸면 콜백이 다시 불려 무한 반복되므로,
// 미리보기는 같은 점일 때 건너뛰고 다음 화면 갱신 때 한 번만 그립니다.
let drawMoveKey = "";
let drawMoveRaf = 0;
function onDrawMove(param) {
  if (!draw.first || (draw.tool !== "seg" && draw.tool !== "ray")) return;
  const pt = pointFromParam(param);
  if (!pt) return;
  const key = `${draw.tool}|${pt.t}|${pt.p}`;
  if (key === drawMoveKey) return;
  drawMoveKey = key;
  cancelAnimationFrame(drawMoveRaf);
  drawMoveRaf = requestAnimationFrame(() => {
    if (!draw.first) return;
    const pts = linePoints(draw.tool, draw.first, pt);
    if (!pts) return;
    if (!draw.temp) draw.temp = makeLineSeries(draw.color, true);
    draw.temp.setData(pts);
  });
}

function undoDrawing() {
  const it = draw.items.pop();
  if (!it) return;
  removeDrawObj(it);
  saveDrawings();
  setDrawTool(null);
  redrawIfNeeded();
}

function setupDrawing() {
  $("drawBar").addEventListener("click", (e) => {
    const btn = e.target.closest(".draw-btn[data-tool]");
    if (btn) { setDrawTool(draw.tool === btn.dataset.tool ? null : btn.dataset.tool); return; }
    const col = e.target.closest(".draw-color");
    if (col) {
      draw.color = col.dataset.color;
      $("drawColors").querySelectorAll(".draw-color").forEach((b) => b.classList.toggle("active", b === col));
    }
  });
  $("drawUndoBtn").addEventListener("click", undoDrawing);
  $("drawClearBtn").addEventListener("click", () => {
    if (!draw.items.length) return;
    if (!confirm(`이 종목에 그린 선 ${draw.items.length}개를 모두 지울까요?`)) return;
    draw.items.forEach(removeDrawObj);
    draw.items = [];
    saveDrawings();
    setDrawTool(null);
    redrawIfNeeded();
  });
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea") return;
    if (!$("tab-chart")?.classList.contains("active")) return;
    if (e.key === "Escape" && draw.tool) { e.stopImmediatePropagation(); setDrawTool(null); return; }
    if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "Z")) { e.preventDefault(); undoDrawing(); }
  }, true);
}

// ==================== 차트 크게 보기(전체화면) ====================
function isChartFocus() {
  return document.querySelector(".chart-main")?.classList.contains("focus");
}

function updateFocusLabel() {
  const el = $("focusAssetLabel");
  if (!el) return;
  const name = $("chartAssetName")?.textContent || "";
  const meta = $("chartAssetMeta")?.textContent || "";
  el.textContent = `${name}  ·  ${meta}  ▾`;
}

// ---- 크게 보기 화면의 종목 검색·선택 창 ----
const MARKET_KO = { KOSPI: "코스피", KOSDAQ: "코스닥", US: "미국", CRYPTO: "코인" };
let focusPickerMarket = "ALL";
let focusPickerIdx = 0;

function isFocusPickerOpen() {
  return $("focusPicker")?.classList.contains("open");
}

function renderFocusPicker() {
  const q = $("focusPickerInput").value.trim().toLowerCase();
  const list = state.assets.filter((a) => {
    if (focusPickerMarket !== "ALL" && a.market !== focusPickerMarket) return false;
    if (!q) return true;
    return (
      a.name.toLowerCase().includes(q) ||
      a.symbol.toLowerCase().includes(q) ||
      (a.theme || "").toLowerCase().includes(q)
    );
  });
  if (focusPickerIdx >= list.length) focusPickerIdx = Math.max(0, list.length - 1);
  $("focusPickerList").innerHTML = list.length
    ? list
        .map(
          (a, i) => `
      <div class="focus-picker-item ${i === focusPickerIdx ? "hover" : ""} ${a.symbol === state.selectedSymbol ? "current" : ""}" data-sym="${escHtml(a.symbol)}">
        <span class="fp-name">${escHtml(a.name)}</span>
        <span class="fp-sym">${escHtml(a.symbol)}${a.theme ? " · " + escHtml(a.theme) : ""}</span>
        <span class="mkt-tag mkt-${a.market}">${MARKET_KO[a.market] || a.market}</span>
      </div>`
        )
        .join("")
    : `<div class="focus-picker-empty">검색 결과가 없습니다</div>`;
  $("focusPickerList").querySelectorAll(".focus-picker-item").forEach((el) => {
    el.addEventListener("click", () => pickFocusAsset(el.dataset.sym));
  });
  const hov = $("focusPickerList").querySelector(".hover");
  if (hov) hov.scrollIntoView({ block: "nearest" });
}

function openFocusPicker(open) {
  const p = $("focusPicker");
  p.classList.toggle("open", open);
  if (open) {
    $("focusPickerInput").value = "";
    focusPickerIdx = 0;
    renderFocusPicker();
    setTimeout(() => $("focusPickerInput").focus(), 0);
  }
}

function pickFocusAsset(sym) {
  openFocusPicker(false);
  if (!sym || sym === state.selectedSymbol) return;
  state.selectedSymbol = sym;
  renderAssetList();
  loadChart(sym);
}

function setupFocusPicker() {
  $("focusAssetLabel").addEventListener("click", (e) => {
    e.stopPropagation();
    openFocusPicker(!isFocusPickerOpen());
  });
  $("focusPicker").addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => { if (isFocusPickerOpen()) openFocusPicker(false); });
  $("focusPickerInput").addEventListener("input", () => { focusPickerIdx = 0; renderFocusPicker(); });
  $("focusPickerInput").addEventListener("keydown", (e) => {
    const items = $("focusPickerList").querySelectorAll(".focus-picker-item");
    if (e.key === "ArrowDown") { e.preventDefault(); focusPickerIdx = Math.min(items.length - 1, focusPickerIdx + 1); renderFocusPicker(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); focusPickerIdx = Math.max(0, focusPickerIdx - 1); renderFocusPicker(); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[focusPickerIdx]) pickFocusAsset(items[focusPickerIdx].dataset.sym); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); openFocusPicker(false); }
  });
  $("focusPickerPills").addEventListener("click", (e) => {
    if (!e.target.classList.contains("pill")) return;
    $("focusPickerPills").querySelectorAll(".pill").forEach((b) => b.classList.remove("active"));
    e.target.classList.add("active");
    focusPickerMarket = e.target.dataset.market;
    focusPickerIdx = 0;
    renderFocusPicker();
    $("focusPickerInput").focus();
  });
}

function setChartFocus(on) {
  const main = document.querySelector(".chart-main");
  if (!main) return;
  main.classList.toggle("focus", on);
  document.body.classList.toggle("chart-focus-mode", on);
  if (!on) { main.classList.remove("hide-tools"); openFocusPicker(false); }
  $("chartFocusBtn").textContent = on ? "✕ 크게 보기 닫기" : "⛶ 차트 크게 보기";
  $("focusToolsBtn").textContent = main.classList.contains("hide-tools") ? "⚙ 설정 보이기" : "⚙ 설정 숨기기";
  updateFocusLabel();
  // 크기가 바뀐 뒤 다시 맞춤
  setTimeout(() => { if (tvChart) tvChart.timeScale().fitContent(); }, 80);
}

function stepFocusAsset(dir) {
  const items = Array.from($("assetList").querySelectorAll(".asset-item"));
  if (!items.length) return;
  let idx = items.findIndex((el) => el.dataset.sym === state.selectedSymbol);
  idx = idx < 0 ? 0 : (idx + dir + items.length) % items.length;
  items[idx].click();
}

function setupChartFocus() {
  setupFocusPicker();
  $("chartFocusBtn").addEventListener("click", () => setChartFocus(!isChartFocus()));
  $("focusExitBtn").addEventListener("click", () => setChartFocus(false));
  $("focusPrevBtn").addEventListener("click", () => stepFocusAsset(-1));
  $("focusNextBtn").addEventListener("click", () => stepFocusAsset(1));
  $("focusFitBtn").addEventListener("click", () => tvChart && tvChart.timeScale().fitContent());
  $("focusToolsBtn").addEventListener("click", () => {
    const main = document.querySelector(".chart-main");
    main.classList.toggle("hide-tools");
    $("focusToolsBtn").textContent = main.classList.contains("hide-tools") ? "⚙ 설정 보이기" : "⚙ 설정 숨기기";
  });
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea") return;
    const chartTabOn = $("tab-chart")?.classList.contains("active");
    if (e.key === "Escape" && isFocusPickerOpen()) { openFocusPicker(false); return; }
    if (e.key === "Escape" && isChartFocus()) { setChartFocus(false); return; }
    if (e.key === "/" && isChartFocus()) { e.preventDefault(); openFocusPicker(true); return; }
    if (!chartTabOn) return;
    if ((e.key === "f" || e.key === "F" || e.key === "ㄹ") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      setChartFocus(!isChartFocus());
    } else if (isChartFocus() && e.key === "ArrowLeft" && e.shiftKey) {
      stepFocusAsset(-1);
    } else if (isChartFocus() && e.key === "ArrowRight" && e.shiftKey) {
      stepFocusAsset(1);
    }
  });
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
    ALL: "전체 전체 종목",
    KOSPI: "코스피 70종목",
    KOSDAQ: "코스닥 70종목",
    US: "미국주식 80종목",
    CRYPTO: "코인 30종목",
  };
  $("researchScopeLabel").textContent = `${scopeNames[mkt] || mkt} 기준 (왕복 수수료 0.2% 반영)`;

  // Recommendation cards
  const cardDefs = [
    { key: "ALL", title: "🏆 전체 전체 종목 최적", highlight: true },
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
    state.scannerMap = {};
    (data.items || []).forEach((it) => {
      state.scannerMap[it.symbol] = it;
    });
    (data.indices || []).forEach((ix) => {
      state.scannerMap[ix.symbol] = ix;
    });
    if (data.rotation && data.rotation.markets) state.rotationData = data.rotation;
    renderTop30Board();
    renderRotationCard();
    renderPortfolioTab();
    renderScannerView();
    if (state.chartPayload) renderTradePlanCard();
  } catch (err) {
    showToast("스캐너 오류: " + err.message, 4500);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function updateChartPortfolioButtons() {
  const sym = state.selectedSymbol;
  if ($("chartStarBtn")) {
    const starred = isStarred(sym);
    $("chartStarBtn").textContent = starred ? "★ 관심중" : "☆ 관심";
  }
  if ($("chartAddHoldingBtn")) {
    const h = getHolding(sym);
    $("chartAddHoldingBtn").textContent = h ? "💼 보유 수정" : "💼 보유 등록";
  }
}

function renderTradePlanCard() {
  const box = $("tradePlanGrid");
  if (!box || !state.chartPayload) return;
  const asset = state.chartPayload.asset;
  const it = state.scannerMap[asset.symbol];
  if (!it || !it.trade_plan) {
    box.innerHTML = `<div class="muted">매매 계획 데이터를 계산 중입니다...</div>`;
    return;
  }
  const tp = it.trade_plan;
  const cur = asset.currency;
  const cap = Number($("calcCapitalInput").value) || (cur === "KRW" ? 10000000 : 10000);
  const maxRiskPct = Number($("calcRiskPctInput").value) || 2.0;
  const maxLossBudget = cap * (maxRiskPct / 100);
  const riskPerUnit = Math.max(tp.entry_price - tp.stop_loss, tp.entry_price * 0.01);
  const rawQty = maxLossBudget / riskPerUnit;
  const recQty = cur === "KRW" ? Math.max(1, Math.floor(rawQty)) : Number(rawQty.toFixed(asset.market === "CRYPTO" ? 4 : 2));
  const recInvest = recQty * tp.entry_price;
  const expGain = recQty * (tp.target_1 - tp.entry_price);
  const disp = getDisplayRating(it);

  box.innerHTML = `
    <div class="tp-box">
      <div class="tp-label">현재가 · 의견</div>
      <div class="tp-val">${fmtPrice(tp.entry_price, cur)}</div>
      <div class="tp-sub"><span class="rate-badge ${disp.badgeClass}" style="font-size:10px;padding:1px 6px;">${disp.label}</span></div>
    </div>
    <div class="tp-box">
      <div class="tp-label">자동 손절가 (${tp.stop_basis})</div>
      <div class="tp-val neg">${fmtPrice(tp.stop_loss, cur)}</div>
      <div class="tp-sub">손절폭 -${tp.risk_pct}%</div>
    </div>
    <div class="tp-box">
      <div class="tp-label">1차 목표가 (${tp.t1_basis})</div>
      <div class="tp-val pos">${fmtPrice(tp.target_1, cur)}</div>
      <div class="tp-sub">예상 +${tp.upside_t1_pct}% · 2차 ${fmtPrice(tp.target_2, cur)}</div>
    </div>
    <div class="tp-box">
      <div class="tp-label">손익비 (R:R) · RSI</div>
      <div class="tp-val" style="color:#82b1ff">1 : ${tp.rr_ratio}</div>
      <div class="tp-sub">${renderRsiBadge(it)}</div>
    </div>
    <div class="tp-box">
      <div class="tp-label">권장 매수 수량 (손실 ${maxRiskPct}%)</div>
      <div class="tp-val">${recQty.toLocaleString()} ${asset.market === "CRYPTO" ? "개" : "주"}</div>
      <div class="tp-sub">투입금 약 ${fmtPrice(recInvest, cur)}</div>
    </div>
    <div class="tp-box">
      <div class="tp-label">1차 목표 시 예상 수익</div>
      <div class="tp-val pos">+${fmtPrice(expGain, cur)}</div>
      <div class="tp-sub">최대 손절 한도 -${fmtPrice(maxLossBudget, cur)}</div>
    </div>
  `;
}

function probBarColor(prob) {
  if (prob >= 75) return "linear-gradient(90deg, #ff9100, #ffea00)";
  if (prob >= 66) return "linear-gradient(90deg, #00c853, #69f0ae)";
  if (prob >= 56) return "#ffd54f";
  if (prob >= 42) return "#64748b";
  return "#ef5350";
}

function renderMarketThermometer(mr) {
  const grid = $("marketThermometerGrid");
  if (!grid || !mr) return;
  const all = mr.ALL || {};
  $("marketRegimeOverall").textContent = `전체 전체 종목 중 MA200 위 ${all.ma200_above_pct ?? 0}% · 💎 과매도 ${all.oversold_count ?? 0}종목`;

  const defs = [
    { key: "KOSPI", label: "🇰🇷 코스피 (70)" },
    { key: "KOSDAQ", label: "🚀 코스닥 (70)" },
    { key: "US", label: "🇺🇸 미국주식 (80)" },
    { key: "CRYPTO", label: "🪙 코인 (30)" },
  ];
  grid.innerHTML = defs
    .map((d) => {
      const m = mr[d.key] || { ma200_above_pct: 0, ma200_bull_pct: 0, oversold_count: 0, regime_label: "-" };
      const pct = m.ma200_above_pct || 0;
      const color = pct >= 55 ? "#00e676" : pct >= 30 ? "#ffd54f" : "#ef5350";
      return `
        <div class="thermo-card">
          <div class="thermo-head">
            <span>${d.label}</span>
            <span style="color:${color};font-size:11.5px;">${m.regime_label}</span>
          </div>
          <div class="thermo-bar"><div class="thermo-fill" style="width:${pct}%;background:${color}"></div></div>
          <div class="thermo-sub">
            <span>MA200 위 <b>${pct}%</b> (평평/상승 ${m.ma200_bull_pct}%)</span>
            <span style="color:#40e0ff">💎과매도 ${m.oversold_count}</span>
          </div>
        </div>`;
    })
    .join("");
}

function renderIndicesBoard(indices) {
  const idxGrid = $("indicesGrid");
  const macroGrid = $("macroGrid");
  if (!idxGrid || !macroGrid || !indices) return;

  const eqIdx = indices.filter((x) => x.group === "INDEX");
  const macros = indices.filter((x) => x.group === "MACRO");

  idxGrid.innerHTML = eqIdx
    .map((x) => {
      const arrow = x.ma200_state === "up" ? "↗" : x.ma200_state === "flat" ? "→" : "↘";
      const prob = Number(x.upside_prob || 0);
      const valStr = x.unit === "$" ? fmtPrice(x.close, "USD") : Number(x.close).toLocaleString("en-US", { maximumFractionDigits: 1 });
      return `
        <div class="idx-card" data-sym="${x.symbol}">
          <div class="idx-top">
            <span class="idx-name">${x.name}</span>
            <span class="idx-etf">${x.etf_tip}</span>
          </div>
          <div class="idx-price-row">
            <span class="idx-price">${valStr}</span>
            <span class="${pctClass(x.change_pct)}" style="font-size:11.5px;">${fmtPct(x.change_pct)}</span>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:4px;">
            <span class="rate-badge rate-${x.rating}" style="font-size:10px;padding:2px 6px;">${x.rating_label}</span>
            <b style="font-size:12px;color:${prob >= 66 ? "#69f0ae" : prob >= 55 ? "#ffd54f" : "#9db0cc"}">${prob.toFixed(0)}%</b>
          </div>
          <div class="idx-meta">
            <span>200${x.above_ma200 ? "▲" : "▼"}${arrow} · 1M <b class="${pctClass(x.ret20_pct)}">${fmtPct(x.ret20_pct)}</b></span>
          </div>
          <div class="idx-meta">
            <span>RSI ${x.rsi14 !== null ? (x.rsi14 <= 36 ? `<b style="color:#40e0ff">💎${x.rsi14}</b>` : x.rsi14) : "-"}</span>
            <span>${x.weekly_bull ? '<span class="pos">주봉↗</span>' : '<span class="neg">주봉↘</span>'}</span>
          </div>
        </div>`;
    })
    .join("");

  macroGrid.innerHTML = macros
    .map((m) => {
      const valStr =
        m.unit === "%" ? `${Number(m.close).toFixed(2)}%`
        : m.unit === "원" ? `${Math.round(m.close).toLocaleString("ko-KR")}원`
        : Number(m.close).toFixed(2);
      return `
        <div class="macro-card" data-sym="${m.symbol}">
          <div>
            <div style="font-weight:700;font-size:12.5px;">${m.name} <span class="muted">(${m.etf_tip})</span></div>
            <div class="muted" style="font-size:11px;">1개월 ${fmtPct(m.ret20_pct)} · RSI ${m.rsi14 ?? "-"}</div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:15px;font-weight:800;">${valStr} <span class="${pctClass(m.change_pct)}" style="font-size:11px;">${fmtPct(m.change_pct)}</span></div>
            <span class="rate-badge rate-${m.status_code}" style="font-size:10px;padding:1px 7px;">${m.status_label}</span>
          </div>
        </div>`;
    })
    .join("");

  [...idxGrid.querySelectorAll(".idx-card"), ...macroGrid.querySelectorAll(".macro-card")].forEach((el) => {
    el.addEventListener("click", () => jumpToChart(el.dataset.sym, "S3"));
  });
}

function renderTop30Board() {
  const data = state.scannerData;
  if (!data || !data.items) return;

  renderIndicesBoard(data.indices);
  renderMarketThermometer(data.market_regime);

  const rc = data.rating_counts || {};
  const mySellAlerts = state.myHoldings.filter((h) => evaluateHoldingStatus(h, state.scannerMap[h.symbol]).alertLevel >= 2).length;
  $("top30RatingKpis").innerHTML = `
    <div class="kpi-box"><div><div class="muted">🔥 강력 매수</div><div class="muted">확률 75%↑ + PF≥1.2</div></div><div class="kpi-num" style="color:#ffab40">${rc.STRONG_BUY || 0}</div></div>
    <div class="kpi-box"><div><div class="muted">🟢 매수</div><div class="muted">확률 66~74%</div></div><div class="kpi-num pos">${rc.BUY || 0}</div></div>
    <div class="kpi-box"><div><div class="muted">🟡 매수 관심</div><div class="muted">확률 56~65%</div></div><div class="kpi-num" style="color:#ffd54f">${rc.WATCH_BUY || 0}</div></div>
    <div class="kpi-box"><div><div class="muted">💎 RSI 과매도</div><div class="muted">RSI ≤ 36 저점주목</div></div><div class="kpi-num" style="color:#40e0ff">${data.oversold_total || 0}</div></div>
    <div class="kpi-box" style="cursor:pointer" onclick="document.querySelector('.tab-btn[data-tab=portfolio]').click()"><div><div class="muted">💼 내 보유종목</div><div class="muted">매도경보 ${mySellAlerts}건</div></div><div class="kpi-num ${mySellAlerts > 0 ? "neg" : ""}" style="${mySellAlerts === 0 ? "color:#82b1ff" : ""}">${state.myHoldings.length}</div></div>
  `;

  $("top30UpdatedMeta").textContent = `기준: ${data.scanned_at}`;

  const ratingOrder = { STRONG_BUY: 4, BUY: 3, WATCH_BUY: 2, HOLD_WATCH: 1, SELL_WARN: 0 };
  const minRating = state.top30RatingFilter === "ALL" ? -1 : (ratingOrder[state.top30RatingFilter] ?? -1);

  const filtered = data.items
    .filter((it) => {
      if (state.top30MarketFilter !== "ALL" && it.market !== state.top30MarketFilter) return false;
      if (state.top30ThemeFilter !== "ALL" && it.theme !== state.top30ThemeFilter) return false;
      if ((ratingOrder[it.rating] ?? 0) < minRating) return false;
      if (state.top30OversoldOnly && (it.rsi14 === null || it.rsi14 > 36)) return false;
      if (state.top30RisingsOnly && !it.is_new_top30 && (it.prob_delta || 0) < 3 && (it.rank_delta || 0) < 3) return false;
      return true;
    })
    .sort((a, b) => (b.upside_prob - a.upside_prob) || (b.hist_pf_6y - a.hist_pf_6y) || (b.change_pct - a.change_pct))
    .slice(0, 30);

  if (filtered.length === 0) {
    $("top30TableBody").innerHTML = `<tr><td colspan="10" class="muted" style="text-align:center;padding:28px;">선택한 필터 조건에 해당하는 종목이 없습니다.</td></tr>`;
    return;
  }

  $("top30TableBody").innerHTML = filtered
    .map((it, idx) => {
      const rank = idx + 1;
      const prob = Number(it.upside_prob || 0);
      const tp = it.trade_plan || {};
      const disp = getDisplayRating(it);
      const deltaBadge = it.is_new_top30
        ? `<span class="delta-new">NEW</span>`
        : it.rank_delta > 0
        ? `<span class="delta-up">▲${it.rank_delta}</span>`
        : it.rank_delta < 0
        ? `<span class="delta-down">▼${Math.abs(it.rank_delta)}</span>`
        : "";
      const probDeltaStr =
        it.prob_delta > 0.4
          ? `<div class="delta-up" style="margin:0">+${it.prob_delta.toFixed(1)}%p</div>`
          : it.prob_delta < -0.4
          ? `<div class="delta-down" style="margin:0">${it.prob_delta.toFixed(1)}%p</div>`
          : "";
      const factorsHtml = (it.prob_factors || [])
        .map((f) => `<span class="factor-chip">${f}</span>`)
        .join("");
      const star = isStarred(it.symbol);
      return `
        <tr data-sym="${it.symbol}">
          <td><button class="star-btn ${star ? "starred" : ""}" data-star="${it.symbol}">${star ? "★" : "☆"}</button></td>
          <td class="num">
            <span class="rank-num ${rank <= 3 ? "rank-top3" : ""}">${rank <= 3 ? ["🥇", "🥈", "🥉"][rank - 1] : rank}</span>${deltaBadge}
          </td>
          <td><b>${it.name}</b>${disp.isHeld ? `<span class="hold-tag">보유</span>` : ""} <div class="muted">${it.symbol}</div></td>
          <td><span class="mkt-tag mkt-${it.market}">${it.market}</span><span class="theme-tag">${it.theme || ""}</span></td>
          <td>
            <div class="prob-cell">
              <div class="prob-bar-track"><div class="prob-bar-fill" style="width:${prob}%;background:${probBarColor(prob)}"></div></div>
              <div style="text-align:right"><span class="prob-num" style="color:${prob >= 66 ? "#69f0ae" : prob >= 56 ? "#ffd54f" : prob < 42 ? "#ff8a80" : "#c5d1e6"}">${prob.toFixed(1)}%</span>${probDeltaStr}</div>
            </div>
          </td>
          <td><span class="rate-badge ${disp.badgeClass}">${disp.label}</span></td>
          <td class="num"><div>${fmtPrice(it.close, it.currency)}</div><div class="${pctClass(it.change_pct)}" style="font-size:11px;">${fmtPct(it.change_pct)}</div></td>
          <td style="font-size:11px;">
            <div><span class="neg">손절 ${fmtPrice(tp.stop_loss, it.currency)}</span> (-${tp.risk_pct}%)</div>
            <div><span class="pos">목표 ${fmtPrice(tp.target_1, it.currency)}</span> · <b>1:${tp.rr_ratio}</b></div>
          </td>
          <td>${renderRsiBadge(it)}</td>
          <td>${factorsHtml || `<span class="muted">${it.reason}</span>`}</td>
        </tr>`;
    })
    .join("");

  $("top30TableBody").querySelectorAll("button[data-star]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleStar(btn.dataset.star);
    });
  });
  $("top30TableBody").querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => jumpToChart(tr.dataset.sym, "S3"));
  });
}

/* ==================== MY PORTFOLIO & WATCHLIST TAB ==================== */
function handleAddHolding() {
  const sym = $("pfSymbolSelect").value;
  const avgPrice = Number($("pfAvgPrice").value);
  const qty = Number($("pfQty").value);
  const buyDate = $("pfBuyDate").value || new Date().toISOString().slice(0, 10);
  const customStop = $("pfCustomStop").value ? Number($("pfCustomStop").value) : null;

  if (!sym || !(avgPrice > 0) || !(qty > 0)) {
    showToast("종목, 평균 매수가, 수량을 올바르게 입력해 주세요.");
    return;
  }
  const idx = state.myHoldings.findIndex((h) => h.symbol === sym);
  const entry = { symbol: sym, avgPrice, qty, buyDate, customStop };
  if (idx >= 0) {
    state.myHoldings[idx] = entry;
    showToast("보유종목 정보를 수정했습니다.");
  } else {
    state.myHoldings.push(entry);
    showToast("내 보유종목에 등록되었습니다!");
  }
  saveUserPortfolioStorage();
  $("pfAvgPrice").value = "";
  $("pfQty").value = "";
  $("pfCustomStop").value = "";
  updateChartPortfolioButtons();
  renderPortfolioTab();
  renderTop30Board();
  renderScannerView();
}

function removeHolding(sym) {
  state.myHoldings = state.myHoldings.filter((h) => h.symbol !== sym);
  saveUserPortfolioStorage();
  updateChartPortfolioButtons();
  renderPortfolioTab();
  renderTop30Board();
  renderScannerView();
  showToast("보유종목에서 삭제했습니다.");
}

async function exportPortfolioJson() {
  const blob = JSON.stringify({ holdings: state.myHoldings, watchlist: state.myWatchlist });
  try {
    await navigator.clipboard.writeText(blob);
    showToast("보유종목·관심종목 백업 데이터가 클립보드에 복사되었습니다!");
  } catch (_) {
    prompt("아래 백업 텍스트를 복사해 보관하세요:", blob);
  }
}

function importPortfolioJson() {
  const raw = prompt("복사해 둔 백업 JSON 텍스트를 붙여넣어 주세요:");
  if (!raw) return;
  try {
    const obj = JSON.parse(raw);
    if (Array.isArray(obj.holdings)) state.myHoldings = obj.holdings;
    if (Array.isArray(obj.watchlist)) state.myWatchlist = obj.watchlist;
    saveUserPortfolioStorage();
    renderPortfolioTab();
    renderTop30Board();
    renderScannerView();
    showToast("보유종목·관심종목 복원 완료!");
  } catch (err) {
    showToast("백업 데이터 형식이 올바르지 않습니다: " + err.message);
  }
}

function renderPortfolioTab() {
  const tbody = $("portfolioTableBody");
  const kpiWrap = $("portfolioKpis");
  const banner = $("portfolioAlertBanner");
  if (!tbody || !kpiWrap) return;

  let krCost = 0, krVal = 0, krDay = 0;
  let usCost = 0, usVal = 0, usDay = 0;
  const sellAlerts = [];
  const tpAlerts = [];

  const evalRows = state.myHoldings.map((h) => {
    const it = state.scannerMap[h.symbol];
    const asset = state.assets.find((a) => a.symbol === h.symbol) || { name: h.symbol, market: "", theme: "", currency: "USD" };
    const st = evaluateHoldingStatus(h, it);
    const cost = h.avgPrice * h.qty;
    const val = (it ? it.close : h.avgPrice) * h.qty;
    if (asset.currency === "KRW") {
      krCost += cost; krVal += val; krDay += st.dayAmt;
    } else {
      usCost += cost; usVal += val; usDay += st.dayAmt;
    }
    if (st.alertLevel >= 2) sellAlerts.push({ name: asset.name, label: st.label, detail: st.detail });
    if (st.alertLevel === 1) tpAlerts.push({ name: asset.name, label: st.label, detail: st.detail });
    return { h, it, asset, st, cost, val };
  });

  if (sellAlerts.length > 0 || tpAlerts.length > 0) {
    banner.classList.remove("hidden");
    const msgs = [
      ...sellAlerts.map((a) => `${a.label} · <b>${a.name}</b> (${a.detail})`),
      ...tpAlerts.map((a) => `${a.label} · <b>${a.name}</b> (${a.detail})`),
    ];
    banner.innerHTML = `🚨 <b>내 보유종목 점검 알림 (${msgs.length}건)</b>: ` + msgs.join(" &nbsp;|&nbsp; ");
  } else {
    banner.classList.add("hidden");
  }

  const krRet = krCost > 0 ? ((krVal / krCost) - 1) * 100 : 0;
  const usRet = usCost > 0 ? ((usVal / usCost) - 1) * 100 : 0;
  kpiWrap.innerHTML = `
    <div class="kpi-box"><div><div class="muted">🇰🇷 국내(KRW) 평가</div><div class="${pctClass(krVal - krCost)}">${fmtPrice(krVal - krCost, "KRW")} (${fmtPct(krRet)})</div></div><div class="kpi-num" style="font-size:18px;">${fmtPrice(krVal, "KRW")}</div></div>
    <div class="kpi-box"><div><div class="muted">🇺🇸·🪙 달러(USD) 평가</div><div class="${pctClass(usVal - usCost)}">${fmtPrice(usVal - usCost, "USD")} (${fmtPct(usRet)})</div></div><div class="kpi-num" style="font-size:18px;">${fmtPrice(usVal, "USD")}</div></div>
    <div class="kpi-box"><div><div class="muted">오늘 일일 변동</div><div class="muted">KRW / USD</div></div><div style="text-align:right;font-weight:700;"><div class="${pctClass(krDay)}">${krDay >= 0 ? "+" : ""}${fmtPrice(krDay, "KRW")}</div><div class="${pctClass(usDay)}">${usDay >= 0 ? "+" : ""}${fmtPrice(usDay, "USD")}</div></div></div>
    <div class="kpi-box"><div><div class="muted">🔴 매도·손절 경보</div><div class="muted">내 보유종목 기준</div></div><div class="kpi-num neg">${sellAlerts.length}</div></div>
    <div class="kpi-box"><div><div class="muted">🟣 익절검토 · 🟢 보유</div><div class="muted">총 ${state.myHoldings.length}종목</div></div><div class="kpi-num pos">${state.myHoldings.length - sellAlerts.length}</div></div>
  `;

  if (evalRows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="muted" style="text-align:center;padding:28px;">아직 등록된 보유종목이 없습니다. 위 폼에서 실제 보유 중인 종목의 매수가·수량을 입력하시면 수익률과 맞춤 매도/손절 경보가 자동 계산됩니다.</td></tr>`;
  } else {
    evalRows.sort((a, b) => b.st.alertLevel - a.st.alertLevel || b.st.pnlPct - a.st.pnlPct);
    tbody.innerHTML = evalRows
      .map(({ h, it, asset, st }) => {
        const cur = asset.currency;
        return `
          <tr data-sym="${h.symbol}">
            <td><b>${asset.name}</b><div class="muted">${h.symbol} · ${h.buyDate || ""}</div></td>
            <td><span class="mkt-tag mkt-${asset.market}">${asset.market}</span><span class="theme-tag">${asset.theme || ""}</span></td>
            <td class="num">${fmtPrice(h.avgPrice, cur)}</td>
            <td class="num"><div>${it ? fmtPrice(it.close, cur) : "-"}</div><div class="${it ? pctClass(it.change_pct) : ""}" style="font-size:11px;">${it ? fmtPct(it.change_pct) : "-"}</div></td>
            <td class="num">${Number(h.qty).toLocaleString()}</td>
            <td class="num"><div class="${pctClass(st.pnlPct)}" style="font-size:13px;">${fmtPct(st.pnlPct)}</div><div class="${pctClass(st.pnlAmt)}" style="font-size:11px;">${st.pnlAmt >= 0 ? "+" : ""}${fmtPrice(st.pnlAmt, cur)}</div></td>
            <td style="font-size:11px;"><div class="neg">손절 ${fmtPrice(st.stopLoss, cur)}</div><div class="pos">목표 ${fmtPrice(st.target1, cur)}</div></td>
            <td>${it ? renderRsiBadge(it) : "-"}</td>
            <td><span class="rate-badge ${st.badgeClass}">${st.label}</span><div class="muted" style="margin-top:2px;">${st.detail}</div></td>
            <td><button class="btn btn-secondary btn-sm del-hold-btn" data-del="${h.symbol}">삭제</button></td>
          </tr>`;
      })
      .join("");

    tbody.querySelectorAll("button[data-del]").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        removeHolding(b.dataset.del);
      });
    });
    tbody.querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => jumpToChart(tr.dataset.sym, "S3"));
    });
  }

  // Watchlist table
  const wbody = $("watchlistTableBody");
  if (!wbody) return;
  if (state.myWatchlist.length === 0) {
    wbody.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:20px;">관심종목이 없습니다. TOP 30이나 차트에서 ☆ 별표를 눌러 추가해 보세요.</td></tr>`;
  } else {
    wbody.innerHTML = state.myWatchlist
      .map((sym) => {
        const it = state.scannerMap[sym];
        const asset = state.assets.find((a) => a.symbol === sym) || { name: sym, market: "", theme: "", currency: "USD" };
        if (!it) return "";
        const tp = it.trade_plan || {};
        const disp = getDisplayRating(it);
        return `
          <tr data-sym="${sym}">
            <td><b>${asset.name}</b> <span class="muted">${sym}</span></td>
            <td><span class="mkt-tag mkt-${asset.market}">${asset.market}</span><span class="theme-tag">${asset.theme || ""}</span></td>
            <td class="num"><b>${it.upside_prob.toFixed(1)}%</b></td>
            <td><span class="rate-badge ${disp.badgeClass}">${disp.label}</span></td>
            <td class="num">${fmtPrice(it.close, asset.currency)} <span class="${pctClass(it.change_pct)}">${fmtPct(it.change_pct)}</span></td>
            <td>${renderRsiBadge(it)}</td>
            <td style="font-size:11px;">손절 ${fmtPrice(tp.stop_loss, asset.currency)} / 목표 ${fmtPrice(tp.target_1, asset.currency)} (1:${tp.rr_ratio})</td>
            <td>
              <button class="btn btn-secondary btn-sm w-to-hold" data-sym="${sym}">+ 보유</button>
              <button class="btn btn-secondary btn-sm w-unstar" data-sym="${sym}">★ 해제</button>
            </td>
          </tr>`;
      })
      .join("");

    wbody.querySelectorAll(".w-to-hold").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        const it = state.scannerMap[b.dataset.sym];
        $("pfSymbolSelect").value = b.dataset.sym;
        if (it) $("pfAvgPrice").value = it.close;
        $("pfQty").focus();
      });
    });
    wbody.querySelectorAll(".w-unstar").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleStar(b.dataset.sym);
      });
    });
    wbody.querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => jumpToChart(tr.dataset.sym, "S3"));
    });
  }
}

function renderScannerView() {
  const data = state.scannerData;
  if (!data) return;

  const mySellCnt = state.myHoldings.filter((h) => evaluateHoldingStatus(h, state.scannerMap[h.symbol]).alertLevel >= 2).length;
  $("scannerKpis").innerHTML = `
    <div class="kpi-box"><div><div class="muted">🟢 신규 매수</div><div class="muted">${data.strategy_name}</div></div><div class="kpi-num pos">${data.counts.BUY}</div></div>
    <div class="kpi-box"><div><div class="muted">🟡 돌파 임박</div><div class="muted">추세선 ${$("nearPctInput").value}% 이내</div></div><div class="kpi-num" style="color:#ffd54f">${data.counts.NEAR}</div></div>
    <div class="kpi-box"><div><div class="muted">💎 RSI 과매도</div><div class="muted">RSI ≤ 36 매수 주목</div></div><div class="kpi-num" style="color:#40e0ff">${data.oversold_total || 0}</div></div>
    <div class="kpi-box"><div><div class="muted">💼 내 보유 매도경보</div><div class="muted">보유 ${state.myHoldings.length}종목 중</div></div><div class="kpi-num ${mySellCnt > 0 ? "neg" : ""}" style="${mySellCnt === 0 ? "color:#82b1ff" : ""}">${mySellCnt}</div></div>
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
          <span style="color:#40e0ff">과매도 ${th.oversold || 0}</span><br/>
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

  const filteredItems = data.items.filter((it) => {
    if (state.scannerThemeFilter !== "ALL" && it.theme !== state.scannerThemeFilter) return false;
    if (state.scannerOversoldOnly && (it.rsi14 === null || it.rsi14 > 36)) return false;
    return true;
  });

  $("scannerTableBody").innerHTML = filteredItems
    .map((it) => {
      const h = getHolding(it.symbol);
      const disp = getDisplayRating(it);
      // Status column reflects user's own holdings for HOLD/SELL, and clean buy/near/oversold/watch for unowned stocks
      let statusHtml = `<span class="sig-badge sig-WATCH">⚪ 관망</span>`;
      if (h) {
        const st = evaluateHoldingStatus(h, it);
        statusHtml = st.alertLevel >= 2
          ? `<span class="sig-badge sig-SELL">🔴 보유매도</span>`
          : `<span class="sig-badge sig-HOLD">💼 보유중</span>`;
      } else if (it.signal === "BUY") {
        statusHtml = `<span class="sig-badge sig-BUY">🟢 신규매수</span>`;
      } else if (it.signal === "NEAR") {
        statusHtml = `<span class="sig-badge sig-NEAR">🟡 돌파임박</span>`;
      } else if (it.rsi14 !== null && it.rsi14 <= 36) {
        statusHtml = `<span class="rsi-oversold">💎 과매도</span>`;
      }
      return `
      <tr data-sym="${it.symbol}">
        <td>${statusHtml}</td>
        <td><span class="rate-badge ${disp.badgeClass}">${disp.label}</span></td>
        <td class="num"><b>${Number(it.upside_prob || 0).toFixed(1)}%</b></td>
        <td><b>${it.name}</b> <span class="muted">${it.symbol}</span></td>
        <td><span class="mkt-tag mkt-${it.market}">${it.market}</span><span class="theme-tag">${it.theme || ""}</span></td>
        <td class="num">${fmtPrice(it.close, it.currency)}</td>
        <td class="num ${pctClass(it.change_pct)}">${fmtPct(it.change_pct)}</td>
        <td>
          <span class="${it.above_ma20 ? "pos" : "neg"}">20${it.above_ma20 ? "▲" : "▼"}</span> ·
          <span class="${it.above_ma200 ? "pos" : "neg"}">200${it.above_ma200 ? "▲" : "▼"}</span> ·
          ${renderRsiBadge(it)}
        </td>
        <td class="num ${it.dist_short_upper_pct !== null && it.dist_short_upper_pct <= 0 ? "pos" : "muted"}">
          ${it.dist_short_upper_pct !== null ? fmtPct(it.dist_short_upper_pct) : "-"}
        </td>
        <td class="num ${it.dist_long_upper_pct !== null && it.dist_long_upper_pct <= 0 ? "pos" : "muted"}">
          ${it.dist_long_upper_pct !== null ? fmtPct(it.dist_long_upper_pct) : "-"}
        </td>
        <td class="muted">${h ? evaluateHoldingStatus(h, it).detail : it.reason}</td>
      </tr>`;
    })
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


/* ==================== PAPER ROTATION PORTFOLIO ==================== */
function renderRotationCard() {
  const grid = $("rotationGrid");
  if (!grid) return;
  const rot = state.rotationData;
  if (!rot || !rot.markets || Object.keys(rot.markets).length === 0) {
    grid.innerHTML = `<div class="muted">${rot && rot.error ? "순환 포트폴리오 계산 오류: " + escHtml(rot.error) : "시장별 최적(AUTO_BEST) 스캔에서 표시됩니다."}</div>`;
    return;
  }
  const labels = { KOSPI: "🇰🇷 코스피", KOSDAQ: "🚀 코스닥", US: "🇺🇸 미국", CRYPTO: "🪙 코인" };
  const pct = (v, d = 0) => `<span class="${v >= 0 ? "pos" : "neg"}">${v >= 0 ? "+" : ""}${Number(v).toFixed(d)}%</span>`;
  $("rotationMeta").textContent = `${rot.start}부터 재생 · 규칙은 2026-11-26 고정 (이후 성과가 진짜 검증)`;
  grid.innerHTML = Object.entries(rot.markets)
    .map(([mkt, m]) => {
      const ps = m.perf_since_start, bs = m.bnh_since_start, py = m.perf_ytd, by = m.bnh_ytd;
      const buys = m.orders_next_open.buy.map((x) => escHtml(x.name)).join(", ") || "없음";
      const sells = m.orders_next_open.sell.map((x) => escHtml(x.name)).join(", ") || "없음";
      const holds = m.holdings.length
        ? m.holdings
            .map(
              (h) => `<div data-sym="${escHtml(h.symbol)}" title="${escHtml(h.entry_date)} 진입 @ ${fmtPrice(h.entry_price, h.currency)}"><span>${h.sell_next_open ? "🔻 " : ""}${escHtml(h.name)}</span><span>${pct(h.return_pct, 1)} · ${h.weight_pct.toFixed(0)}%</span></div>`
            )
            .join("")
        : `<div class="muted">보유 없음 (현금 ${m.cash_pct.toFixed(0)}%)</div>`;
      return `
        <div class="rot-box">
          <div class="rot-head"><span>${labels[mkt] || mkt}</span><span class="rot-badge ${m.regime_on ? "on" : "off"}">지수필터 ${m.regime_on ? "켜짐 · 투자" : "꺼짐 · 현금화"}</span></div>
          <div class="muted" title="${escHtml(m.basis)}">${escHtml(m.label)} · ${m.slots}칸</div>
          <div class="rot-perf">
            <div class="muted">누적</div><div>${pct(ps.ret)} <span class="muted">(보유 ${pct(bs.ret)})</span></div>
            <div class="muted">올해</div><div>${pct(py.ret, 1)} <span class="muted">(보유 ${pct(by.ret, 1)})</span></div>
            <div class="muted">최대낙폭</div><div>${pct(ps.mdd)} <span class="muted">(보유 ${pct(bs.mdd)})</span></div>
            <div class="muted">기준일</div><div>${escHtml(m.as_of)}</div>
          </div>
          <div class="rot-orders">▶ <b>다음 시가 매수</b>: ${buys}<br>▶ <b>다음 시가 매도</b>: ${sells}</div>
          <div class="muted">보유 ${m.holdings.length}/${m.slots} · 현금 ${m.cash_pct.toFixed(0)}%</div>
          <div class="rot-hold">${holds}</div>
        </div>`;
    })
    .join("");
  grid.querySelectorAll(".rot-hold div[data-sym]").forEach((el) => {
    el.addEventListener("click", () => jumpToChart(el.dataset.sym, "S3"));
  });
  renderRotationCompare(rot.compare, labels, pct);
}

function renderRotationCompare(cmp, labels, pct) {
  const body = $("rotationCompareBody");
  if (!body) return;
  if (!cmp || !cmp.markets) {
    body.innerHTML = `<tr><td colspan="8" class="muted">비교 데이터가 없습니다.</td></tr>`;
    return;
  }
  $("rotationCompareMeta").textContent = `규칙 고정일 ${cmp.freeze_date}`;
  $("rotationCompareLegend").innerHTML = (cmp.candidates || [])
    .map((c) => `<b>${escHtml(c.label)}</b>: ${escHtml(c.desc)}`)
    .join(" &nbsp;|&nbsp; ");
  const cell = (p, d = 1) => (p ? pct(p.ret, d) : `<span class="muted">시작 전</span>`);
  const rows = [];
  Object.entries(cmp.markets).forEach(([mkt, m]) => {
    const best = Math.max(...m.rows.map((r) => (r.since_freeze ? r.since_freeze.ret : -1e9)));
    m.rows.forEach((r, i) => {
      const orders = [
        r.buy_next_open.length ? `매수 ${r.buy_next_open.map(escHtml).join(", ")}` : "",
        r.sell_next_open.length ? `매도 ${r.sell_next_open.map(escHtml).join(", ")}` : "",
      ].filter(Boolean).join(" / ") || `<span class="muted">없음</span>`;
      const star = r.since_freeze && r.since_freeze.ret === best && m.rows.filter((x) => x.since_freeze).length > 1 ? " 🏆" : "";
      rows.push(`<tr>
        ${i === 0 ? `<td rowspan="${m.rows.length + 1}"><b>${labels[mkt] || mkt}</b><div class="muted">${m.slots}칸 · ${escHtml(m.as_of)}</div></td>` : ""}
        <td title="${escHtml(r.rule)}">${escHtml(r.label)}${star}</td>
        <td>${cell(r.since_freeze)} <span class="muted">${r.forward_days ? r.forward_days + "일" : ""}</span></td>
        <td>${pct(r.ytd.ret, 1)}</td><td>${pct(r.since_start.ret)}</td><td>${pct(r.since_start.mdd)}</td>
        <td>${r.holdings}/${m.slots}</td><td style="max-width:280px">${orders}</td></tr>`);
    });
    rows.push(`<tr class="muted"><td>단순보유</td><td>${cell(m.bnh.since_freeze)}</td><td>${pct(m.bnh.ytd.ret, 1)}</td><td>${pct(m.bnh.since_start.ret)}</td><td>${pct(m.bnh.since_start.mdd)}</td><td>-</td><td>-</td></tr>`);
  });
  body.innerHTML = rows.join("");
}

function escHtml(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}


/* ==================== 화면 한국어 표시 (보이는 글자만 변환, 코드·데이터 키는 그대로) ==================== */
const KO_TERMS = [
  [/Buy\s*&\s*Hold/g, "단순보유"], [/B&H/g, "단순보유"],
  [/(^|[^A-Za-z0-9])MA200(?![0-9])/g, "$1200일선"], [/(^|[^A-Za-z0-9])MA50(?![0-9])/g, "$150일선"],
  [/(^|[^A-Za-z0-9])MA40(?![0-9])/g, "$140일선"], [/(^|[^A-Za-z0-9])MA20(?![0-9])/g, "$120일선"],
  [/(^|[^A-Za-z0-9])MA5(?![0-9])/g, "$15일선"], [/(^|[^A-Za-z])MDD(?![A-Za-z])/g, "$1최대낙폭"],
  [/R:R/g, "손익비"], [/(^|[^A-Za-z])(?:TOP|Top)\s*(\d+)/g, "$1상위 $2"], [/(^|[^A-Za-z])TOP(?![A-Za-z])/g, "$1상위"],
  [/(^|[^A-Za-z])PF(?![A-Za-z])/g, "$1이익계수"], [/(^|[^A-Za-z])NEW(?![A-Za-z])/g, "$1신규"],
  [/(^|[^A-Za-z])Sharpe(?![A-Za-z])/g, "$1샤프"], [/(^|[^A-Za-z])CAGR(?![A-Za-z])/g, "$1연복리"],
  [/TrendLine Quant Lab/g, "추세선 퀀트 연구소"],
];
function koText(t) {
  let out = t;
  for (const [rx, rep] of KO_TERMS) out = out.replace(rx, rep);
  return out;
}
function koTranslateNode(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentNode && /^(SCRIPT|STYLE|TEXTAREA)$/.test(n.parentNode.nodeName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  let n;
  while ((n = walker.nextNode())) {
    const v = n.nodeValue;
    if (/[A-Za-z]/.test(v)) {
      const k = koText(v);
      if (k !== v) n.nodeValue = k;
    }
  }
  root.querySelectorAll && root.querySelectorAll("[title],[placeholder]").forEach((el) => {
    ["title", "placeholder"].forEach((a) => {
      const v = el.getAttribute(a);
      if (v && /[A-Za-z]/.test(v)) {
        const k = koText(v);
        if (k !== v) el.setAttribute(a, k);
      }
    });
  });
}
document.addEventListener("DOMContentLoaded", () => {
  document.title = koText(document.title);
  koTranslateNode(document.body);
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === "characterData") {
        const v = m.target.nodeValue, k = koText(v);
        if (k !== v) m.target.nodeValue = k;
      } else m.addedNodes.forEach((nd) => (nd.nodeType === 3 ? (nd.nodeValue = koText(nd.nodeValue)) : nd.nodeType === 1 && koTranslateNode(nd)));
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
});
