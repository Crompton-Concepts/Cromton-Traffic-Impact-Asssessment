/**
 * UI Utility Helpers
 * Safe DOM manipulation, formatting, and event debouncing utilities.
 */

/** Safely get an element by ID with typed return. */
export function getEl<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

/** Safely set textContent on an element by ID. */
export function setText(id: string, text: string): void {
  const el = getEl(id);
  if (el) el.textContent = text;
}

/** Safely set innerHTML — prefer textContent for untrusted data. */
export function setHtml(id: string, html: string): void {
  const el = getEl(id);
  if (el) el.innerHTML = html;
}

/** Toggle a CSS class on an element by ID. */
export function toggleClass(id: string, className: string, force?: boolean): boolean {
  const el = getEl(id);
  if (!el) return false;
  return el.classList.toggle(className, force);
}

/** Debounce a function by a given delay in milliseconds. */
export function debounce<T extends (...args: unknown[]) => void>(
  fn: T,
  delayMs: number
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

/** Throttle a function to execute at most once per interval. */
export function throttle<T extends (...args: unknown[]) => void>(
  fn: T,
  intervalMs: number
): (...args: Parameters<T>) => void {
  let last = 0;
  return (...args: Parameters<T>) => {
    const now = Date.now();
    if (now - last >= intervalMs) {
      last = now;
      fn(...args);
    }
  };
}

/** Format a number with commas and optional decimal places. */
export function fmtNumber(value: unknown, decimals = 0, fallback = '-'): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  if (decimals <= 0) return Math.round(num).toLocaleString();
  return num.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** Format a percentage value (0-100) with a % sign. */
export function fmtPercent(value: unknown, fallback = '-'): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return `${num.toFixed(1)}%`;
}

/** Format a date as dd/mm/yyyy (AU format). */
export function fmtAuDate(value: unknown, fallback?: string): string {
  const text = String(value || '').trim();
  if (!text) {
    return fallback || new Date().toLocaleDateString('en-AU');
  }
  const d = new Date(text);
  if (Number.isNaN(d.getTime())) {
    return fallback || new Date().toLocaleDateString('en-AU');
  }
  return d.toLocaleDateString('en-AU');
}

/** Parse a float safely, returning null if invalid. */
export function parseFloatOrNull(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const text = String(value).replace(/,/g, '').trim();
  if (!text) return null;
  const match = text.match(/[-+]?\d+(?:\.\d+)?/);
  if (!match) return null;
  const parsed = parseFloat(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Parse a boolean from various string representations. */
export function parseBool(value: unknown): boolean {
  if (typeof value === 'boolean') return value;
  return ['1', 'true', 'yes', 'y'].includes(String(value).trim().toLowerCase());
}

/** Escape HTML entities to prevent XSS. */
export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/** Copy text to clipboard with fallback for older browsers. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through */
  }
  // Fallback
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
    return true;
  } catch {
    return false;
  } finally {
    document.body.removeChild(ta);
  }
}

/** Detect if the device is likely a touch/mobile device. */
export function isTouchDevice(): boolean {
  return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
}

/** Detect if the viewport is narrow (mobile breakpoint). */
export function isMobileViewport(): boolean {
  return window.innerWidth < 768;
}
