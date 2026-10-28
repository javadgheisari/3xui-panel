const form = document.querySelector('#lookup-form');
const input = document.querySelector('#config-id');
const submitButton = document.querySelector('#submit-button');
const emptyState = document.querySelector('#empty-state');
const loadingState = document.querySelector('#loading-state');
const errorState = document.querySelector('#error-state');
const resultState = document.querySelector('#result-state');
const retryButton = document.querySelector('#retry-button');
const refreshButton = document.querySelector('#refresh-button');
const demoButton = document.querySelector('#demo-button');
let activeId = '';

function showState(state) {
  emptyState.hidden = state !== 'empty';
  loadingState.hidden = state !== 'loading';
  errorState.hidden = state !== 'error';
  resultState.hidden = state !== 'result';
  submitButton.disabled = state === 'loading';
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes === 0) return '0 GB';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** index);
  const digits = value >= 100 || index === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits).replace(/\.0+$|(?<=\.[0-9])0$/, '')} ${units[index]}`;
}

function formatDate(timestamp) {
  if (!timestamp) return 'No expiry';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' }).format(date);
}

function statusFor(data) {
  if (!data.enabled) return { label: 'Disabled', active: false };
  if (data.expires_at && data.expires_at <= Date.now()) return { label: 'Expired', active: false };
  if (!data.unlimited && data.remaining_bytes <= 0) return { label: 'Depleted', active: false };
  if (data.online === true) return { label: 'Online', active: true };
  return { label: 'Active', active: true };
}

function render(data) {
  const percent = data.unlimited || data.total_bytes <= 0
    ? 0
    : Math.min(100, Math.max(0, (data.used_bytes / data.total_bytes) * 100));
  const circumference = 2 * Math.PI * 73;
  document.querySelector('#ring-value').style.strokeDashoffset = `${circumference * (1 - percent / 100)}`;
  document.querySelector('#usage-percent').textContent = data.unlimited ? '∞' : `${Math.round(percent)}%`;
  document.querySelector('#progress-bar').style.width = `${data.unlimited ? 100 : percent}%`;
  document.querySelector('#plan-title').textContent = data.title || 'Your plan';
  document.querySelector('#remaining-value').textContent = data.unlimited ? 'Unlimited' : formatBytes(data.remaining_bytes);
  document.querySelector('#usage-summary').textContent = data.unlimited
    ? `${formatBytes(data.used_bytes)} used · no data limit`
    : `${formatBytes(data.used_bytes)} used of ${formatBytes(data.total_bytes)}`;
  document.querySelector('#download-value').textContent = formatBytes(data.download_bytes);
  document.querySelector('#upload-value').textContent = formatBytes(data.upload_bytes);
  document.querySelector('#expiry-value').textContent = formatDate(data.expires_at);
  document.querySelector('#last-updated').textContent = 'Updated just now';

  const status = statusFor(data);
  const badge = document.querySelector('#plan-status');
  badge.innerHTML = '<span></span>' + status.label;
  badge.classList.toggle('inactive', !status.active);
  showState('result');
}

function renderError(error) {
  const title = error.code === 'not_found'
    ? 'We couldn’t find that configuration.'
    : error.code === 'setup_required'
      ? 'The portal needs to be connected.'
      : 'The lookup didn’t complete.';
  document.querySelector('#error-title').textContent = title;
  document.querySelector('#error-message').textContent = error.message || 'Please try again shortly.';
  demoButton.hidden = error.code !== 'setup_required';
  showState('error');
}

async function lookup(identifier) {
  activeId = identifier.trim();
  if (!activeId) {
    input.focus();
    return;
  }
  showState('loading');
  try {
    const response = await fetch(`/api/usage?id=${encodeURIComponent(activeId)}`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    const payload = await response.json();
    if (!response.ok) throw payload.error || { message: 'The lookup failed.' };
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

refreshButton.addEventListener('click', () => lookup(activeId));

demoButton.addEventListener('click', () => {
  input.value = 'demo-7b6e-4fd2';
  document.querySelector('#error-message').textContent = 'Set XUI_DEMO_MODE=1 on the server, then try the demo ID.';
  input.focus();
});

