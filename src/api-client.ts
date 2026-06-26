/**
 * TIA API Client
 * Typed fetch wrappers for the Python report service and Cloud Functions.
 */

import type {
  DraftCreateRequest,
  DraftCreateResponse,
  HealthCheckResponse,
  VerifyFormulasRequest,
  VerifyFormulasResponse,
  AddressCandidate,
  RateLimitMeta,
  ReportMode,
} from './types';

let baseUrl = '';
let lastCheckReason = '';

/** Configure the base URL for the report service. */
export function setBaseUrl(url: string): void {
  baseUrl = url.replace(/\/$/, '');
}

/** Get the currently configured base URL. */
export function getBaseUrl(): string {
  return baseUrl;
}

/** Get the reason string from the last health-check failure. */
export function getLastCheckReason(): string {
  return lastCheckReason;
}

/** Check if the report service is reachable and healthy. */
export async function isServiceAvailable(timeoutMs = 1800): Promise<boolean> {
  lastCheckReason = '';
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;

  try {
    const response = await fetch(`${baseUrl}/health`, {
      method: 'GET',
      cache: 'no-store',
      signal: controller ? controller.signal : undefined,
    });
    if (timer) clearTimeout(timer);

    if (!response.ok) {
      lastCheckReason = `Report service returned HTTP ${response.status} for /health.`;
      return false;
    }
    const health = (await response.json()) as HealthCheckResponse;
    const healthy = String(health?.status || '').toLowerCase() === 'ok';
    if (!healthy) {
      lastCheckReason = 'Report service did not return status=ok.';
    }
    return healthy;
  } catch (err) {
    if (timer) clearTimeout(timer);
    const msg = String((err as Error)?.message || '').toLowerCase();
    const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
    const isLoopback = /^https?:\/\/(localhost|127\.0\.0\.1)/i.test(baseUrl);
    const likelyPna = isHttps && isLoopback &&
      (msg.includes('failed to fetch') || msg.includes('networkerror') || msg.includes('load failed'));
    lastCheckReason = likelyPna
      ? 'Browser blocked access to local service (private-network policy). Restart the Python service and try again.'
      : `Report service is not reachable at ${baseUrl}.`;
    return false;
  }
}

/** Create a new report draft and return the editor URL. */
export async function createDraft(
  title: string,
  payload: Record<string, unknown>
): Promise<string> {
  const response = await fetch(`${baseUrl}/report/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, payload } satisfies DraftCreateRequest),
  });

  if (!response.ok) {
    throw new Error(`Draft creation failed: HTTP ${response.status}`);
  }
  const data = (await response.json()) as DraftCreateResponse;
  const editorPath = String(data?.editor_url || '');
  if (!editorPath) {
    throw new Error('Editor URL was not returned by the service.');
  }
  return new URL(editorPath, baseUrl).toString();
}

/** Open the editable report in a new tab. */
export async function openEditableReport(
  mode: ReportMode,
  title: string,
  payload: Record<string, unknown>
): Promise<void> {
  const available = await isServiceAvailable();
  if (!available) {
    throw new Error(lastCheckReason || 'Report service is offline.');
  }
  const url = await createDraft(title, { ...payload, report_variant: mode });
  window.open(url, '_blank', 'noopener');
}

/** Submit formula verification failures to the backend for analysis. */
export async function verifyFormulas(
  failures: VerifyFormulasRequest['failures']
): Promise<{ response: VerifyFormulasResponse; rateMeta: RateLimitMeta }> {
  const response = await fetch(`${baseUrl}/verify-formulas`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ failures } satisfies VerifyFormulasRequest),
  });

  const rateMeta: RateLimitMeta = {
    limit: parseInt(response.headers.get('X-RateLimit-Limit') || '0', 10),
    remaining: parseInt(response.headers.get('X-RateLimit-Remaining') || '0', 10),
    reset_epoch: parseInt(response.headers.get('X-RateLimit-Reset') || '0', 10),
  };

  if (response.status === 429) {
    const retryAfter = parseInt(response.headers.get('Retry-After') || '60', 10);
    throw new Error(`Rate limited. Retry after ${retryAfter}s.`);
  }

  if (!response.ok) {
    throw new Error(`Formula verification failed: HTTP ${response.status}`);
  }

  const data = (await response.json()) as VerifyFormulasResponse;
  return { response: data, rateMeta };
}

/** Resolve the Google Address Search endpoint (local proxy or Cloud Function). */
export function getAddressSearchEndpoint(): string {
  const origin = typeof window !== 'undefined' ? String(window.location.origin || '') : '';
  if (/^https?:\/\//i.test(origin)) {
    return `${origin}/api/google-address-search`;
  }
  return 'https://us-central1-crompton-apps.cloudfunctions.net/googleAddressSearch';
}

/** Fetch a geocoding candidate from the backend. */
export async function fetchAddressCandidate(
  query: string,
  state?: string
): Promise<AddressCandidate | null> {
  const q = String(query || '').trim();
  if (!q) return null;

  const endpoint = getAddressSearchEndpoint();
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept-Language': 'en-AU,en;q=0.9',
      },
      body: JSON.stringify({ query: q, state: state || '' }),
    });
    if (!response.ok) return null;
    const data = (await response.json()) as { candidate?: unknown };
    const c = data.candidate as Record<string, unknown> | undefined;
    if (!c) return null;

    const lat = Number(c.lat);
    const lon = Number(c.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

    return {
      lat,
      lon,
      displayName: String(c.displayName || q),
      road: c.road != null ? String(c.road) : null,
      houseNumber: String(c.houseNumber || ''),
      provider: String(c.provider || 'Google Geocoding API'),
    };
  } catch {
    return null;
  }
}
