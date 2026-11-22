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
let currentData = null;
let currentError = null;
let language = localStorage.getItem('language') || 'en';
if (!['en', 'fa'].includes(language)) language = 'en';
const translations = {
  en: {
    'document.title': 'Internet usage',
    'meta[name="description"]': 'View your internet usage and remaining data',
    '.brand@aria-label': 'Internet usage home',
    '.secure-pill': '<span></span> Live user usage',
    '.eyebrow': '<span>01</span> Service usage overview',
    '#page-title': 'See your usage.<br /><em>Know what remains.</em>',
    '.hero-copy': 'Enter your username to see usage, remaining data, and your service expiry date.',
    '.lookup label': 'Username',
    '#client-name@placeholder': 'e.g. ali',
    '#submit-button span': 'Check usage',
    '#form-hint': 'Your username is used only to retrieve usage information.',
    '.preview-label': 'Live usage preview',
    '.error-kicker': 'Search failed',
    '#retry-button': 'Try again',
    '.result-kicker': 'User',
    '.usage-ring@aria-label': 'Internet usage',
    '.ring-copy small': 'Used',
    '.usage-primary > p': 'Remaining data',
    '.metric:nth-child(1) span': 'Data used',
    '.metric:nth-child(2) span': 'Total data',
    '.metric:nth-child(3) span': 'Expiry date',
    '.inbound-detail': 'Connected inbounds<span id="inbounds-value">—</span>',
    '#refresh-button': '<svg viewBox="0 0 24 24"><path d="M20 6v5h-5M4 18v-5h5M18.5 9A7 7 0 0 0 6.3 6.3L4 9m16 6-2.3 2.7A7 7 0 0 1 5.5 15"/></svg> Refresh',
    '.page-footer p:first-child': 'Powered by <a href="https://github.com/MHSanaei/3x-ui" rel="noreferrer">3x-ui</a>',
    '.page-footer p:last-child': '<span></span> Usage data is retrieved directly from the panel',
  },
};
const persianStatic = {};
for (const key of Object.keys(translations.en)) {
  const [selector, attribute] = key.split('@');
  const element = selector === 'document.title' ? document.querySelector('title') : document.querySelector(selector);
  persianStatic[key] = attribute ? element.getAttribute(attribute) : element.innerHTML;
}
const t = (fa, en) => language === 'fa' ? fa : en;
const number = () => new Intl.NumberFormat(language === 'fa' ? 'fa-IR' : 'en-US');

function setLanguage(next) {
  language = next;
  localStorage.setItem('language', language);
  document.documentElement.lang = language;
  document.documentElement.dir = language === 'fa' ? 'rtl' : 'ltr';
  for (const [key, english] of Object.entries(translations.en)) {
    const [selector, attribute] = key.split('@');
    const element = selector === 'document.title' ? document.querySelector('title') : document.querySelector(selector);
    const value = language === 'en' ? english : persianStatic[key];
    if (attribute) element.setAttribute(attribute, value);
    else element.innerHTML = value;
  }
  const switcher = document.querySelector('#language-switch');
  switcher.textContent = language === 'fa' ? 'English' : 'فارسی';
  switcher.setAttribute('aria-label', language === 'fa' ? 'Switch to English' : 'تغییر زبان به فارسی');
  if (currentData) render(currentData);
  else if (currentError) renderError(currentError);
}

function showState(state) {
  emptyState.hidden = state !== 'empty';
  loadingState.hidden = state !== 'loading';
  errorState.hidden = state !== 'error';
  resultState.hidden = state !== 'result';
  submitButton.disabled = state === 'loading';
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes === 0) return t('۰ بایت', '0 bytes');
  const units = language === 'fa' ? ['بایت', 'کیلوبایت', 'مگابایت', 'گیگابایت', 'ترابایت', 'پتابایت'] : ['bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** index);
  const digits = value >= 100 || index === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${new Intl.NumberFormat(language === 'fa' ? 'fa-IR' : 'en-US', { maximumFractionDigits: digits }).format(value)} ${units[index]}`;
}

function formatExpiry(expiryTime) {
  if (expiryTime === 0) return t('بدون تاریخ انقضا', 'No expiry date');
  if (expiryTime < 0) return t('پس از اولین استفاده فعال می‌شود', 'Activates after first use');
  const timestamp = expiryTime < 10_000_000_000 ? expiryTime * 1000 : expiryTime;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(language === 'fa' ? 'fa-IR-u-ca-persian' : 'en-US', { day: 'numeric', month: 'long', year: 'numeric' }).format(date);
}

function statusFor(data) {
  if (!data.enable) return { label: t('غیرفعال', 'Inactive'), active: false };
  const expiry = data.expiryTime < 10_000_000_000 ? data.expiryTime * 1000 : data.expiryTime;
  if (expiry > 0 && expiry <= Date.now()) return { label: t('منقضی‌شده', 'Expired'), active: false };
  if (data.remainingTraffic !== null && data.remainingTraffic <= 0) return { label: t('حجم تمام شده', 'Data exhausted'), active: false };
  return { label: t('فعال', 'Active'), active: true };
}

function render(data) {
  currentData = data;
  currentError = null;
  const unlimited = data.totalGB === 0;
  const percent = unlimited ? 0 : Math.min(100, Math.max(0, (data.usedTraffic / data.totalGB) * 100));
  const circumference = 2 * Math.PI * 73;
  document.querySelector('#ring-value').style.strokeDashoffset = `${circumference * (1 - percent / 100)}`;
  document.querySelector('#usage-percent').textContent = unlimited ? '∞' : `${number().format(Math.round(percent))}${t('٪', '%')}`;
  document.querySelector('#progress-bar').style.width = `${percent}%`;
  document.querySelector('#client-title').textContent = data.name;
  document.querySelector('#remaining-value').textContent = unlimited ? t('نامحدود', 'Unlimited') : formatBytes(data.remainingTraffic);
  document.querySelector('#usage-summary').textContent = unlimited
    ? t(`${formatBytes(data.usedTraffic)} مصرف‌شده · بدون محدودیت حجم`, `${formatBytes(data.usedTraffic)} used · No data limit`)
    : t(`${formatBytes(data.usedTraffic)} مصرف‌شده از ${formatBytes(data.totalGB)}`, `${formatBytes(data.usedTraffic)} used of ${formatBytes(data.totalGB)}`);
  document.querySelector('#used-value').textContent = formatBytes(data.usedTraffic);
  document.querySelector('#total-value').textContent = unlimited ? t('نامحدود', 'Unlimited') : formatBytes(data.totalGB);
  document.querySelector('#expiry-value').textContent = formatExpiry(data.expiryTime);
  document.querySelector('#inbounds-value').textContent = data.inboundIds.length
    ? data.inboundIds.map((id) => number().format(id)).join(t('، ', ', '))
    : t('هیچ‌کدام', 'None');
  document.querySelector('#last-updated').textContent = `${t('به‌روزرسانی در ', 'Updated at ')}${new Intl.DateTimeFormat(language === 'fa' ? 'fa-IR' : 'en-US', { hour: 'numeric', minute: '2-digit' }).format(new Date(data.fetchedAt))}`;

  const status = statusFor(data);
  const badge = document.querySelector('#plan-status');
  badge.innerHTML = '<span></span>' + status.label;
  badge.classList.toggle('inactive', !status.active);
  showState('result');
}

function renderError(error) {
  currentError = error;
  currentData = null;
  const title = error.code === 'not_found'
    ? t('کاربری با این نام پیدا نشد.', 'No user found with that name.')
    : error.code === 'setup_required'
      ? t('تنظیمات اتصال کامل نیست.', 'Connection setup is incomplete.')
      : t('دریافت اطلاعات انجام نشد.', 'Could not retrieve usage information.');
  document.querySelector('#error-title').textContent = title;
  document.querySelector('#error-message').textContent = language === 'en'
    ? (error.code === 'not_found' ? 'Check the username and try again.' : 'Please try again later.')
    : error.message || 'کمی بعد دوباره تلاش کنید.';
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
    if (!response.ok) throw payload.error || { message: t('دریافت اطلاعات انجام نشد.', 'Could not retrieve usage information.') };
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
document.querySelector('#language-switch').addEventListener('click', () => setLanguage(language === 'fa' ? 'en' : 'fa'));
setLanguage(language);
