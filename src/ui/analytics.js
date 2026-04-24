// Google Analytics 4 — Arth
// Replace G-XXXXXXXXXX with your actual Measurement ID
const GA_ID = 'G-7GNLXM4S8B';

// Load gtag.js
const s = document.createElement('script');
s.async = true;
s.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`;
document.head.appendChild(s);

window.dataLayer = window.dataLayer || [];
function gtag(){ dataLayer.push(arguments); }
gtag('js', new Date());
gtag('config', GA_ID);

// Custom event helper
function trackEvent(name, params) {
  gtag('event', name, params || {});
}
