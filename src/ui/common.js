/**
 * FinBestie - Common JavaScript
 * Shared utilities and authentication logic
 */

const $ = id => document.getElementById(id);

const safeJson = r => {
  if (r.ok) return r.json();
  if (r.status === 401) {
    // If we're not on the landing page, redirect to it
    if (window.location.pathname !== '/') window.location.href = '/';
    return Promise.reject(new Error('Unauthenticated'));
  }
  return Promise.reject(new Error(`Server error: ${r.status}`));
};

// Formatting utilities
const INR = v => '₹' + Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const sign = v => v >= 0 ? '+' : '';

// Authentication logic
async function handleGoogleCredential(response) {
  try {
    const res = await fetch('/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential: response.credential })
    });
    const data = await res.json();
    if (data.status === 'ok') {
      window.location.href = '/app';
    } else {
      console.error('Login failed:', data.error);
    }
  } catch (e) {
    console.error('Auth error:', e);
  }
}

async function logout() {
  try {
    await fetch('/auth/logout', { method: 'POST' });
    window.location.href = '/';
  } catch (e) {
    console.error('Logout failed:', e);
    window.location.href = '/';
  }
}

function showUser(user) {
  const signinBtn = $('signin-btn');
  const userBtn = $('user-btn');
  const userAvatar = $('user-avatar');
  const userName = $('user-name');
  const userEmail = $('user-email');

  if (signinBtn) signinBtn.classList.add('hidden');
  if (userBtn) {
    userBtn.classList.remove('hidden');
    userBtn.classList.add('flex');
  }
  if (userAvatar) userAvatar.src = user.picture || '';
  if (userName) userName.textContent = user.name?.split(' ')[0] || '';
  if (userEmail) userEmail.textContent = user.email || '';
}

function renderSignIn() {
  const signinBtn = $('signin-btn');
  const userBtn = $('user-btn');
  if (signinBtn) signinBtn.classList.remove('hidden');
  if (userBtn) userBtn.classList.add('hidden');
}

// Check session on load
async function checkSession() {
  try {
    const data = await fetch('/auth/me').then(safeJson);
    if (data.status === 'ok') {
      showUser(data.user);
      return data.user;
    } else {
      renderSignIn();
    }
  } catch (e) {
    renderSignIn();
  }
  return null;
}
