(() => {
  'use strict';

  const PAIRS = [
    ['EUR_USD', 'EUR / USD', 'OANDA:EURUSD'],
    ['GBP_USD', 'GBP / USD', 'OANDA:GBPUSD'],
    ['USD_JPY', 'USD / JPY', 'OANDA:USDJPY'],
    ['AUD_USD', 'AUD / USD', 'OANDA:AUDUSD'],
    ['USD_CAD', 'USD / CAD', 'OANDA:USDCAD'],
    ['USD_CHF', 'USD / CHF', 'OANDA:USDCHF'],
    ['NZD_USD', 'NZD / USD', 'OANDA:NZDUSD'],
  ];

  const BACKTESTS = {
    legacy: { trades: 633, expectancy: -0.0959005565, pf: 0.8064611417, lcb: null, returnPct: -8.775413, prodPct: -0.7125167, label: 'legacy baseline' },
    q75d3: { trades: 20, expectancy: 0.218066, pf: 1.804, lcb: null, returnPct: null, prodPct: null, label: 'post-outcome development row' },
    q75d5: { trades: 39, expectancy: 0.0487460912, pf: 1.1386263932, lcb: -0.1795396317, returnPct: 0.28234197, prodPct: 0.13807196, label: 'selected development hypothesis' },
    q75d10: { trades: 52, expectancy: 0.083318, pf: 1.2076, lcb: null, returnPct: null, prodPct: null, label: 'post-outcome development row' },
  };

  const state = {
    route: location.pathname === '/news' ? 'news' : 'desk',
    symbol: 'EUR_USD',
    connected: false,
    refreshing: false,
    data: {
      account: null,
      positions: [],
      status: null,
      promotion: null,
      decisions: [],
      readiness: null,
      operations: null,
      operationEvents: [],
      fundamentals: [],
      history: [],
      events: [],
      quotes: {},
    },
    selectedTrace: null,
    decisionFilter: 'all',
    newsFilter: 'all',
    liveTimer: null,
    intelTimer: null,
  };

  const $ = (id) => document.getElementById(id);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const n = (value, fallback = 0) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const lower = (value) => String(value ?? '').toLowerCase();
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' })[char]);
  const money = (value, currency = state.data.account?.currency || 'USD') => {
    const num = Number(value);
    if (!Number.isFinite(num)) return '—';
    try { return new Intl.NumberFormat('en-US', { style:'currency', currency, maximumFractionDigits:2 }).format(num); }
    catch { return `${num.toFixed(2)} ${currency}`; }
  };
  const compact = (value, digits = 2) => {
    const num = Number(value);
    if (!Number.isFinite(num)) return '—';
    return new Intl.NumberFormat('en-US', { notation:'compact', maximumFractionDigits:digits }).format(num);
  };
  const pct = (value, digits = 1) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)}%` : '—';
  const price = (value, instrument = state.symbol) => {
    const num = Number(value);
    if (!Number.isFinite(num)) return '—';
    return num.toFixed(instrument.endsWith('JPY') ? 3 : 5);
  };
  const scoreText = (value) => {
    const num = Number(value);
    return Number.isFinite(num) ? (num >= 0 ? '+' : '') + num.toFixed(3) : '—';
  };
  const timeAgo = (value) => {
    if (!value) return '—';
    const ms = Date.now() - new Date(value).getTime();
    if (!Number.isFinite(ms)) return '—';
    const s = Math.max(0, Math.floor(ms / 1000));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  };
  const formatClock = (value) => {
    if (!value) return '—';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit', second:'2-digit' });
  };
  const pairMeta = (instrument = state.symbol) => PAIRS.find(([id]) => id === instrument) || [instrument, instrument.replace('_',' / '), `OANDA:${instrument.replace('_','')}`];

  function apiBase() {
    return (sessionStorage.getItem('forexApiBase') || '').replace(/\/$/, '');
  }

  function token() {
    return sessionStorage.getItem('forexApiToken') || '';
  }

  async function request(path) {
    const headers = { Accept: 'application/json' };
    if (token()) headers.Authorization = `Bearer ${token()}`;
    const response = await fetch(`${apiBase()}${path}`, { headers, cache:'no-store' });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || payload);
      } catch { /* retain status */ }
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    const type = response.headers.get('content-type') || '';
    return type.includes('application/json') ? response.json() : response.text();
  }

  async function safe(path, fallback = null) {
    try { return await request(path); }
    catch (error) {
      if (error.status === 401 || error.status === 503) setConnected(false);
      return fallback;
    }
  }

  function setConnected(connected) {
    state.connected = connected;
    $('connectButton').classList.toggle('connected', connected);
    $('connectionLabel').textContent = connected ? 'LINKED' : 'CONNECT';
    if (!connected) {
      $('runtimeOrbit').classList.remove('online');
      $('runtimeState').textContent = 'OFFLINE';
    }
  }

  function toast(title, message = '', error = false) {
    const node = document.createElement('div');
    node.className = `toast${error ? ' error' : ''}`;
    node.innerHTML = `<strong>${escapeHtml(title)}</strong>${message ? ` · ${escapeHtml(message)}` : ''}`;
    $('toastStack').appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }

  function setRoute(route, push = false) {
    state.route = route === 'news' ? 'news' : 'desk';
    document.body.classList.toggle('route-news', state.route === 'news');
    $('deskView').classList.toggle('active', state.route === 'desk');
    $('newsView').classList.toggle('active', state.route === 'news');
    $('viewEyebrow').textContent = state.route === 'desk' ? 'LIVE DECISION SURFACE' : 'MACRO / EVENT SURFACE';
    $$('.nav-item[data-route]').forEach((item) => item.classList.toggle('active', item.dataset.route === state.route));
    if (push) history.pushState({ route: state.route }, '', state.route === 'news' ? '/news' : '/');
    if (state.route === 'desk') setTimeout(() => renderTradingView(), 30);
  }

  function buildNavigation() {
    $$('.nav-item[data-route], .brand[data-route]').forEach((link) => {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        setRoute(link.dataset.route, true);
        window.scrollTo({ top:0, behavior:'smooth' });
      });
    });
    $$('[data-scroll="backtest"]').forEach((link) => link.addEventListener('click', (event) => {
      event.preventDefault();
      if (state.route !== 'desk') setRoute('desk', true);
      setTimeout(() => $('backtest').scrollIntoView({ behavior:'smooth', block:'start' }), 40);
    }));
    window.addEventListener('popstate', () => setRoute(location.pathname === '/news' ? 'news' : 'desk'));
  }

  function buildSymbolMenu() {
    $('symbolMenu').innerHTML = PAIRS.map(([id, label]) => `<button class="symbol-option${id === state.symbol ? ' active' : ''}" data-symbol="${id}" type="button"><span>${label}</span><small>${id}</small></button>`).join('');
    $('symbolButton').addEventListener('click', () => { $('symbolMenu').hidden = !$('symbolMenu').hidden; });
    document.addEventListener('click', (event) => {
      if (!$('symbolButton').contains(event.target) && !$('symbolMenu').contains(event.target)) $('symbolMenu').hidden = true;
    });
    $('symbolMenu').addEventListener('click', (event) => {
      const button = event.target.closest('[data-symbol]');
      if (!button) return;
      selectSymbol(button.dataset.symbol);
      $('symbolMenu').hidden = true;
    });
  }

  async function selectSymbol(instrument) {
    state.symbol = instrument;
    const [, label] = pairMeta();
    $('symbolDisplay').textContent = label;
    $('chartTitle').innerHTML = `${escapeHtml(label.replace(' / ', '/'))} <span>· 5M</span>`;
    $$('.symbol-option').forEach((node) => node.classList.toggle('active', node.dataset.symbol === instrument));
    renderPairList();
    renderTradingView();
    await refreshSymbolData();
  }

  function renderTradingView() {
    if (state.route !== 'desk') return;
    const host = $('tradingviewChart');
    if (!host) return;
    const [, , tvSymbol] = pairMeta();
    host.innerHTML = '';
    const wrapper = document.createElement('div');
    wrapper.className = 'tradingview-widget-container';
    wrapper.style.height = '100%';
    wrapper.style.width = '100%';
    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    widget.style.height = 'calc(100% - 0px)';
    widget.style.width = '100%';
    wrapper.appendChild(widget);
    const script = document.createElement('script');
    script.type = 'text/javascript';
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.text = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: '5',
      timezone: 'America/New_York',
      theme: 'dark',
      style: '1',
      locale: 'en',
      backgroundColor: 'rgba(8, 11, 13, 1)',
      gridColor: 'rgba(255, 255, 255, 0.035)',
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      calendar: false,
      support_host: 'https://www.tradingview.com',
    });
    wrapper.appendChild(script);
    host.appendChild(wrapper);
  }

  async function refreshAll({ quiet = false } = {}) {
    if (state.refreshing) return;
    state.refreshing = true;
    $('refreshButton').classList.add('loading');
    const encoded = encodeURIComponent(state.symbol);
    try {
      const [account, positions, statusData, promotion, decisions, readiness, operations, operationEvents, fundamentals, historyData, events, quote] = await Promise.all([
        safe('/v1/account'),
        safe('/v1/positions', []),
        safe('/v1/status'),
        safe('/v1/promotion'),
        safe('/v1/decisions?limit=100', []),
        safe(`/v1/readiness/${encoded}`),
        safe('/v1/operations/summary?hours=24'),
        safe('/v1/operations/events?hours=24&limit=80', []),
        safe('/v1/fundamentals/snapshots', []),
        safe('/v1/fundamentals/history', []),
        safe('/v1/events/scheduled', []),
        safe(`/v1/market/${encoded}/quote`),
      ]);

      if (account) state.data.account = account;
      state.data.positions = Array.isArray(positions) ? positions : [];
      if (statusData) state.data.status = statusData;
      if (promotion) state.data.promotion = promotion;
      state.data.decisions = Array.isArray(decisions) ? decisions : [];
      if (readiness) state.data.readiness = readiness;
      if (operations) state.data.operations = operations;
      state.data.operationEvents = Array.isArray(operationEvents) ? operationEvents : [];
      state.data.fundamentals = Array.isArray(fundamentals) ? fundamentals : [];
      state.data.history = Array.isArray(historyData) ? historyData : [];
      state.data.events = Array.isArray(events) ? events : [];
      if (quote) state.data.quotes[state.symbol] = quote;

      const hasRuntime = Boolean(account || statusData || decisions.length || readiness);
      setConnected(hasRuntime);
      if (hasRuntime) {
        $('lastSync').textContent = formatClock(new Date());
        await refreshPositionMarks();
      }
      renderAll();
      if (!quiet && hasRuntime) toast('Runtime synchronized', `${state.symbol} observational state refreshed`);
    } finally {
      state.refreshing = false;
      $('refreshButton').classList.remove('loading');
    }
  }

  async function refreshSymbolData() {
    const encoded = encodeURIComponent(state.symbol);
    const [readiness, quote] = await Promise.all([
      safe(`/v1/readiness/${encoded}`),
      safe(`/v1/market/${encoded}/quote`),
    ]);
    if (readiness) state.data.readiness = readiness;
    if (quote) state.data.quotes[state.symbol] = quote;
    renderHeader();
    renderDecisionPrism();
    renderPositions();
  }

  async function refreshPositionMarks() {
    const instruments = [...new Set(state.data.positions.map((item) => item.instrument).filter(Boolean))];
    await Promise.all(instruments.map(async (instrument) => {
      if (instrument === state.symbol && state.data.quotes[instrument]) return;
      const quote = await safe(`/v1/market/${encodeURIComponent(instrument)}/quote`);
      if (quote) state.data.quotes[instrument] = quote;
    }));
  }

  function renderAll() {
    renderHeader();
    renderAccount();
    renderPairList();
    renderPositions();
    renderDecisionPrism();
    renderDecisionTape();
    renderTelemetry();
    renderRiskMap();
    renderNews();
    renderEvents();
  }

  function renderHeader() {
    const statusData = state.data.status || {};
    const readiness = state.data.readiness || {};
    const quote = state.data.quotes[state.symbol] || {};
    const mode = String(statusData.mode || '—').toUpperCase();
    const runtime = statusData.runtime || {};
    const runtimeHealthy = runtime.healthy === true;
    $('runtimeOrbit').classList.toggle('online', runtimeHealthy);
    $('runtimeState').textContent = runtimeHealthy
      ? 'AUTONOMOUS'
      : runtime.active
        ? (runtime.stale ? 'STALE' : 'DEGRADED')
        : 'IDLE';
    $('modeValue').textContent = mode;
    $('modePill').className = `status-pill ${mode === 'PAPER' ? 'good' : mode === '—' ? '' : 'warn'}`;
    $('readinessValue').textContent = readiness.ready === true ? 'READY' : readiness.ready === false ? 'BLOCKED' : '—';
    $('readinessPill').className = `status-pill ${readiness.ready === true ? 'good' : readiness.ready === false ? 'bad' : ''}`;
    const bid = n(quote.bid, NaN), ask = n(quote.ask, NaN);
    const mid = Number.isFinite(bid) && Number.isFinite(ask) ? (bid + ask) / 2 : NaN;
    $('quoteMid').textContent = price(mid);
    $('bidPrice').textContent = price(bid);
    $('askPrice').textContent = price(ask);
    if (Number.isFinite(bid) && Number.isFinite(ask)) {
      const pip = state.symbol.endsWith('JPY') ? 0.01 : 0.0001;
      $('quoteSpread').textContent = `SPREAD ${((ask - bid) / pip).toFixed(2)} PIP`;
    } else $('quoteSpread').textContent = 'SPREAD —';
    const trace = currentTrace();
    $('sessionPhase').textContent = String(trace?.metadata?.session_phase || '—').toUpperCase();
  }

  function renderAccount() {
    const account = state.data.account || {};
    $('accountCurrency').textContent = account.currency || '—';
    $('accountNav').textContent = money(account.nav, account.currency || 'USD');
    $('accountBalance').textContent = money(account.balance, account.currency || 'USD');
    $('accountUPL').textContent = money(account.unrealized_pl, account.currency || 'USD');
    $('accountUPL').className = n(account.unrealized_pl) > 0 ? 'positive' : n(account.unrealized_pl) < 0 ? 'negative' : '';
    $('dailyRealized').textContent = money(account.realized_pl_today, account.currency || 'USD');
    const used = n(account.margin_used), available = n(account.margin_available);
    const utilization = used + available > 0 ? (used / (used + available)) * 100 : 0;
    $('marginBar').style.width = `${Math.min(100, utilization)}%`;
    $('marginUsedPct').textContent = pct(utilization, 2);
    $('marginAvailable').textContent = money(account.margin_available, account.currency || 'USD');
    $('paperAuthority').textContent = state.data.status?.paper_orders_enabled ? 'ENABLED' : 'DISABLED';
    $('openRiskCount').textContent = `${state.data.positions.length} POS`;
    const promotion = state.data.promotion;
    $('promotionState').textContent = promotion ? (promotion.ready ? 'READY' : 'GATED') : '—';
  }

  function latestTraceFor(instrument) {
    return state.data.decisions.find((trace) => trace.instrument === instrument) || null;
  }

  function currentTrace() {
    if (state.selectedTrace?.instrument === state.symbol) return state.selectedTrace;
    return latestTraceFor(state.symbol) || state.data.decisions[0] || null;
  }

  function renderPairList() {
    $('decisionCount').textContent = `${state.data.decisions.length} traces`;
    $('pairList').innerHTML = PAIRS.map(([id, label]) => {
      const trace = latestTraceFor(id);
      const disposition = lower(trace?.candidate?.disposition);
      const stateClass = disposition === 'trade' ? 'trade' : trace ? 'reject' : '';
      const reason = trace?.candidate?.rejection_code || trace?.candidate?.reasons?.[0] || 'No recent trace';
      return `<button class="pair-card ${stateClass}${id === state.symbol ? ' active' : ''}" data-pair="${id}" type="button"><strong>${label}</strong><span></span><small>${escapeHtml(reason)} · ${timeAgo(trace?.created_at)}</small></button>`;
    }).join('');
    $$('[data-pair]', $('pairList')).forEach((button) => button.addEventListener('click', () => selectSymbol(button.dataset.pair)));
  }

  function positionNet(position) {
    return n(position.long_units) + n(position.short_units);
  }

  function positionAverage(position) {
    const net = positionNet(position);
    return net >= 0 ? position.long_average_price : position.short_average_price;
  }

  function renderPositions() {
    const positions = state.data.positions.filter((position) => positionNet(position) !== 0);
    const account = state.data.account || {};
    $('positionCount').textContent = String(positions.length);
    const totalPnl = positions.reduce((sum, position) => sum + n(position.unrealized_pl), 0);
    $('positionPnl').textContent = money(totalPnl, account.currency || 'USD');
    $('positionPnl').className = totalPnl > 0 ? 'positive' : totalPnl < 0 ? 'negative' : '';
    if (!positions.length) {
      $('positionsBody').innerHTML = '<tr class="empty-row"><td colspan="7">No broker positions are currently open.</td></tr>';
      return;
    }
    $('positionsBody').innerHTML = positions.map((position) => {
      const net = positionNet(position);
      const side = net > 0 ? 'LONG' : 'SHORT';
      const quote = state.data.quotes[position.instrument] || {};
      const mark = net > 0 ? quote.bid : quote.ask;
      const pnl = n(position.unrealized_pl);
      return `<tr data-position-symbol="${escapeHtml(position.instrument)}"><td><strong>${escapeHtml(position.instrument.replace('_',' / '))}</strong></td><td class="${side === 'LONG' ? 'positive' : 'negative'}">${side}</td><td>${compact(Math.abs(net), 3)}</td><td>${price(positionAverage(position), position.instrument)}</td><td>${price(mark, position.instrument)}</td><td class="${pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : ''}">${money(pnl, account.currency || 'USD')}</td><td><span class="status-tag good">BROKER OPEN</span></td></tr>`;
    }).join('');
    $$('[data-position-symbol]', $('positionsBody')).forEach((row) => row.addEventListener('dblclick', () => selectSymbol(row.dataset.positionSymbol)));
  }

  function setPipeline(id, text, stateClass) {
    const textNode = $(id);
    textNode.textContent = text;
    const node = textNode.closest('.pipeline-node');
    node.classList.remove('complete', 'denied', 'wait');
    if (stateClass) node.classList.add(stateClass);
  }

  function renderDecisionPrism() {
    const trace = currentTrace();
    if (!trace) {
      $('traceId').textContent = 'NO TRACE';
      $('decisionDirection').textContent = '—';
      $('decisionDisposition').textContent = 'WAITING';
      $('fusionScore').textContent = '—';
      $('scoreOrbit').style.setProperty('--score', 0);
      $('decisionReason').textContent = 'No engine decision has been loaded for this pair.';
      ['technicalStage','fundamentalStage','fusionStage','gateStage','riskStage','executionStage'].forEach((id) => setPipeline(id, 'waiting', ''));
      return;
    }
    state.selectedTrace = trace;
    const candidate = trace.candidate || {};
    const risk = trace.risk || null;
    const order = trace.order || null;
    const disposition = lower(candidate.disposition);
    const riskDisposition = lower(risk?.disposition);
    const orderStatus = lower(order?.status);
    const fusion = n(candidate.score);
    const normalized = Math.min(100, Math.max(0, Math.abs(fusion) <= 1 ? Math.abs(fusion) * 100 : Math.abs(fusion)));
    $('traceId').textContent = trace.trace_id ? `#${String(trace.trace_id).slice(0,8)}` : 'TRACE';
    $('decisionDirection').textContent = String(candidate.direction || '—').toUpperCase();
    $('decisionDisposition').textContent = String(candidate.disposition || 'OBSERVE').toUpperCase();
    $('fusionScore').textContent = scoreText(candidate.score);
    $('scoreOrbit').style.setProperty('--score', normalized.toFixed(1));
    $('decisionReason').textContent = candidate.rejection_code || candidate.reasons?.[0] || risk?.reasons?.[0] || (order ? `Broker order ${order.status}` : 'Candidate evaluated without a dominant textual reason.');

    setPipeline('technicalStage', `score ${scoreText(candidate.technical_score)}`, 'complete');
    setPipeline('fundamentalStage', `score ${scoreText(candidate.fundamental_score)}`, 'complete');
    setPipeline('fusionStage', disposition || 'evaluated', disposition === 'trade' ? 'complete' : 'wait');
    setPipeline('gateStage', candidate.rejection_code ? candidate.rejection_code : 'passed', candidate.rejection_code ? 'denied' : 'complete');
    if (risk) setPipeline('riskStage', riskDisposition || 'evaluated', riskDisposition === 'granted' ? 'complete' : 'denied');
    else setPipeline('riskStage', disposition === 'trade' ? 'not reached' : 'not requested', 'wait');
    if (order) setPipeline('executionStage', orderStatus || 'submitted', ['protected','filled'].includes(orderStatus) ? 'complete' : ['rejected','cancelled','emergency_close'].includes(orderStatus) ? 'denied' : 'wait');
    else setPipeline('executionStage', 'not submitted', 'wait');
  }

  function decisionRow(trace, index) {
    const candidate = trace.candidate || {};
    const risk = trace.risk || {};
    const order = trace.order || {};
    const disposition = lower(candidate.disposition);
    const reason = candidate.rejection_code || candidate.reasons?.[0] || risk.reasons?.[0] || '—';
    return `<tr data-trace-index="${index}"><td>${formatClock(trace.created_at)}</td><td><strong>${escapeHtml((trace.instrument || '—').replace('_',' / '))}</strong></td><td>${escapeHtml(String(candidate.direction || '—').toUpperCase())}</td><td><span class="status-tag ${disposition === 'trade' ? 'good' : 'warn'}">${escapeHtml(candidate.disposition || '—')}</span></td><td>${scoreText(candidate.technical_score)}</td><td>${scoreText(candidate.fundamental_score)}</td><td>${scoreText(candidate.score)}</td><td>${escapeHtml(risk.disposition || '—')}</td><td>${escapeHtml(order.status || '—')}</td><td title="${escapeHtml(reason)}">${escapeHtml(String(reason).slice(0,58))}</td></tr>`;
  }

  function filteredDecisions() {
    if (state.decisionFilter === 'trade') return state.data.decisions.filter((trace) => lower(trace?.candidate?.disposition) === 'trade');
    if (state.decisionFilter === 'reject') return state.data.decisions.filter((trace) => lower(trace?.candidate?.disposition) !== 'trade');
    return state.data.decisions;
  }

  function renderDecisionTape() {
    const rows = filteredDecisions();
    if (!rows.length) {
      $('decisionsBody').innerHTML = '<tr class="empty-row"><td colspan="10">No decision traces match this view.</td></tr>';
      return;
    }
    $('decisionsBody').innerHTML = rows.map((trace, index) => decisionRow(trace, index)).join('');
    $$('[data-trace-index]', $('decisionsBody')).forEach((row) => row.addEventListener('click', () => openTrace(rows[Number(row.dataset.traceIndex)])));
  }

  function renderTelemetry() {
    const metrics = state.data.promotion?.metrics || {};
    $('decisionRate').textContent = compact(metrics.decisions ?? state.data.decisions.length, 2);
    $('tradeCandidates').textContent = compact(metrics.trade_candidates, 2);
    $('orderRejects').textContent = compact(metrics.rejected_orders, 2);
    const degraded = state.data.readiness?.degraded_sources || [];
    $('degradedCount').textContent = Array.isArray(degraded) ? String(degraded.length) : '—';
    $('degradedMeta').textContent = Array.isArray(degraded) && degraded.length ? String(degraded.slice(0,2).join(' · ')).slice(0,44) : 'readiness graph';
  }

  function renderRiskMap() {
    const account = state.data.account || {};
    const used = n(account.margin_used), available = n(account.margin_available);
    const load = used + available > 0 ? (used / (used + available)) * 100 : 0;
    $('currentRiskLoad').textContent = pct(load, 2);
    $('riskMarginUsed').textContent = money(account.margin_used, account.currency || 'USD');
    $('riskMarginFree').textContent = money(account.margin_available, account.currency || 'USD');
    $('riskPositions').textContent = String(state.data.positions.filter((p) => positionNet(p) !== 0).length);
    $('riskNav').textContent = money(account.nav, account.currency || 'USD');
    const angle = (load / 100) * Math.PI * 1.6 - Math.PI * .8;
    const radius = 55 * Math.min(1, load / 100 + .1);
    $('riskRadarDot').style.transform = `translate(calc(-50% + ${Math.cos(angle) * radius}px), calc(-50% + ${Math.sin(angle) * radius}px))`;
  }

  function renderBacktest() {
    const result = BACKTESTS[$('backtestPolicy').value] || BACKTESTS.q75d5;
    $('btExpectancy').textContent = `${result.expectancy >= 0 ? '+' : ''}${result.expectancy.toFixed(5)}R`;
    $('btTrades').textContent = String(result.trades);
    $('btPf').textContent = result.pf.toFixed(3);
    $('btLcb').textContent = result.lcb == null ? 'NOT RECORDED' : `${result.lcb.toFixed(5)}R`;
    $('btReturn').textContent = result.returnPct == null ? 'NOT RECORDED' : `${result.returnPct >= 0 ? '+' : ''}${result.returnPct.toFixed(3)}%`;
    $('btProdReturn').textContent = result.prodPct == null ? 'NOT RECORDED' : `${result.prodPct >= 0 ? '+' : ''}${result.prodPct.toFixed(3)}%`;
    $('btExpectancyFlag').textContent = result.label;
    const sequence = result.expectancy >= 0 ? [0.16,0.34,0.26,0.51,0.41,0.66,0.58,0.74,0.61,0.83,0.72,0.92] : [0.72,0.55,0.61,0.42,0.48,0.37,0.33,0.29,0.23,0.19,0.13,0.09];
    $('replayChart').innerHTML = sequence.map((value, index) => {
      const isNegative = result.expectancy < 0 && index > 5;
      return `<div class="replay-bar${isNegative ? ' negative' : ''}" style="height:${Math.max(12,value*170)}px"><span>${index + 1}</span></div>`;
    }).join('');
  }

  function renderNews() {
    const snapshots = state.data.fundamentals;
    $('fundamentalAge').textContent = snapshots.length ? `${snapshots.length} currencies` : 'NO FEED';
    if (!snapshots.length) {
      $('currencyMatrix').innerHTML = '<div class="empty-state">Connect to render point-in-time currency state.</div>';
    } else {
      $('currencyMatrix').innerHTML = snapshots.map((item) => {
        const score = n(item.score, n(item.policy)*.35 + n(item.inflation)*.2 + n(item.growth)*.15 + n(item.labor)*.15 + n(item.news)*.15);
        return `<article class="currency-card${score < 0 ? ' negative' : ''}" style="--score-abs:${Math.min(1,Math.abs(score))}"><header><strong>${escapeHtml(item.currency || '—')}</strong><span>${scoreText(score)}</span></header><div class="factor-row"><div><small>POLICY</small><em>${scoreText(item.policy)}</em></div><div><small>GROWTH</small><em>${scoreText(item.growth)}</em></div><div><small>NEWS</small><em>${scoreText(item.news)}</em></div></div></article>`;
      }).join('');
    }

    const filtered = state.newsFilter === 'all' ? state.data.history : state.data.history.filter((item) => lower(item.kind) === state.newsFilter);
    if (!filtered.length) {
      $('newsFeed').innerHTML = '<div class="empty-state">No macro observations match this view.</div>';
      return;
    }
    $('newsFeed').innerHTML = [...filtered].reverse().map((item) => {
      const payload = item.payload || item.data || {};
      const headline = item.headline || payload.headline || item.category || payload.category || `${item.kind || 'observation'} · ${item.currency || '—'}`;
      const body = item.body || payload.body || item.source || payload.source || 'Point-in-time macro observation';
      const source = item.source || payload.source || 'source recorded';
      return `<article class="news-item"><div class="news-kind">${escapeHtml(item.kind || 'macro')}</div><div class="news-content"><strong>${escapeHtml(headline)}</strong><p>${escapeHtml(String(body).slice(0,300))}</p></div><div class="news-meta"><span>${escapeHtml(item.currency || payload.currency || '—')}</span><small>${timeAgo(item.available_at || item.observed_at || item.created_at)}</small><small>${escapeHtml(String(source).slice(0,28))}</small></div></article>`;
    }).join('');
  }

  function renderEvents() {
    const events = [...state.data.events].sort((a,b) => new Date(a.scheduled_at) - new Date(b.scheduled_at));
    $('eventCount').textContent = `${events.length} scheduled`;
    const now = Date.now();
    const next = events.find((event) => new Date(event.scheduled_at).getTime() >= now);
    if (next) {
      const diff = Math.max(0, new Date(next.scheduled_at).getTime() - now);
      const hours = Math.floor(diff / 3600000), minutes = Math.floor((diff % 3600000) / 60000);
      $('nextEventCountdown').textContent = `${String(hours).padStart(2,'0')}:${String(minutes).padStart(2,'0')}`;
      $('nextEventDetail').textContent = `${next.currency || '—'} · ${next.name || 'Scheduled event'} · ${new Date(next.scheduled_at).toLocaleString()}`;
    } else {
      $('nextEventCountdown').textContent = '—';
      $('nextEventDetail').textContent = 'No future scheduled event loaded.';
    }
    if (!events.length) {
      $('eventTimeline').innerHTML = '<div class="empty-state">No scheduled events loaded.</div>';
      return;
    }
    $('eventTimeline').innerHTML = events.slice(0,24).map((event) => `<article class="timeline-item ${lower(event.importance) === 'high' ? 'high' : ''}"><small>${new Date(event.scheduled_at).toLocaleString()}</small><strong>${escapeHtml(event.currency || '—')} · ${escapeHtml(event.name || 'Scheduled event')}</strong><p>${escapeHtml(event.importance || 'importance unknown')} · blackout ${Math.round(n(event.pre_blackout?.seconds || event.pre_blackout_seconds, 900)/60)}m before</p></article>`).join('');
  }

  function traceSection(title, rows, statusText = '') {
    return `<section class="trace-section"><header><strong>${escapeHtml(title)}</strong><span>${escapeHtml(statusText)}</span></header><div class="trace-kv">${rows.map(([key,value]) => `<div><small>${escapeHtml(key)}</small><strong>${escapeHtml(value ?? '—')}</strong></div>`).join('')}</div></section>`;
  }

  function openTrace(trace) {
    if (!trace) return;
    state.selectedTrace = trace;
    const candidate = trace.candidate || {};
    const risk = trace.risk || {};
    const order = trace.order || {};
    $('traceDrawerTitle').textContent = `${(trace.instrument || 'FX').replace('_',' / ')} decision`;
    const reasons = [...(candidate.reasons || []), ...(risk.reasons || [])];
    $('traceInspector').innerHTML = [
      traceSection('TRACE IDENTITY', [['trace', trace.trace_id], ['created', trace.created_at], ['instrument', trace.instrument], ['session', trace.metadata?.session_phase]], candidate.disposition || ''),
      traceSection('CANDIDATE', [['direction', candidate.direction], ['fusion score', scoreText(candidate.score)], ['technical', scoreText(candidate.technical_score)], ['fundamental', scoreText(candidate.fundamental_score)], ['entry', candidate.entry_price], ['stop', candidate.stop_loss], ['target', candidate.take_profit], ['setup family', candidate.setup_family], ['setup state', candidate.setup_state], ['rejection', candidate.rejection_code]], candidate.disposition || ''),
      traceSection('RISK AUTHORIZATION', [['disposition', risk.disposition], ['units', risk.units], ['risk amount', risk.risk_amount], ['account', risk.account_id], ['max units', risk.maximum_units], ['max loss', risk.maximum_loss], ['policy', risk.risk_policy_version]], risk.disposition || 'not requested'),
      traceSection('EXECUTION', [['status', order.status], ['units', order.units], ['fill', order.fill_price], ['provider order', order.provider_order_id], ['provider trade', order.provider_trade_id], ['protection', order.protection_confirmed ? 'confirmed' : '—']], order.status || 'not submitted'),
      `<section class="trace-section"><header><strong>REASONS</strong><span>${reasons.length}</span></header><ul class="trace-reasons">${reasons.length ? reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join('') : '<li>No textual reason recorded.</li>'}</ul></section>`,
      `<section class="trace-section"><header><strong>RAW TRACE</strong><span>JSON</span></header><pre class="trace-json">${escapeHtml(JSON.stringify(trace, null, 2))}</pre></section>`,
    ].join('');
    openDrawer('trace');
  }

  function openDrawer(kind) {
    $('drawerBackdrop').hidden = false;
    if (kind === 'connection') {
      $('apiBaseInput').value = apiBase();
      $('apiTokenInput').value = token();
      $('connectionDrawer').classList.add('open');
      $('connectionDrawer').setAttribute('aria-hidden', 'false');
    } else {
      $('traceDrawer').classList.add('open');
      $('traceDrawer').setAttribute('aria-hidden', 'false');
    }
  }

  function closeDrawers() {
    $('connectionDrawer').classList.remove('open');
    $('traceDrawer').classList.remove('open');
    $('connectionDrawer').setAttribute('aria-hidden', 'true');
    $('traceDrawer').setAttribute('aria-hidden', 'true');
    setTimeout(() => { $('drawerBackdrop').hidden = true; }, 180);
  }

  function bindControls() {
    $('refreshButton').addEventListener('click', () => refreshAll());
    $('connectButton').addEventListener('click', () => openDrawer('connection'));
    $('closeConnection').addEventListener('click', closeDrawers);
    $('closeTrace').addEventListener('click', closeDrawers);
    $('drawerBackdrop').addEventListener('click', closeDrawers);
    $('saveConnection').addEventListener('click', async () => {
      const base = $('apiBaseInput').value.trim().replace(/\/$/, '');
      const credential = $('apiTokenInput').value.trim();
      if (base) sessionStorage.setItem('forexApiBase', base); else sessionStorage.removeItem('forexApiBase');
      if (credential) sessionStorage.setItem('forexApiToken', credential); else sessionStorage.removeItem('forexApiToken');
      closeDrawers();
      await refreshAll({ quiet:true });
      if (state.connected) toast('Control plane linked', 'Live observational state is active');
      else { toast('Connection not authorized', 'Check API base and bearer token', true); openDrawer('connection'); }
    });
    $('clearConnection').addEventListener('click', () => {
      sessionStorage.removeItem('forexApiToken');
      sessionStorage.removeItem('forexApiBase');
      setConnected(false);
      toast('Session credential cleared');
    });
    $('inspectDecision').addEventListener('click', () => openTrace(currentTrace()));
    $$('.pipeline-node').forEach((node) => node.addEventListener('click', () => openTrace(currentTrace())));
    $('tapeFilters').addEventListener('click', (event) => {
      const button = event.target.closest('[data-filter]');
      if (!button) return;
      state.decisionFilter = button.dataset.filter;
      $$('[data-filter]', $('tapeFilters')).forEach((item) => item.classList.toggle('active', item === button));
      renderDecisionTape();
    });
    $('newsFilters').addEventListener('click', (event) => {
      const button = event.target.closest('[data-news-filter]');
      if (!button) return;
      state.newsFilter = button.dataset.newsFilter;
      $$('[data-news-filter]', $('newsFilters')).forEach((item) => item.classList.toggle('active', item === button));
      renderNews();
    });
    $('backtestPolicy').addEventListener('change', renderBacktest);
    $('renderBacktest').addEventListener('click', () => { renderBacktest(); toast('Recorded run rendered', 'No new outcome window was accessed'); });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeDrawers();
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openDrawer('connection'); }
    });
  }

  function init() {
    buildNavigation();
    buildSymbolMenu();
    bindControls();
    setRoute(state.route);
    renderPairList();
    renderBacktest();
    renderTradingView();
    refreshAll({ quiet:true });
    state.liveTimer = setInterval(() => refreshAll({ quiet:true }), 15000);
    state.intelTimer = setInterval(() => {
      if (document.visibilityState === 'visible' && !state.refreshing) refreshAll({ quiet:true });
    }, 60000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && Date.now() - (new Date($('lastSync').textContent).getTime() || 0) > 15000) refreshAll({ quiet:true });
    });
  }

  window.addEventListener('DOMContentLoaded', init);
})();
