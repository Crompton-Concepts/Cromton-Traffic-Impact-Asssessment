/**
 * TIA Firebase Cloud Functions
 *
 * Trigger: auth.user().onCreate
 * When a user is added directly in the Firebase console (or via any Firebase
 * Auth call), automatically provision a matching record in the `tia_users`
 * Realtime Database path so the account is visible in the admin portal.
 *
 * Without this function a Firebase-Auth-only account is invisible to the
 * admin portal because the portal reads exclusively from `tia_users` (RTDB).
 */

const admin     = require('firebase-admin');
const { onRequest } = require('firebase-functions/v2/https');
const { onCall, HttpsError } = require('firebase-functions/v1/https');
const { user } = require('firebase-functions/v1/auth');
const { defineSecret } = require('firebase-functions/params');

admin.initializeApp();

const USERS_PATH = 'tia_users';
const GOOGLE_MAPS_API_KEY = defineSecret('GOOGLE_MAPS_API_KEY');

// Origins permitted to call the HTTP functions. Keep in sync with cors.json.
const ALLOWED_ORIGINS = [
  'https://tia.cromptonapps.com',
  'https://cromptonapps.com',
  'https://crompton-apps.web.app',
  'https://crompton-apps.firebaseapp.com',
  'https://crompton-concepts.github.io',
  'https://cromptonconcepts.github.io',
  'http://localhost:5500',
  'http://127.0.0.1:5500'
];

// Echo the request Origin only when it is allow-listed; otherwise emit no
// CORS header so non-approved browsers are blocked. Returns the resolved
// origin (or '' when not allowed) so callers can also reject server-side.
function applyCors(req, res) {
  const origin = String(req.headers.origin || '');
  if (origin && ALLOWED_ORIGINS.includes(origin)) {
    res.set('Access-Control-Allow-Origin', origin);
    res.set('Vary', 'Origin');
    return origin;
  }
  return '';
}

// True when the request originates from an allow-listed site. Used as a
// defence-in-depth check on the unauthenticated geocode proxy so scripted
// requests that omit/forge a non-approved Origin are rejected.
function originAllowed(req) {
  const origin = String(req.headers.origin || '');
  if (origin) return ALLOWED_ORIGINS.includes(origin);
  // No Origin header (e.g. server-to-server) — fall back to Referer host.
  const referer = String(req.headers.referer || '');
  return ALLOWED_ORIGINS.some((o) => referer.startsWith(o));
}

function normalizeStateCode(raw) {
  const code = String(raw || '').trim().toUpperCase();
  if (code === 'NSW') return 'NSW';
  if (code === 'SA') return 'SA';
  return 'QLD';
}

function extractGoogleAddressParts(result) {
  const components = Array.isArray(result && result.address_components)
    ? result.address_components
    : [];
  const findByType = (type) => {
    const hit = components.find((c) => Array.isArray(c.types) && c.types.includes(type));
    return hit || null;
  };

  const state = findByType('administrative_area_level_1');
  const country = findByType('country');
  const route = findByType('route');
  const streetNumber = findByType('street_number');

  return {
    stateShort: String(state && state.short_name ? state.short_name : '').toUpperCase(),
    countryShort: String(country && country.short_name ? country.short_name : '').toUpperCase(),
    road: String(route && route.long_name ? route.long_name : ''),
    houseNumber: String(streetNumber && streetNumber.long_name ? streetNumber.long_name : '')
  };
}

function scoreGoogleCandidate(result, requestedRoad, requestedHouseNumber, selectedStateCode) {
  const parts = extractGoogleAddressParts(result);
  const formatted = String(result && result.formatted_address ? result.formatted_address : '');
  const normalizedRoad = String(requestedRoad || '').toLowerCase().trim();
  const candidateRoad = String(parts.road || '').toLowerCase().trim();
  const requestedHouse = String(requestedHouseNumber || '').toLowerCase().trim();
  const candidateHouse = String(parts.houseNumber || '').toLowerCase().trim();

  let score = 0;

  if (parts.countryShort === 'AU') score += 80;
  else score -= 120;

  if (parts.stateShort === selectedStateCode) score += 45;
  else if (parts.stateShort) score -= 60;

  if (normalizedRoad) {
    if (candidateRoad && (candidateRoad === normalizedRoad || candidateRoad.includes(normalizedRoad) || normalizedRoad.includes(candidateRoad))) {
      score += 40;
    } else if (formatted.toLowerCase().includes(normalizedRoad)) {
      score += 10;
    } else {
      score -= 30;
    }
  }

  if (requestedHouse) {
    if (candidateHouse && candidateHouse === requestedHouse) score += 65;
    else if (candidateHouse) score -= 55;
    else score -= 10;
  }

  const locationType = String(result && result.geometry && result.geometry.location_type ? result.geometry.location_type : '').toUpperCase();
  if (locationType === 'ROOFTOP') score += 15;
  else if (locationType === 'RANGE_INTERPOLATED') score += 4;
  else if (locationType === 'APPROXIMATE') score -= 8;

  return score;
}

function parseRequestedRoad(address) {
  const value = String(address || '').trim();
  if (!value) return '';
  return value
    .split(',')[0]
    .replace(/^\s*(?:\d+[a-zA-Z]?\s*\/\s*)?\d+[a-zA-Z]?\s+/, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseRequestedHouseNumber(address) {
  const value = String(address || '').trim();
  if (!value) return '';
  const first = value.split(',')[0].trim();
  const unitMatch = first.match(/^\s*(?:\d+[a-zA-Z]?\s*\/\s*)?(\d+[a-zA-Z]?)(?=\b|\s)/);
  return unitMatch ? String(unitMatch[1]).toUpperCase() : '';
}

exports.googleAddressSearch = onRequest({ secrets: [GOOGLE_MAPS_API_KEY] }, async (req, res) => {
  applyCors(req, res);
  res.set('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.set('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(204).send('');
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Reject requests that do not originate from an approved site. This is a
  // defence-in-depth guard against scripted abuse of the (unauthenticated)
  // geocode proxy, which spends the project's Google Maps quota.
  if (!originAllowed(req)) {
    return res.status(403).json({ error: 'Origin not allowed' });
  }

  try {
    const body = req.body || {};
    const query = String(body.query || '').trim();
    const stateCode = normalizeStateCode(body.state);
    if (!query) {
      return res.status(400).json({ error: 'Missing query' });
    }
    if (query.length > 300) {
      return res.status(400).json({ error: 'Query too long' });
    }

    const apiKey = GOOGLE_MAPS_API_KEY.value() || '';
    if (!apiKey) {
      return res.status(500).json({ error: 'Google Maps API key not configured' });
    }

    const requestedRoad = parseRequestedRoad(query);
    const requestedHouseNumber = parseRequestedHouseNumber(query);
    const components = `country:AU|administrative_area:${stateCode}`;
    const endpoint = `https://maps.googleapis.com/maps/api/geocode/json?address=${encodeURIComponent(query)}&components=${encodeURIComponent(components)}&region=au&key=${encodeURIComponent(apiKey)}`;

    const response = await fetch(endpoint, {
      method: 'GET',
      headers: { 'Accept-Language': 'en-AU,en;q=0.9' }
    });

    if (!response.ok) {
      return res.status(502).json({ error: `Google request failed: ${response.status}` });
    }

    const data = await response.json();
    const results = Array.isArray(data && data.results) ? data.results : [];
    if (!results.length) {
      return res.json({ ok: true, candidate: null, alternatives: [] });
    }

    const ranked = results
      .map((result) => {
        const parts = extractGoogleAddressParts(result);
        const lat = Number(result && result.geometry && result.geometry.location && result.geometry.location.lat);
        const lon = Number(result && result.geometry && result.geometry.location && result.geometry.location.lng);
        const score = scoreGoogleCandidate(result, requestedRoad, requestedHouseNumber, stateCode);
        return {
          score,
          result,
          candidate: {
            lat,
            lon,
            displayName: String(result && result.formatted_address ? result.formatted_address : query),
            road: parts.road || requestedRoad,
            houseNumber: parts.houseNumber || requestedHouseNumber,
            provider: 'Google Geocoding API',
            state: parts.stateShort,
            country: parts.countryShort,
            locationType: String(result && result.geometry && result.geometry.location_type ? result.geometry.location_type : '')
          }
        };
      })
      .filter((entry) => Number.isFinite(entry.candidate.lat) && Number.isFinite(entry.candidate.lon))
      .sort((a, b) => b.score - a.score);

    const top = ranked[0] || null;
    const minAcceptable = requestedHouseNumber ? 35 : 10;
    const accepted = top && top.score >= minAcceptable && top.candidate.country === 'AU' && top.candidate.state === stateCode
      ? top.candidate
      : null;

    return res.json({
      ok: true,
      candidate: accepted,
      alternatives: ranked.slice(0, 5).map((r) => ({ ...r.candidate, score: r.score }))
    });
  } catch (err) {
    return res.status(500).json({ error: err && err.message ? err.message : String(err) });
  }
});

/**
 * auth.user().onCreate — fires every time a new Firebase Auth user is created,
 * whether via the Firebase console, an Auth API call, or the app's own
 * createUserWithEmailAndPassword (e.g. the password-reset flow in admin.html).
 *
 * Logic:
 *  1. Skip if a tia_users record with this email already exists (portal-created users).
 *  2. Derive a safe username from the email local-part.
 *  3. Write a stub record flagged with provisionedFromAuth: true.
 *     The stub has NO passwordHash — an admin must set a password via the portal,
 *     or the user can log in after the admin uses "Forgot Password" to send a reset link.
 */
exports.provisionAuthUser = user().onCreate(async (user) => {
  if (!user.email) {
    console.log('[TIA] Skipping Auth user without email:', user.uid);
    return null;
  }

  const db       = admin.database();
  const usersRef = db.ref(USERS_PATH);

  // ── 1. Check whether a tia_users record already exists for this email ──
  const snapshot = await usersRef.once('value');
  const users    = snapshot.val() || {};

  const emailLower     = user.email.toLowerCase();
  const alreadyExists  = Object.values(users).some(
    u => u && u.email && u.email.toLowerCase() === emailLower
  );

  if (alreadyExists) {
    console.log(`[TIA] tia_users record already present for ${user.email} — skipping provision.`);
    return null;
  }

  // ── 2. Derive a unique username from the email local-part ──────────────
  const base = emailLower
    .split('@')[0]
    .replace(/[^a-z0-9._-]/g, '')   // strip disallowed chars
    .slice(0, 30)                    // cap length
    || 'user';

  let username = base;
  let suffix   = 1;
  while (users[username]) {
    username = `${base}${suffix++}`;
  }

  // ── 3. Write stub record ────────────────────────────────────────────────
  const record = {
    username,
    email:               user.email,
    tier:                'free',
    createdAt:           new Date().toISOString(),
    provisionedFromAuth: true,   // flag: admin still needs to set a password
  };

  await usersRef.child(username).set(record);

  console.log(
    `[TIA] Auto-provisioned tia_users stub for ${user.email} ` +
    `(username: "${username}"). Admin must set a password before the user can log in.`
  );

  return null;
});

/**
 * adminSetUserPassword — callable by signed-in admins only.
 * Uses Admin SDK to set (or create) a Firebase Auth account with a specific password,
 * bypassing the client-side limitation that only the current user can change their own password.
 *
 * Called from admin.html when the admin sets/resets a user's password.
 */
exports.adminSetUserPassword = onCall(async (data, context) => {
  if (!context.auth) {
    throw new HttpsError('unauthenticated', 'Must be signed in.');
  }

  // Verify the caller is an admin in tia_users.
  const db       = admin.database();
  const usersRef = db.ref(USERS_PATH);
  const snap     = await usersRef.once('value');
  const users    = snap.val() || {};
  const callerEmail = (context.auth.token.email || '').toLowerCase();
  const callerRec   = Object.values(users).find(
    u => u && u.email && u.email.toLowerCase() === callerEmail
  );
  if (!callerRec || !callerRec.isAdmin) {
    throw new HttpsError('permission-denied', 'Admin privileges required.');
  }

  const { email, newPassword } = data || {};
  if (!email || typeof newPassword !== 'string' || newPassword.length < 8) {
    throw new HttpsError('invalid-argument', 'Valid email and password (8+ chars) required.');
  }

  try {
    // Try to update existing account first.
    const existing = await admin.auth().getUserByEmail(email);
    await admin.auth().updateUser(existing.uid, { password: newPassword });
    return { success: true, created: false };
  } catch (err) {
    if (err.code === 'auth/user-not-found') {
      // Create fresh account — provisionAuthUser will write the RTDB stub.
      await admin.auth().createUser({ email, password: newPassword });
      return { success: true, created: true };
    }
    throw new HttpsError('internal', err.message || String(err));
  }
});

/**
 * reconcileAuthUsers — callable by signed-in admins only.
 *
 * Enumerates every Firebase Auth user via the Admin SDK, compares against
 * the tia_users RTDB path by email, and writes a stub for anyone missing.
 * Idempotent: safe to re-run; existing records are left untouched.
 *
 * Use when historical signups disappeared from tia_users (e.g. due to a
 * stale-client clobber) but their Firebase Auth accounts still exist.
 */
exports.reconcileAuthUsers = onRequest({ region: 'us-central1', invoker: 'private' }, async (req, res) => {
  // CORS — same shape as googleAddressSearch since this is reached via a
  // Firebase Hosting rewrite (/api/reconcile-auth-users) for ingress-policy
  // reasons (Domain Restricted Sharing blocks public allUsers invoker on
  // newly-created callables in this org).
  applyCors(req, res);
  res.set('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.set('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') return res.status(204).send('');
  if (req.method !== 'POST')   return res.status(405).json({ error: 'Method not allowed' });

  // Verify the Firebase ID token from the Authorization header.
  const authHeader = String(req.headers.authorization || req.headers.Authorization || '');
  const match = authHeader.match(/^Bearer\s+(.+)$/i);
  if (!match) return res.status(401).json({ error: 'Missing Bearer token.' });
  let decoded;
  try {
    decoded = await admin.auth().verifyIdToken(match[1]);
  } catch (err) {
    return res.status(401).json({ error: 'Invalid token: ' + (err.message || err.code) });
  }

  const db          = admin.database();
  const usersRef    = db.ref(USERS_PATH);
  const snap        = await usersRef.once('value');
  const users       = snap.val() || {};
  const callerEmail = String(decoded.email || '').toLowerCase();
  const callerRec   = Object.values(users).find(
    u => u && u.email && u.email.toLowerCase() === callerEmail
  );
  if (!callerRec || !callerRec.isAdmin) {
    return res.status(403).json({ error: 'Admin privileges required.' });
  }

  const emailsPresent  = new Set();
  const usernamesInUse = new Set(Object.keys(users));
  for (const u of Object.values(users)) {
    if (u && u.email) emailsPresent.add(String(u.email).toLowerCase());
  }

  const created = [];
  const skipped = [];
  let scanned   = 0;
  let pageToken;

  do {
    const page = await admin.auth().listUsers(1000, pageToken);
    for (const authUser of page.users) {
      scanned++;
      const email = authUser.email;
      if (!email) {
        skipped.push({ uid: authUser.uid, reason: 'no-email' });
        continue;
      }
      const emailLower = email.toLowerCase();
      if (emailsPresent.has(emailLower)) continue;

      const base = emailLower
        .split('@')[0]
        .replace(/[^a-z0-9._-]/g, '')
        .slice(0, 30) || 'user';

      let username = base;
      let suffix   = 1;
      while (usernamesInUse.has(username)) {
        username = `${base}${suffix++}`;
      }
      usernamesInUse.add(username);
      emailsPresent.add(emailLower);

      const record = {
        username,
        email,
        tier:                'free',
        createdAt:           authUser.metadata && authUser.metadata.creationTime
                              ? new Date(authUser.metadata.creationTime).toISOString()
                              : new Date().toISOString(),
        provisionedFromAuth: true,
        reconciled:          true,
      };

      await usersRef.child(username).set(record);
      created.push({ username, email });
    }
    pageToken = page.pageToken;
  } while (pageToken);

  console.log(
    `[TIA] reconcileAuthUsers: scanned=${scanned} created=${created.length} ` +
    `skipped=${skipped.length} (caller=${callerEmail})`
  );

  return res.json({ scanned, created, skipped });
});
