'use strict';

// ---------------- 工具 ----------------
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
let STATE = null;
let SIDE = 'buy';
let curQuote = null;
let DAY_BAR = null;        // 当前代码在当前交易日的日线 {open,high,low,close,...}
let TRADE_DATE = null;     // 当前模拟交易日
let LATEST_DAY = null;     // 库中最新交易日
let calYear, calMonth;     // 日历弹层正在显示的年月 (0-based month)

let TOKEN = localStorage.getItem('paper_token') || '';

async function api(path, opts) {
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers, TOKEN ? { 'X-Auth-Token': TOKEN } : {});
  const res = await fetch(path, opts);
  if (res.status === 401) { showAuth(); throw new Error('未登录'); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

const fmt = (n, d = 2) => (n == null || isNaN(n)) ? '--'
  : Number(n).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtSigned = (n, d = 2) => (n == null || isNaN(n)) ? '--' : (n > 0 ? '+' : '') + fmt(n, d);
const cls = (n) => n > 0 ? 'up' : (n < 0 ? 'down' : 'flat');

function fmtInstHolderInline(it, kind) {
  if (kind === 'etf') return '';
  const n = it.inst_holder_count;
  const rd = it.inst_holder_report_date || '';
  if (n == null || n === '') {
    return '<span class="inst-hold na" title="无当年完整披露">· 机构 N/A</span>';
  }
  const src = it.inst_holder_source === 'database' ? ' (本地库)' : (it.inst_holder_source === 'sina' ? ' (新浪)' : '');
  const tip = rd ? `报告期 ${rd}${src}` : '主力数据';
  return `<span class="inst-hold" title="${tip}">· 机构 ${n} 家</span>`;
}

function instHolderLoadingHtml() {
  return '<span class="inst-hold loading" data-inst-load title="机构家数加载中">· 机构 <span class="spin"></span></span>';
}

function applyInstHolders(map, kind) {
  if (kind === 'etf') return;
  $$('#selBody tr[data-code]').forEach(tr => {
    const slot = tr.querySelector('[data-inst-load]');
    if (!slot) return;
    const it = map[tr.dataset.code] || {};
    slot.outerHTML = fmtInstHolderInline(it, kind);
  });
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), 2200);
}

// ---------------- 统一弹层 (替代 confirm / prompt) ----------------
let _dlgMode = null;   // 'confirm' | 'prompt'
let _dlgResolve = null;

function _closeDlg() {
  $('#dlgMask').classList.remove('show');
  $('#dlgInput').classList.remove('show');
  _dlgMode = null;
  _dlgResolve = null;
}

function _finishDlg(value) {
  const fn = _dlgResolve;
  _closeDlg();
  if (fn) fn(value);
}

function uiConfirm(message, title) {
  title = title || '确认';
  return new Promise((resolve) => {
    _dlgMode = 'confirm';
    _dlgResolve = resolve;
    $('#dlgTitle').textContent = title;
    $('#dlgMsg').textContent = message;
    $('#dlgInput').classList.remove('show');
    $('#dlgCancel').style.display = '';
    $('#dlgOk').textContent = '确定';
    $('#dlgMask').classList.add('show');
  });
}

function uiPrompt(message, defaultValue, title) {
  title = title || '输入';
  defaultValue = defaultValue != null ? String(defaultValue) : '';
  return new Promise((resolve) => {
    _dlgMode = 'prompt';
    _dlgResolve = resolve;
    $('#dlgTitle').textContent = title;
    $('#dlgMsg').textContent = message;
    const inp = $('#dlgInput');
    inp.classList.add('show');
    inp.value = defaultValue;
    $('#dlgCancel').style.display = '';
    $('#dlgOk').textContent = '确定';
    $('#dlgMask').classList.add('show');
    setTimeout(() => { inp.focus(); inp.select(); }, 50);
  });
}

function initDialog() {
  $('#dlgOk').onclick = () => {
    if (_dlgMode === 'prompt') _finishDlg($('#dlgInput').value);
    else if (_dlgMode === 'confirm') _finishDlg(true);
  };
  $('#dlgCancel').onclick = () => {
    if (_dlgMode === 'prompt') _finishDlg(null);
    else if (_dlgMode === 'confirm') _finishDlg(false);
  };
  $('#dlgMask').addEventListener('click', (e) => {
    if (e.target.id === 'dlgMask') {
      if (_dlgMode === 'prompt') _finishDlg(null);
      else if (_dlgMode === 'confirm') _finishDlg(false);
    }
  });
  $('#dlgInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); $('#dlgOk').click(); }
    else if (e.key === 'Escape') { e.preventDefault(); $('#dlgCancel').click(); }
  });
  document.addEventListener('keydown', (e) => {
    if (!_dlgResolve || _dlgMode !== 'confirm') return;
    if (e.key === 'Escape') { e.preventDefault(); $('#dlgCancel').click(); }
    else if (e.key === 'Enter') { e.preventDefault(); $('#dlgOk').click(); }
  });
}

// ---------------- 市场规则 (前端轻量副本, 用于步进/整手) ----------------
function bare(code) {
  let s = String(code || '').trim().toUpperCase();
  if (s.includes('.')) s = s.split('.')[0];
  ['SH', 'SZ', 'BJ', 'HK'].forEach(p => {
    if (s.startsWith(p) && /^\d+$/.test(s.slice(p.length))) s = s.slice(p.length);
  });
  return s;
}
function isHK(code) { const b = bare(code); return /^\d{1,5}$/.test(b) && b.length <= 5 && !/^\d{6}$/.test(b); }
function priceTick(code) {
  const b = bare(code);
  if (isHK(code)) return 0.001;
  if (/^(51|52|56|58|15|16|50)/.test(b)) return 0.001;   // 基金
  if (/^(11|12)/.test(b)) return 0.001;                   // 可转债
  return 0.01;
}
function minLot(code) {
  const b = bare(code);
  if (isHK(code)) return 1;
  if (/^(688|689)/.test(b)) return 200;   // 科创板
  if (/^(11|12)/.test(b)) return 10;      // 可转债
  return 100;
}
function qtyStep(code) {
  const b = bare(code);
  if (isHK(code)) return 1;
  if (/^(688|689|300|301)/.test(b)) return 1;   // 科创/创业
  if (/^[48]\d{5}$/.test(b) || /^920/.test(b)) return 1; // 北交所
  if (/^(11|12)/.test(b)) return 10;
  return 100;
}

// ---------------- 渲染 ----------------
function render(state) {
  STATE = state;
  const s = state.summary;
  if (state.trade_date) { TRADE_DATE = state.trade_date; $('#dateCur').textContent = state.trade_date; }
  $('#acctName').textContent = state.account;
  $('#totalAsset').textContent = fmt(s.total_asset);
  const tp = $('#todayPnl'); tp.textContent = `${fmtSigned(s.today_pnl)} (${fmtSigned(s.today_pnl_pct)}%)`;
  tp.className = 'pnl ' + cls(s.today_pnl);
  const zp = $('#totalPnl'); zp.textContent = `${fmtSigned(s.total_pnl)} (${fmtSigned(s.total_pnl_pct)}%)`;
  zp.className = 'pnl ' + cls(s.total_pnl);
  $('#availCash').textContent = fmt(s.available_cash);
  $('#marketValue').textContent = fmt(s.market_value);

  renderPositions(state.positions);
  renderOrders(state.orders);
  renderTrades(state.trades);
  refreshQtyHint();
}

function renderPositions(list) {
  const body = $('#posBody');
  if (!list || !list.length) { body.innerHTML = '<tr class="empty"><td colspan="6">暂无持仓</td></tr>'; return; }
  body.innerHTML = list.map(p => `
    <tr data-code="${p.code}" data-avail="${p.available}">
      <td><div class="cell-2"><b>${p.name || '-'}</b><small>${p.code}</small></div></td>
      <td class="r"><div class="cell-2"><span class="${cls(p.change_pct)}">${fmt(p.price, 3)}</span><small class="${cls(p.change_pct)}">${fmtSigned(p.change_pct)}%</small></div></td>
      <td class="r"><div class="cell-2"><span>${p.volume}</span><small>${p.available}</small></div></td>
      <td class="r"><div class="cell-2"><span>${fmt(p.avg_cost, 3)}</span><small>${fmt(p.market_value)}</small></div></td>
      <td class="r"><div class="cell-2"><span class="${cls(p.float_pnl)}">${fmtSigned(p.float_pnl)}</span><small class="${cls(p.float_pnl)}">${fmtSigned(p.pnl_pct)}%</small></div></td>
      <td class="op"><button class="mini-btn sell" data-sell="${p.code}">卖</button></td>
    </tr>`).join('');
}

function renderOrders(list) {
  const body = $('#orderBody');
  if (!list || !list.length) { body.innerHTML = '<tr class="empty"><td colspan="5">暂无委托</td></tr>'; return; }
  const stMap = { filled: '已成', pending: '挂单', cancelled: '已撤', failed: '废单' };
  body.innerHTML = list.map(o => `
    <tr>
      <td><div class="cell-2"><b>${o.name || o.code}</b><small>${(o.created_at || '').slice(5, 16)} ${o.code}</small></div></td>
      <td class="r"><div class="cell-2"><span class="badge ${o.direction}">${o.direction === 'buy' ? '买' : '卖'}</span><small>${o.price_type === 'market' ? '市价' : '限价'}</small></div></td>
      <td class="r"><div class="cell-2"><span>${o.price_type === 'market' ? '市价' : fmt(o.price, 3)}</span><small>${o.quantity}</small></div></td>
      <td class="r"><span class="badge st-${o.status}">${stMap[o.status] || o.status}</span>${o.note ? `<div><small class="flat">${o.note}</small></div>` : ''}</td>
      <td class="op">${o.status === 'pending' ? `<button class="mini-btn cancel" data-cancel="${o.order_id}">撤</button>` : ''}</td>
    </tr>`).join('');
}

function renderTrades(list) {
  const body = $('#tradeBody');
  if (!list || !list.length) { body.innerHTML = '<tr class="empty"><td colspan="5">暂无成交</td></tr>'; return; }
  body.innerHTML = list.map(t => `
    <tr>
      <td><div class="cell-2"><b>${t.name || t.code}</b><small>${(t.ts || '').slice(0, 16)} ${t.code}</small></div></td>
      <td class="r"><span class="badge ${t.direction}">${t.direction === 'buy' ? '买' : '卖'}</span></td>
      <td class="r"><div class="cell-2"><span>${fmt(t.price, 3)}</span><small>${t.quantity}</small></div></td>
      <td class="r"><div class="cell-2"><span>${fmt(t.amount)}</span><small class="flat">费 ${fmt(t.fees)}</small></div></td>
      <td class="op"><button class="mini-btn cancel" data-deltrade="${t.trade_id}">删</button></td>
    </tr>`).join('');
}

// ---------------- 交易面板 ----------------
function setSide(side) {
  SIDE = side;
  $$('.seg-btn').forEach(b => b.classList.toggle('active', b.dataset.side === side));
  const btn = $('#submitBtn');
  btn.textContent = side === 'buy' ? '买入' : '卖出';
  btn.className = 'submit-btn ' + side;
  refreshQtyHint();
  updateEstimate();
}

function currentCode() { return $('#codeInput').value.trim(); }

function refreshQtyHint() {
  const hint = $('#qtyHint');
  if (SIDE === 'buy') {
    hint.textContent = STATE ? `可用 ¥${fmt(STATE.summary.available_cash)}` : '';
  } else {
    const pos = posOf(currentCode());
    hint.textContent = pos ? `可卖 ${pos.available}` : '可卖 0';
  }
}

function posOf(code) {
  if (!STATE || !code) return null;
  const b = bare(code);
  return STATE.positions.find(p => bare(p.code) === b) || null;
}

// 输入代码后: 优先取「当前交易日」的日线区间; 无则退化到实时报价
async function refreshCode(code) {
  if (!code) { DAY_BAR = null; hideRange(); return; }
  try {
    const bar = await api(`/api/day_range?code=${encodeURIComponent(code)}&date=${encodeURIComponent(TRADE_DATE || '')}`);
    DAY_BAR = bar;
    curQuote = { price: bar.close, name: bar.name, change_pct: bar.change_pct };
    $('#qName').textContent = bar.name || bare(code);
    $('#qPrice').textContent = fmt(bar.close, 3);
    $('#qPrice').className = 'q-price ' + cls(bar.change_pct);
    const c = $('#qChg'); c.textContent = `${fmtSigned(bar.change_pct)}%`; c.className = 'q-chg ' + cls(bar.change_pct);
    showRange(bar);
    // 价格默认填当日收盘 (在区间内)
    const cur = Number($('#priceInput').value) || 0;
    if (!cur || cur < bar.low || cur > bar.high) $('#priceInput').value = bar.close;
    updateEstimate();
    refreshQtyHint();
  } catch (e) {
    DAY_BAR = null;
    hideRange();
    await fetchQuote(code);   // 无当日日线 -> 实时报价降级
  }
}

function showRange(bar) {
  const box = $('#rangeLine');
  box.style.display = '';
  $('#rlLow').textContent = fmt(bar.low, 3);
  $('#rlHigh').textContent = fmt(bar.high, 3);
  const inp = $('#priceInput');
  inp.min = bar.low; inp.max = bar.high;
}
function hideRange() { $('#rangeLine').style.display = 'none'; const inp = $('#priceInput'); inp.removeAttribute('min'); inp.removeAttribute('max'); }

async function fetchQuote(code) {
  if (!code) return;
  try {
    const q = await api('/api/quote?code=' + encodeURIComponent(code));
    curQuote = q;
    $('#qName').textContent = q.name || bare(code);
    $('#qPrice').textContent = fmt(q.price, 3);
    $('#qPrice').className = 'q-price ' + cls(q.change_pct);
    const c = $('#qChg'); c.textContent = `${fmtSigned(q.change_pct)}%`; c.className = 'q-chg ' + cls(q.change_pct);
    if (!$('#priceInput').value || Number($('#priceInput').value) === 0) {
      $('#priceInput').value = q.price;
    }
  } catch (e) {
    curQuote = null;
    $('#qName').textContent = bare(code) || '—';
    $('#qPrice').textContent = '无行情'; $('#qPrice').className = 'q-price flat';
    $('#qChg').textContent = '';
  }
  updateEstimate();
}

// ---------------- 交易日切换 + 日历 ----------------
async function loadTradeDate() {
  try {
    const d = await api('/api/trade_date');
    TRADE_DATE = d.trade_date; LATEST_DAY = d.latest;
    $('#dateCur').textContent = d.trade_date || '--';
    $('#dateLatest').textContent = d.latest ? `最新 ${d.latest}` : '';
  } catch (e) { /* 无 DB, 保持默认 */ }
}

async function setTradeDate(date) {
  try {
    const snap = await api('/api/trade_date', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date }),
    });
    render(snap);
    toast('交易日 → ' + date);
    if (currentCode()) refreshCode(currentCode());
  } catch (e) { toast('切换失败: ' + e.message); }
}

async function stepDay(direction) {
  try {
    const snap = await api('/api/trade_date/step?direction=' + direction);
    render(snap);
    toast('交易日 → ' + snap.trade_date);
    if (currentCode()) refreshCode(currentCode());
  } catch (e) { toast(e.message || '没有更多交易日'); }
}

// ---------------- QMT 日K 同步 + 结算 ----------------
let SYNC_POLL = null;

function syncPhaseLabel(phase) {
  const m = { etf: 'ETF', stock: 'A股', settle: '结算', done: '完成', error: '失败' };
  return m[phase] || phase || '';
}

function updateSyncStatus(st) {
  const el = $('#syncStatus');
  if (!el) return;
  if (!st || !st.running) {
    el.textContent = '';
    return;
  }
  el.textContent = `${syncPhaseLabel(st.phase)} ${Math.round(st.elapsed || 0)}s`;
}

async function pollSyncStatus() {
  clearTimeout(SYNC_POLL);
  const tick = async () => {
    let st;
    try { st = await api('/api/sync/status'); }
    catch (e) { SYNC_POLL = setTimeout(tick, 2000); return; }
    updateSyncStatus(st);
    if (st.running) {
      SYNC_POLL = setTimeout(tick, 1500);
      return;
    }
    $('#syncBtn').disabled = false;
    if (st.error) {
      toast('同步失败: ' + st.error);
      return;
    }
    const parts = [];
    if (st.etf_rows != null) parts.push(`ETF ${st.etf_rows}`);
    if (st.stock_rows != null) parts.push(`股 ${st.stock_rows}`);
    if (st.latest) parts.push('最新 ' + st.latest);
    toast('同步完成' + (parts.length ? ' · ' + parts.join(' · ') : ''));
    await load();
    await loadTradeDate();
    if (currentCode()) refreshCode(currentCode());
  };
  tick();
}

async function runDataSync() {
  if ($('#syncBtn').disabled) return;
  if (!await uiConfirm(
    '从 QMT 同步最近 15 日 A股/ETF 日K线, 并结算挂单更新盈亏。\n需已启动 MiniQMT。',
    '同步数据'
  )) return;
  $('#syncBtn').disabled = true;
  updateSyncStatus({ running: true, phase: 'etf', elapsed: 0 });
  try {
    await api('/api/sync/kline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days_back: 15, concurrency: 4, source: 'qmt' }),
    });
    pollSyncStatus();
  } catch (e) {
    $('#syncBtn').disabled = false;
    updateSyncStatus(null);
    toast('启动同步失败: ' + e.message);
  }
}

async function openCalendar() {
  const base = TRADE_DATE ? new Date(TRADE_DATE) : new Date();
  calYear = base.getFullYear(); calMonth = base.getMonth();
  $('#calMask').classList.add('show');
  $('#calPop').classList.add('show');
  await renderCalendar();
}
function closeCalendar() { $('#calMask').classList.remove('show'); $('#calPop').classList.remove('show'); }

async function renderCalendar() {
  const pad = (n) => String(n).padStart(2, '0');
  const start = `${calYear}-${pad(calMonth + 1)}-01`;
  const lastDay = new Date(calYear, calMonth + 1, 0).getDate();
  const end = `${calYear}-${pad(calMonth + 1)}-${pad(lastDay)}`;
  $('#calTitle').textContent = `${calYear}年${calMonth + 1}月`;
  let valid = new Set();
  try { const r = await api(`/api/calendar?start=${start}&end=${end}`); valid = new Set(r.days || []); } catch (e) {}

  const firstDow = (new Date(calYear, calMonth, 1).getDay() + 6) % 7; // 周一为首列
  let html = '';
  for (let i = 0; i < firstDow; i++) html += '<span class="cal-cell empty"></span>';
  for (let d = 1; d <= lastDay; d++) {
    const iso = `${calYear}-${pad(calMonth + 1)}-${pad(d)}`;
    const on = valid.has(iso);
    const isCur = iso === TRADE_DATE;
    html += `<span class="cal-cell ${on ? 'on' : 'off'} ${isCur ? 'cur' : ''}" ${on ? `data-day="${iso}"` : ''}>${d}</span>`;
  }
  $('#calGrid').innerHTML = html;
}

function calShiftMonth(delta) {
  calMonth += delta;
  if (calMonth < 0) { calMonth = 11; calYear--; }
  else if (calMonth > 11) { calMonth = 0; calYear++; }
  renderCalendar();
}

function stepPrice(dir) {
  const inp = $('#priceInput');
  const tick = priceTick(currentCode());
  let v = Number(inp.value) || 0;
  v = Math.max(0, +(v + dir * tick).toFixed(3));
  inp.value = v;
  updateEstimate();
}
function stepQty(dir) {
  const inp = $('#qtyInput');
  const step = qtyStep(currentCode());
  let v = Number(inp.value) || 0;
  v = Math.max(0, v + dir * step);
  inp.value = v;
  updateEstimate();
}

function quickQty(frac) {
  const code = currentCode();
  if (!code) { toast('请先输入代码'); return; }
  const price = effectivePrice();
  if (!price || price <= 0) { toast('无有效价格'); return; }
  const step = qtyStep(code), lot = minLot(code);
  let qty = 0;
  if (SIDE === 'buy') {
    const cash = STATE ? STATE.summary.available_cash * frac : 0;
    const raw = Math.floor(cash / price / step) * step;
    qty = raw >= lot ? raw : 0;
  } else {
    const pos = posOf(code);
    const avail = pos ? pos.available : 0;
    qty = Math.floor(avail * frac / step) * step;
    if (frac === 1) qty = avail;  // 全仓卖出允许零股
  }
  $('#qtyInput').value = qty;
  updateEstimate();
}

function effectivePrice() {
  if ($('#marketChk').checked) {
    if (DAY_BAR) return DAY_BAR.close;          // 市价按当日收盘
    if (curQuote) return curQuote.price;
  }
  return Number($('#priceInput').value) || (DAY_BAR ? DAY_BAR.close : (curQuote ? curQuote.price : 0));
}

let estTimer = null;
function updateEstimate() {
  clearTimeout(estTimer);
  estTimer = setTimeout(async () => {
    const code = currentCode();
    const qty = Number($('#qtyInput').value) || 0;
    const price = effectivePrice();
    if (!code || qty <= 0 || price <= 0) {
      $('#estAmount').textContent = '--'; $('#estFee').textContent = '--'; return;
    }
    $('#estAmount').textContent = '¥' + fmt(price * qty);
    try {
      const f = await api(`/api/fee_preview?code=${encodeURIComponent(code)}&price=${price}&quantity=${qty}&direction=${SIDE}`);
      $('#estFee').textContent = '¥' + fmt(f.total);
    } catch (e) { $('#estFee').textContent = '--'; }
  }, 250);
}

async function submitOrder() {
  const code = currentCode();
  const qty = Number($('#qtyInput').value) || 0;
  const isMarket = $('#marketChk').checked;
  const price = isMarket ? 0 : (Number($('#priceInput').value) || 0);
  if (!code) { toast('请输入证券代码'); return; }
  if (qty <= 0) { toast('请输入数量'); return; }
  if (!isMarket && price <= 0) { toast('请输入价格'); return; }
  if (!isMarket && DAY_BAR && (price < DAY_BAR.low - 1e-6 || price > DAY_BAR.high + 1e-6)) {
    toast(`价格需在当日区间 ${fmt(DAY_BAR.low, 3)}~${fmt(DAY_BAR.high, 3)} 内`);
    return;
  }

  const btn = $('#submitBtn'); btn.disabled = true;
  try {
    const o = await api('/api/order', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, direction: SIDE, quantity: qty, price, price_type: isMarket ? 'market' : 'limit' }),
    });
    const label = SIDE === 'buy' ? '买入' : '卖出';
    if (o.status === 'filled') toast(`${label}已成交 ${o.filled_qty}股 @ ${fmt(o.filled_price, 3)}`);
    else if (o.status === 'pending') toast(`${label}已挂单: ${o.note || '待撮合'}`);
    else toast(`${label}失败: ${o.note || o.status}`);
    $('#qtyInput').value = '';
    await load();
  } catch (e) { toast('下单失败: ' + e.message); }
  finally { btn.disabled = false; }
}

// ---------------- 代码搜索建议 ----------------
let sugTimer = null;
function onCodeInput() {
  const kw = currentCode();
  clearTimeout(sugTimer);
  if (!kw) { $('#suggest').classList.remove('show'); return; }
  sugTimer = setTimeout(async () => {
    try {
      const list = await api('/api/search?kw=' + encodeURIComponent(kw));
      const box = $('#suggest');
      if (!list.length) { box.classList.remove('show'); return; }
      box.innerHTML = list.map(x => `<div data-pick="${x.code}"><span>${x.code}</span><span class="s-name">${x.name}</span></div>`).join('');
      box.classList.add('show');
    } catch (e) { $('#suggest').classList.remove('show'); }
  }, 250);
}

// ---------------- 视图切换 ----------------
function switchMobileView(view) {
  document.body.className = view === 'trade' ? 'view-trade' : ('view-' + view);
  $$('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  const se = $('#selEntry');
  if (se) se.textContent = view === 'select' ? '◂ 返回交易' : '每日选股 ▸';
  if (view !== 'trade' && view !== 'select') switchTab(view);
  if (view === 'select') loadSelectState(SEL_KIND);
}
function switchTab(tab) {
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  $$('.tab-view').forEach(v => v.classList.toggle('active', v.id === 'tab-' + tab));
}

// ---------------- 登录 / 注册 ----------------
let AUTH_MODE = 'login';
let POLLING = false;

function showAuth() {
  TOKEN = '';
  localStorage.removeItem('paper_token');
  $('#authMask').classList.add('show');
}
function hideAuth() { $('#authMask').classList.remove('show'); }

function setAuthMode(mode) {
  AUTH_MODE = mode;
  $$('.auth-tab').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  $('#authSubmit').textContent = mode === 'login' ? '登录' : '注册';
}

async function doAuth() {
  const username = $('#authUser').value.trim();
  const password = $('#authPass').value;
  if (!username || !password) { toast('请输入用户名与口令'); return; }
  const btn = $('#authSubmit'); btn.disabled = true;
  try {
    const r = await fetch('/api/' + (AUTH_MODE === 'login' ? 'login' : 'register'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || '失败');
    TOKEN = j.token;
    localStorage.setItem('paper_token', TOKEN);
    localStorage.setItem('paper_user', j.username);
    $('#authPass').value = '';
    hideAuth();
    toast((AUTH_MODE === 'login' ? '登录' : '注册') + '成功: ' + j.username);
    startPolling();
    await load();
    loadTradeDate();
    loadStrategies();
  } catch (e) { toast(e.message); }
  finally { btn.disabled = false; }
}

async function logout() {
  try { await api('/api/logout', { method: 'POST' }); } catch (e) {}
  STATE = null;
  $('#acctName').textContent = '—';
  showAuth();
}

// ---------------- 每日选股 / 选基 ----------------
let STRATEGIES = [];
let CUR_STRAT = null;
let SEL_POLL = null;
let INST_POLL = null;
let SEL_KIND = 'stock';
let SEL_VIEW_RUN_ID = null;

function paramStoreKey(sid) {
  const u = localStorage.getItem('paper_user') || '_';
  return `paper_params_${u}_${sid}`;
}

function stratLabel(sid) {
  const s = STRATEGIES.find(x => x.id === sid);
  return s ? s.label : sid;
}

async function loadStrategies() {
  try {
    const r = await api('/api/strategies');
    STRATEGIES = r.strategies || [];
  } catch (e) { STRATEGIES = []; }
  const sel = $('#stratSelect');
  sel.innerHTML = STRATEGIES.map(s => `<option value="${s.id}">${s.label}</option>`).join('');
  if (STRATEGIES.length) {
    const prefer = STRATEGIES.find(s => s.id === 'bull_launch') || STRATEGIES[0];
    sel.value = prefer.id;
    onStrategyChange();
  }
}

function onStrategyChange(skipSaved) {
  CUR_STRAT = STRATEGIES.find(s => s.id === $('#stratSelect').value) || null;
  $('#stratDesc').textContent = CUR_STRAT ? (CUR_STRAT.description || '') : '';
  renderParamForm(skipSaved ? {} : undefined);
}

function savedParams(sid) {
  try { return JSON.parse(localStorage.getItem(paramStoreKey(sid)) || '{}'); }
  catch (e) { return {}; }
}

function renderParamForm(overrideParams) {
  const box = $('#paramForm');
  if (!CUR_STRAT) { box.innerHTML = ''; return; }
  const saved = overrideParams != null ? overrideParams : savedParams(CUR_STRAT.id);
  const rows = (CUR_STRAT.params || []).map(p => {
    let val = (p.key in saved) ? saved[p.key] : p.default;
    if (Array.isArray(val)) val = val.join(',');
    if (val == null) val = '';
    const hint = p.hint ? `<small class="param-hint">${p.hint}</small>` : '';
    let input = '';
    if (p.type === 'bool') {
      const sel = (val === true || val === 'true') ? 'true'
        : (val === false || val === 'false') ? 'false' : '';
      input = `<select data-key="${p.key}" data-type="bool">
        <option value="" ${sel === '' ? 'selected' : ''}>默认</option>
        <option value="true" ${sel === 'true' ? 'selected' : ''}>是</option>
        <option value="false" ${sel === 'false' ? 'selected' : ''}>否</option>
      </select>`;
    } else {
      const type = (p.type === 'list' || p.type === 'text' || p.type === 'ma_groups') ? 'text' : 'number';
      const step = p.step ? ` step="${p.step}"` : (p.type === 'int' ? ' step="1"' : '');
      const ph = p.hint ? ` placeholder="${p.hint}"` : '';
      const esc = String(val).replace(/"/g, '&quot;');
      input = `<input data-key="${p.key}" data-type="${p.type}" type="${type}"${step}${ph} value="${esc}" />`;
    }
    return `<div class="param-item">
      <label title="${p.key}">${p.label}</label>
      ${input}${hint}
    </div>`;
  }).join('');
  box.innerHTML = rows + `<div class="param-actions">
    <button class="p-save" id="pSave">保存参数</button>
    <button id="pReset">恢复默认</button>
  </div>`;
  $('#pSave').onclick = saveParamsFromForm;
  $('#pReset').onclick = () => { localStorage.removeItem(paramStoreKey(CUR_STRAT.id)); renderParamForm(); toast('已恢复系统默认参数'); };
}

function applyParamsToForm(params) {
  if (!CUR_STRAT || !params) return;
  renderParamForm(params);
}

function collectParams() {
  const out = {};
  $$('#paramForm [data-key]').forEach(el => {
    const v = (el.tagName === 'SELECT' ? el.value : el.value.trim());
    if (v !== '') out[el.dataset.key] = v;
  });
  return out;
}

function saveParamsFromForm() {
  if (!CUR_STRAT) return;
  localStorage.setItem(paramStoreKey(CUR_STRAT.id), JSON.stringify(collectParams()));
  toast('参数已保存 (本机)');
}

function switchSelKind(kind) {
  SEL_KIND = kind;
  SEL_VIEW_RUN_ID = null;
  $$('.sel-kind-tab').forEach(b => b.classList.toggle('active', b.dataset.kind === kind));
  loadSelectState(kind);
}

function updateSelStatusMeta(r) {
  if (!r || !r.run_id) {
    if (SEL_VIEW_RUN_ID) $('#selStatus').textContent = '历史记录';
    return;
  }
  const parts = [];
  if (r.trade_date) parts.push(r.trade_date);
  if (r.count != null) parts.push(`${r.count} 只`);
  if (r.elapsed != null) parts.push(`${r.elapsed}s`);
  if (SEL_VIEW_RUN_ID && !r.is_current) parts.push('(历史)');
  else if (r.is_current) parts.push('· 当前');
  $('#selStatus').textContent = parts.join(' · ');
}

function instCellHtml(it, kind, fromSaved) {
  if (kind === 'etf') return '';
  if (fromSaved && ('inst_holder_count' in it || it.inst_holder_source != null)) {
    return fmtInstHolderInline(it, kind);
  }
  return instHolderLoadingHtml();
}

function needsInstPoll(items) {
  return items.some(it => !('inst_holder_count' in it) && it.inst_holder_source == null);
}

function applySelectPayload(r, kind) {
  if (r.strategy_id && STRATEGIES.some(s => s.id === r.strategy_id)) {
    $('#stratSelect').value = r.strategy_id;
    onStrategyChange(true);
  }
  if (r.params && Object.keys(r.params).length) applyParamsToForm(r.params);
  const fromSaved = Boolean(r.run_id);
  renderSelResults(r.items || [], kind, fromSaved);
  updateSelStatusMeta(r);
  if (kind === 'stock' && (r.items || []).length && !SEL_VIEW_RUN_ID && needsInstPoll(r.items)) {
    pollInstHolders(kind);
  }
}

async function loadSelHistory(kind, activeRunId) {
  const list = $('#selHistoryList');
  try {
    const r = await api('/api/select/history?kind=' + kind);
    const runs = r.runs || [];
    if (!runs.length) {
      list.innerHTML = '<li class="empty">暂无记录</li>';
      return;
    }
    list.innerHTML = runs.map(h => {
      const active = (activeRunId != null && h.run_id === activeRunId)
        || (activeRunId == null && SEL_VIEW_RUN_ID == null && h.is_current);
      const cur = h.is_current ? '<span class="h-cur">当前</span>' : '';
      return `<li class="${active ? 'active' : ''}" data-run="${h.run_id}">
        <span class="h-date">${h.trade_date || '—'}</span>
        <span class="h-strat">${stratLabel(h.strategy_id)}</span>
        <span class="h-cnt">${h.count} 只 · ${h.elapsed != null ? h.elapsed + 's' : ''}</span>
        ${cur}
      </li>`;
    }).join('');
  } catch (e) {
    list.innerHTML = '<li class="empty">加载失败</li>';
  }
}

async function loadHistoryRun(runId) {
  SEL_VIEW_RUN_ID = runId;
  try {
    const r = await api('/api/select/history/' + runId);
    const kind = r.kind || SEL_KIND;
    if (kind !== SEL_KIND) {
      SEL_KIND = kind;
      $$('.sel-kind-tab').forEach(b => b.classList.toggle('active', b.dataset.kind === kind));
    }
    applySelectPayload(r, kind);
    await loadSelHistory(kind, runId);
  } catch (e) { toast('读取历史记录失败'); }
}

function viewCurrentRun() {
  SEL_VIEW_RUN_ID = null;
  loadSelectState(SEL_KIND);
}

async function loadSelectState(kind) {
  SEL_KIND = kind;
  $$('.sel-kind-tab').forEach(b => b.classList.toggle('active', b.dataset.kind === kind));
  if (SEL_VIEW_RUN_ID) {
    await loadHistoryRun(SEL_VIEW_RUN_ID);
    return;
  }
  try {
    const r = await api('/api/select/result?kind=' + kind);
    applySelectPayload(r, kind);
    await loadSelHistory(kind, r.run_id);
  } catch (e) { toast('读取结果失败'); }
}

async function runSelect(kind) {
  if (!CUR_STRAT) { toast('请先选择策略'); return; }
  clearTimeout(INST_POLL);
  SEL_VIEW_RUN_ID = null;
  SEL_KIND = kind;
  switchMobileView('select');
  switchSelKind(kind);
  const params = collectParams();
  localStorage.setItem(paramStoreKey(CUR_STRAT.id), JSON.stringify(params));
  $('#runStock').disabled = $('#runEtf').disabled = true;
  $('#selStatus').textContent = (kind === 'etf' ? '选基' : '选股') + '运行中…';
  try {
    await api('/api/select', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, strategy_id: CUR_STRAT.id, params }),
    });
    pollSelect(kind);
  } catch (e) {
    $('#runStock').disabled = $('#runEtf').disabled = false;
    $('#selStatus').textContent = '';
    toast('启动失败: ' + e.message);
  }
}

function pollSelect(kind) {
  clearTimeout(SEL_POLL);
  const t0 = Date.now();
  const tick = async () => {
    let st;
    try { st = await api('/api/select/status?kind=' + kind); }
    catch (e) {
      if (Date.now() - t0 > 300000) {
        $('#runStock').disabled = $('#runEtf').disabled = false;
        $('#selStatus').textContent = '状态查询失败';
        toast('选股状态查询失败，请刷新页面');
        return;
      }
      SEL_POLL = setTimeout(tick, 2000);
      return;
    }
    if (st.running) {
      $('#selStatus').textContent = `${kind === 'etf' ? '选基' : '选股'}运行中… ${Math.round(st.elapsed || 0)}s`;
      SEL_POLL = setTimeout(tick, 1500);
      return;
    }
    $('#runStock').disabled = $('#runEtf').disabled = false;
    if (st.error) { $('#selStatus').textContent = '失败'; toast('选股失败: ' + st.error); return; }
    $('#selStatus').textContent = `完成 · ${st.count || 0} 只 · ${st.elapsed || 0}s`;
    SEL_VIEW_RUN_ID = null;
    await loadSelectState(kind);
  };
  tick();
}

async function loadSelResult(kind) {
  await loadSelectState(kind);
}


function pollInstHolders(kind) {
  clearTimeout(INST_POLL);
  const tick = async () => {
    try {
      const st = await api('/api/select/inst-holders/status?kind=' + kind);
      if (st.running) {
        INST_POLL = setTimeout(tick, 1200);
        return;
      }
      const r = await api('/api/select/inst-holders?kind=' + kind);
      applyInstHolders(r.items || {}, kind);
    } catch (e) { /* 静默, 不阻塞交易 */ }
  };
  tick();
}

function renderSelResults(items, kind, fromSaved) {
  const body = $('#selBody');
  $('#selAll').checked = false;
  if (!items.length) {
    body.innerHTML = '<tr class="empty"><td colspan="7">无符合条件的标的</td></tr>';
    $('#selMeta').textContent = '';
    return;
  }
  $('#selMeta').textContent = `${kind === 'etf' ? 'ETF' : '股票'} 共 ${items.length} 只 · 挂单于次日按「最低价<挂单价」成交`;
  body.innerHTML = items.map(it => {
    const close = it.close != null ? Number(it.close) : 0;
    const lot = minLot(it.code);
    const tier = it.tier ? `<small class="tier-${it.tier}">${it.tier}级</small>` : '';
    const inst = instCellHtml(it, kind, fromSaved);
    return `<tr data-code="${it.code}">
      <td class="op"><input type="checkbox" class="pick-chk" /></td>
      <td><div class="cell-2"><b>${it.name || '-'}</b><small>${it.code}${inst}</small></div></td>
      <td class="r"><div class="cell-2"><span>${it.score != null ? fmt(it.score, 1) : '-'}</span>${tier}</div></td>
      <td class="r">${close ? fmt(close, 3) : '-'}</td>
      <td class="r"><input class="bid-input" type="number" step="0.001" value="${close || ''}" /></td>
      <td class="r"><input class="qty-input" type="number" step="${lot}" value="${lot}" /></td>
      <td><small class="flat">${it.reason || ''}</small></td>
    </tr>`;
  }).join('');
}

async function placePicks() {
  const kind = SEL_KIND;
  const rows = $$('#selBody tr[data-code]');
  const items = [];
  rows.forEach(tr => {
    if (!tr.querySelector('.pick-chk').checked) return;
    const code = tr.dataset.code;
    const price = Number(tr.querySelector('.bid-input').value) || 0;
    const quantity = Number(tr.querySelector('.qty-input').value) || 0;
    if (price > 0 && quantity > 0) items.push({ code, price, quantity });
  });
  if (!items.length) { toast('请勾选并填写挂单价/数量'); return; }
  $('#placePicks').disabled = true;
  try {
    const r = await api('/api/picks/order', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, items }),
    });
    const eff = r.effective_date || '次日';
    const okN = (r.orders || []).filter(o => o.status !== 'failed').length;
    toast(`已挂单 ${okN} 笔, ${eff} 生效`);
    if (r.snapshot) render(r.snapshot);
    switchMobileView('orders');
  } catch (e) { toast('挂单失败: ' + e.message); }
  finally { $('#placePicks').disabled = false; }
}

// ---------------- 轮询 ----------------
async function load() {
  if (!TOKEN) return;
  try { render(await api('/api/state')); } catch (e) { /* 静默 */ }
}

function startPolling() {
  if (POLLING) return;
  POLLING = true;
  setInterval(load, 4000);
}

// ---------------- 事件绑定 ----------------
function bind() {
  $$('.seg-btn').forEach(b => b.onclick = () => setSide(b.dataset.side));
  $('#codeInput').addEventListener('input', onCodeInput);
  $('#codeInput').addEventListener('change', () => { $('#suggest').classList.remove('show'); refreshCode(currentCode()); });
  $('#codeInput').addEventListener('blur', () => setTimeout(() => $('#suggest').classList.remove('show'), 200));

  $('#suggest').addEventListener('click', (e) => {
    const d = e.target.closest('[data-pick]'); if (!d) return;
    $('#codeInput').value = d.dataset.pick;
    $('#suggest').classList.remove('show');
    refreshCode(d.dataset.pick);
  });

  // 当日区间快捷选价
  $('#rangeLine').addEventListener('click', (e) => {
    const px = e.target.dataset.px; if (!px || !DAY_BAR) return;
    $('#marketChk').checked = false; $('#priceInput').disabled = false;
    $('#priceInput').value = DAY_BAR[px];
    updateEstimate();
  });

  // 交易日切换
  $('#prevDay').onclick = () => stepDay('prev');
  $('#nextDay').onclick = () => stepDay('next');
  $('#calBtn').onclick = openCalendar;
  $('#syncBtn').onclick = runDataSync;
  $('#calMask').onclick = closeCalendar;
  $('#calClose').onclick = closeCalendar;
  $('#calPrevM').onclick = () => calShiftMonth(-1);
  $('#calNextM').onclick = () => calShiftMonth(1);
  $('#calToLatest').onclick = () => { if (LATEST_DAY) { closeCalendar(); setTradeDate(LATEST_DAY); } };
  $('#calGrid').addEventListener('click', (e) => {
    const d = e.target.closest('[data-day]'); if (!d) return;
    closeCalendar();
    setTradeDate(d.dataset.day);
  });

  document.querySelector('.trade-panel').addEventListener('click', (e) => {
    const act = e.target.dataset.act;
    if (act === 'price-inc') stepPrice(1);
    else if (act === 'price-dec') stepPrice(-1);
    else if (act === 'qty-inc') stepQty(1);
    else if (act === 'qty-dec') stepQty(-1);
  });
  $('#quickQty').addEventListener('click', (e) => { if (e.target.dataset.frac) quickQty(Number(e.target.dataset.frac)); });
  $('#qtyInput').addEventListener('input', updateEstimate);
  $('#priceInput').addEventListener('input', updateEstimate);
  $('#marketChk').addEventListener('change', () => {
    $('#priceInput').disabled = $('#marketChk').checked;
    updateEstimate();
  });
  $('#submitBtn').onclick = submitOrder;

  // 列表交互
  $('#posBody').addEventListener('click', (e) => {
    const sellBtn = e.target.closest('[data-sell]');
    const row = e.target.closest('tr[data-code]');
    const code = sellBtn ? sellBtn.dataset.sell : (row ? row.dataset.code : null);
    if (code) {
      $('#codeInput').value = code;
      setSide('sell');
      refreshCode(code);
      if (window.matchMedia('(max-width: 820px)').matches) switchMobileView('trade');
    }
  });
  $('#orderBody').addEventListener('click', async (e) => {
    const c = e.target.closest('[data-cancel]'); if (!c) return;
    try { await api('/api/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_id: c.dataset.cancel }) }); toast('已撤单'); await load(); }
    catch (err) { toast('撤单失败'); }
  });
  $('#tradeBody').addEventListener('click', async (e) => {
    const d = e.target.closest('[data-deltrade]'); if (!d) return;
    if (!await uiConfirm('确定删除这条成交记录?\n(仅删记录, 不回滚资金/持仓)', '删除成交')) return;
    try { await api('/api/trade/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trade_id: d.dataset.deltrade }) }); toast('已删除'); await load(); }
    catch (err) { toast('删除失败: ' + err.message); }
  });

  // 登录 / 注册
  $$('.auth-tab').forEach(b => b.onclick = () => setAuthMode(b.dataset.mode));
  $('#authSubmit').onclick = doAuth;
  $('#authPass').addEventListener('keydown', (e) => { if (e.key === 'Enter') doAuth(); });
  $('#logoutBtn').onclick = logout;

  // 调整模拟资金
  $('#capitalBtn').onclick = async () => {
    const cur = STATE ? STATE.summary.cash : 0;
    const v = await uiPrompt('设置可用资金 (元, 不能为负)', cur, '改资金');
    if (v === null) return;
    const cash = Number(v);
    if (isNaN(cash) || cash < 0) { toast('金额无效'); return; }
    try { await api('/api/capital', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cash }) }); toast('资金已更新'); await load(); }
    catch (err) { toast('更新失败: ' + err.message); }
  };

  $('#listTabs').addEventListener('click', (e) => { if (e.target.dataset.tab) switchTab(e.target.dataset.tab); });
  $('#bottomNav').addEventListener('click', (e) => { const b = e.target.closest('[data-view]'); if (b) switchMobileView(b.dataset.view); });

  // 每日选股 / 选基
  $('#selEntry').onclick = () => {
    const on = document.body.classList.contains('view-select');
    switchMobileView(on ? 'trade' : 'select');
    $('#selEntry').textContent = on ? '每日选股 ▸' : '◂ 返回交易';
  };
  $('#stratSelect').addEventListener('change', () => onStrategyChange());
  $$('.sel-kind-tab').forEach(b => b.onclick = () => switchSelKind(b.dataset.kind));
  $('#selHistoryList').addEventListener('click', (e) => {
    const li = e.target.closest('[data-run]');
    if (!li) return;
    loadHistoryRun(Number(li.dataset.run));
  });
  $('#selHistoryCurrent').onclick = viewCurrentRun;
  $('#runStock').onclick = () => runSelect('stock');
  $('#runEtf').onclick = () => runSelect('etf');
  $('#selAll').addEventListener('change', (e) => {
    $$('#selBody .pick-chk').forEach(c => { c.checked = e.target.checked; });
  });
  $('#placePicks').onclick = placePicks;

  $('#resetBtn').onclick = async () => {
    if (!await uiConfirm('确定重置模拟账户?\n所有持仓/委托/成交将清空。', '重置账户')) return;
    const cap = await uiPrompt('初始资金 (元)', STATE ? STATE.summary.initial_capital : 1000000, '重置账户');
    if (cap === null) return;
    await api('/api/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ initial_capital: Number(cap) || null }) });
    toast('账户已重置'); await load();
  };
}

// ---------------- 启动 ----------------
async function boot() {
  document.body.className = 'view-trade';
  initDialog();
  try { bind(); } catch (e) { console.error('bind failed', e); toast('界面初始化异常，请刷新'); }
  setSide('buy');
  setAuthMode('login');
  if (TOKEN) {
    try {
      await api('/api/me');           // 校验会话
      hideAuth();
      startPolling();
      await load();
      loadTradeDate();
      loadStrategies();
      return;
    } catch (e) { /* 会话失效 → 显示登录 */ }
  }
  showAuth();
}
boot();
