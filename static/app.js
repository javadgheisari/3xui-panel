const form = document.querySelector('#lookup-form');
const input = document.querySelector('#client-name');
const submitButton = document.querySelector('#submit-button');
const emptyState = document.querySelector('#empty-state');
const loadingState = document.querySelector('#loading-state');
const errorState = document.querySelector('#error-state');
const resultState = document.querySelector('#result-state');
const retryButton = document.querySelector('#retry-button');
const refreshButton = document.querySelector('#refresh-button');
let activeName = '';
const persianNumber = new Intl.NumberFormat('fa-IR');

function showState(state) {
  emptyState.hidden = state !== 'empty';
  loadingState.hidden = state !== 'loading';
  errorState.hidden = state !== 'error';
  resultState.hidden = state !== 'result';
  submitButton.disabled = state === 'loading';
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes === 0) return '۰ بایت';
  const units = ['بایت', 'کیلوبایت', 'مگابایت', 'گیگابایت', 'ترابایت', 'پتابایت'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** index);
  const digits = value >= 100 || index === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${new Intl.NumberFormat('fa-IR', { maximumFractionDigits: digits }).format(value)} ${units[index]}`;
}

function formatExpiry(expiryTime) {
  if (expiryTime === 0) return 'بدون تاریخ انقضا';
  if (expiryTime < 0) return 'پس از اولین استفاده فعال می‌شود';
  const timestamp = expiryTime < 10_000_000_000 ? expiryTime * 1000 : expiryTime;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('fa-IR-u-ca-persian', { day: 'numeric', month: 'long', year: 'numeric' }).format(date);
}

function statusFor(data) {
  if (!data.enable) return { label: 'غیرفعال', active: false };
  const expiry = data.expiryTime < 10_000_000_000 ? data.expiryTime * 1000 : data.expiryTime;
  if (expiry > 0 && expiry <= Date.now()) return { label: 'منقضی‌شده', active: false };
  if (data.remainingTraffic !== null && data.remainingTraffic <= 0) return { label: 'حجم تمام شده', active: false };
  return { label: 'فعال', active: true };
}

function render(data) {
  const unlimited = data.totalGB === 0;
  const percent = unlimited ? 0 : Math.min(100, Math.max(0, (data.usedTraffic / data.totalGB) * 100));
  const circumference = 2 * Math.PI * 73;
  document.querySelector('#ring-value').style.strokeDashoffset = `${circumference * (1 - percent / 100)}`;
  document.querySelector('#usage-percent').textContent = unlimited ? '∞' : `${persianNumber.format(Math.round(percent))}٪`;
  document.querySelector('#progress-bar').style.width = `${percent}%`;
  document.querySelector('#client-title').textContent = data.name;
  document.querySelector('#remaining-value').textContent = unlimited ? 'نامحدود' : formatBytes(data.remainingTraffic);
  document.querySelector('#usage-summary').textContent = unlimited
    ? `${formatBytes(data.usedTraffic)} مصرف‌شده · بدون محدودیت حجم`
    : `${formatBytes(data.usedTraffic)} مصرف‌شده از ${formatBytes(data.totalGB)}`;
  document.querySelector('#used-value').textContent = formatBytes(data.usedTraffic);
  document.querySelector('#total-value').textContent = unlimited ? 'نامحدود' : formatBytes(data.totalGB);
  document.querySelector('#expiry-value').textContent = formatExpiry(data.expiryTime);
  document.querySelector('#inbounds-value').textContent = data.inboundIds.length
    ? data.inboundIds.map((id) => persianNumber.format(id)).join('، ')
    : 'هیچ‌کدام';
  document.querySelector('#last-updated').textContent = `به‌روزرسانی در ${new Intl.DateTimeFormat('fa-IR', { hour: 'numeric', minute: '2-digit' }).format(new Date(data.fetchedAt))}`;

  const status = statusFor(data);
  const badge = document.querySelector('#plan-status');
  badge.innerHTML = '<span></span>' + status.label;
  badge.classList.toggle('inactive', !status.active);
  showState('result');
}

function renderError(error) {
  const title = error.code === 'not_found'
    ? 'کاربری با این نام پیدا نشد.'
    : error.code === 'setup_required'
      ? 'تنظیمات اتصال کامل نیست.'
      : 'دریافت اطلاعات انجام نشد.';
  document.querySelector('#error-title').textContent = title;
  document.querySelector('#error-message').textContent = error.message || 'کمی بعد دوباره تلاش کنید.';
  showState('error');
}

async function lookup(name) {
  activeName = name.trim();
  if (!activeName) {
    input.focus();
    return;
  }
  showState('loading');
  try {
    const response = await fetch(`/api/usage?name=${encodeURIComponent(activeName)}`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    const payload = await response.json();
    if (!response.ok) throw payload.error || { message: 'دریافت اطلاعات انجام نشد.' };
    render(payload.data);
  } catch (error) {
    renderError(error);
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  lookup(input.value);
});

retryButton.addEventListener('click', () => {
  showState('empty');
  input.focus();
  input.select();
});

refreshButton.addEventListener('click', () => lookup(activeName));
