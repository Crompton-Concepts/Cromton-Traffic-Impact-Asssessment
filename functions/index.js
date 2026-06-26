/**
 * TIA Firebase Cloud Functions — updated with tia_admins support
 *
 * Trigger: auth.user().onCreate
 * When a user is added directly in the Firebase console (or via any Firebase
 * Auth call), automatically provision a matching record in the `tia_users`
 * Realtime Database path so the account is visible in the admin portal.
 */

const admin     = require('firebase-admin');
const { onRequest, onCall: onCallV2, HttpsError: HttpsErrorV2 } = require('firebase-functions/v2/https');
const { onCall, HttpsError } = require('firebase-functions/v1/https');
const { user } = require('firebase-functions/v1/auth');
const { defineSecret } = require('firebase-functions/params');

admin.initializeApp();

const USERS_PATH = 'tia_users';
const ADMINS_PATH = 'tia_admins';
const AUDIT_PATH = 'tia_audit_log';
const GOOGLE_MAPS_API_KEY = defineSecret('GOOGLE_MAPS_API_KEY');
const SENDGRID_API_KEY    = defineSecret('SENDGRID_API_KEY');

// Sender / app branding used by the SendGrid password-reset email.
// Update FROM_EMAIL to a verified SendGrid sender (single-sender or domain-auth).
const FROM_EMAIL    = 'noreply@cromptonapps.com';
const FROM_NAME     = 'Crompton Traffic Impact Assessment';
const REPLY_TO      = 'labs@cromptonapps.com';
const APP_DISPLAY   = 'Crompton TIA';

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
 *  4. If the user is an admin (isAdmin=true in their existing record), also
 *     write to tia_admins for fast rule-based admin lookups.
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
 * Also syncs the tia_admins path when admin status changes.
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

  const { email, newPassword, isAdmin } = data || {};
  if (!email || typeof newPassword !== 'string' || newPassword.length < 8) {
    throw new HttpsError('invalid-argument', 'Valid email and password (8+ chars) required.');
  }

  try {
    // Try to update existing account first.
    const existing = await admin.auth().getUserByEmail(email);
    await admin.auth().updateUser(existing.uid, { password: newPassword });

    // Sync tia_admins if admin flag is being toggled
    if (typeof isAdmin === 'boolean') {
      const emailKey = email.toLowerCase().replace(/\./g, ',');
      const adminsRef = db.ref(ADMINS_PATH);
      if (isAdmin) {
        await adminsRef.child(emailKey).set(true);
      } else {
        await adminsRef.child(emailKey).remove();
      }
      // Sync Firebase Auth custom claim for Storage rules
      try {
        const targetUser = await admin.auth().getUserByEmail(email);
        await admin.auth().setCustomUserClaims(targetUser.uid, { admin: isAdmin });
      } catch (claimErr) {
        console.warn(`[TIA] Failed to sync custom claim for ${email}:`, claimErr.message);
      }
      // Write audit log
      await db.ref(AUDIT_PATH).push().set({
        action: 'admin_toggle',
        targetEmail: email,
        isAdmin,
        actorEmail: callerEmail,
        timestamp: new Date().toISOString()
      });
    }

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
 * Also populates tia_admins for any user with isAdmin=true.
 */
exports.reconcileAuthUsers = onRequest({ region: 'us-central1' }, async (req, res) => {
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
  if (!match) {
    console.warn('[TIA] reconcileAuthUsers: missing or malformed Authorization header');
    return res.status(401).json({ error: 'Missing Bearer token.' });
  }
  let decoded;
  try {
    decoded = await admin.auth().verifyIdToken(match[1]);
  } catch (err) {
    console.warn('[TIA] reconcileAuthUsers: token verification failed:', err.message);
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

  // ── Populate tia_admins AND sync custom claims for any user with isAdmin=true ──
  const adminsRef = db.ref(ADMINS_PATH);
  let adminCount = 0;
  let claimErrors = 0;
  for (const [uname, u] of Object.entries(users)) {
    if (u && u.isAdmin && u.email) {
      const emailKey = u.email.toLowerCase().replace(/\./g, ',');
      await adminsRef.child(emailKey).set(true);
      adminCount++;
      // Sync custom claim for Storage rules
      try {
        const targetUser = await admin.auth().getUserByEmail(u.email);
        await admin.auth().setCustomUserClaims(targetUser.uid, { admin: true });
      } catch (claimErr) {
        claimErrors++;
        console.warn(`[TIA] reconcile: custom claim failed for ${u.email}:`, claimErr.message);
      }
    }
  }

  console.log(
    `[TIA] reconcileAuthUsers: scanned=${scanned} created=${created.length} ` +
    `skipped=${skipped.length} adminsSynced=${adminCount} (caller=${callerEmail})`
  );

  return res.json({ scanned, created, skipped, adminsSynced: adminCount });
});

/**
 * requestPasswordReset — Gen 2 callable that sends the reset email via SendGrid.
 *
 * The function is responsible for the entire reset email lifecycle:
 *   1. Resolve identifier (email or username) → tia_users record.
 *   2. Provision a Firebase Auth account if one doesn't exist yet for the email.
 *   3. Generate a Firebase password-reset link via the Admin SDK.
 *   4. Send a branded HTML email containing the link via SendGrid.
 *
 * We use SendGrid instead of relying on Firebase Auth's built-in SMTP delivery
 * because deliverability via that path has been unreliable in this project
 * (Workspace SMTP relay + sender-domain authentication problems). SendGrid
 * gives us a verifiable sender, DKIM/SPF for cromptonapps.com, and full
 * control over the email template.
 *
 * Client invokes via:
 *   firebase.functions().httpsCallable('requestPasswordReset')({ identifier })
 *
 * Input data: { identifier: "<email or username>" }
 * Returns:    { ok: true, sent: true|false }
 *             - sent=true  → email was sent (or attempted to be sent)
 *             - sent=false → identifier didn't resolve to a tia_users record;
 *                            caller still shows generic success (enumeration safe).
 *
 * Throws HttpsError on bad input, rate limit, or server failure. Rate-limited
 * at one request per identifier per 60 seconds via in-memory Map.
 */
const _resetRateLimit = new Map(); // identifier-lower -> ts
const RESET_RATE_MS = 60 * 1000;

function buildResetEmailHtml(displayName, resetLink) {
  const safeName = String(displayName || 'there')
    .replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
  return `<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#f4f6f7;font-family:'Source Sans 3',Arial,sans-serif;color:#1a2326;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f4f6f7;padding:32px 12px;">
      <tr><td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;background:#ffffff;border-radius:12px;box-shadow:0 4px 16px rgba(15,47,50,0.08);overflow:hidden;">
          <tr><td style="background:linear-gradient(135deg,#1f5e63 0%,#0f2f32 100%);padding:24px 28px;color:#ffffff;">
            <div style="font-family:'Space Grotesk',Arial,sans-serif;font-weight:700;font-size:1.15rem;letter-spacing:0.3px;">Crompton Traffic Impact Assessment</div>
          </td></tr>
          <tr><td style="padding:28px;">
            <h1 style="margin:0 0 14px;font-family:'Space Grotesk',Arial,sans-serif;font-size:1.4rem;color:#0f2f32;">Reset your password</h1>
            <p style="margin:0 0 16px;line-height:1.55;">Hi ${safeName},</p>
            <p style="margin:0 0 16px;line-height:1.55;">We received a request to reset the password for your ${APP_DISPLAY} account. Click the button below to choose a new one.</p>
            <p style="margin:24px 0;text-align:center;">
              <a href="${resetLink}" style="background:linear-gradient(135deg,#1f5e63 0%,#0f2f32 100%);color:#ffffff;text-decoration:none;font-weight:600;padding:12px 28px;border-radius:8px;display:inline-block;letter-spacing:0.3px;">Reset password</a>
            </p>
            <p style="margin:0 0 12px;font-size:0.85rem;color:#6b7a7d;line-height:1.45;">If the button doesn't work, copy and paste this link into your browser:</p>
            <p style="margin:0 0 20px;font-size:0.82rem;word-break:break-all;color:#3c5054;"><a href="${resetLink}" style="color:#1f5e63;">${resetLink}</a></p>
            <p style="margin:0 0 6px;font-size:0.85rem;color:#6b7a7d;line-height:1.45;">This link expires in 1 hour. If you didn't request a password reset, you can safely ignore this email.</p>
          </td></tr>
          <tr><td style="background:#f4f6f7;padding:16px 28px;border-top:1px solid #e6eaeb;font-size:0.78rem;color:#6b7a7d;">
            Sent by ${APP_DISPLAY}. Replies go to ${REPLY_TO}.
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>`;
}

function buildResetEmailText(displayName, resetLink) {
  const safeName = String(displayName || 'there').replace(/[\r\n]/g, ' ');
  return `Hi ${safeName},

We received a request to reset the password for your ${APP_DISPLAY} account.

Open this link to choose a new password (expires in 1 hour):
${resetLink}

If you didn't request a password reset, you can safely ignore this email.

— ${APP_DISPLAY}
Replies go to ${REPLY_TO}`;
}

exports.requestPasswordReset = onCallV2(
  { region: 'us-central1', cors: true, invoker: 'public', secrets: [SENDGRID_API_KEY] },
  async (request) => {
    const data = (request && request.data) || {};
    const identifierRaw = String(data.identifier || '').trim();
    if (!identifierRaw) {
      throw new HttpsErrorV2('invalid-argument', 'identifier is required');
    }
    if (identifierRaw.length > 254) {
      throw new HttpsErrorV2('invalid-argument', 'identifier too long');
    }

    const identifierLower = identifierRaw.toLowerCase();

    // ── rate limit ──
    const now = Date.now();
    const last = _resetRateLimit.get(identifierLower) || 0;
    if (now - last < RESET_RATE_MS) {
      const waitSec = Math.ceil((RESET_RATE_MS - (now - last)) / 1000);
      throw new HttpsErrorV2('resource-exhausted', `Please wait ${waitSec}s before requesting another reset.`);
    }
    _resetRateLimit.set(identifierLower, now);

    try {
      const db       = admin.database();
      const usersRef = db.ref(USERS_PATH);
      const snap     = await usersRef.once('value');
      const users    = snap.val() || {};

      // Resolve identifier → tia_users record.
      // Match priority: exact username key (case-insensitive), then email.
      let found = null;
      let foundUsername = null;
      const isEmailShaped = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(identifierRaw);

      if (!isEmailShaped) {
        for (const [uname, u] of Object.entries(users)) {
          if (String(uname).toLowerCase() === identifierLower) {
            found = u; foundUsername = uname; break;
          }
        }
      }
      if (!found) {
        for (const [uname, u] of Object.entries(users)) {
          if (u && u.email && String(u.email).toLowerCase() === identifierLower) {
            found = u; foundUsername = uname; break;
          }
        }
      }

      if (!found || !found.email) {
        console.log(`[TIA] requestPasswordReset: unknown identifier "${identifierRaw}" — silent no-op.`);
        return { ok: true, sent: false };
      }

      const email = String(found.email).trim();
      const displayName = String(found.fullName || found.displayName || foundUsername || email.split('@')[0]).trim();

      // Ensure a Firebase Auth account exists for this email so generatePasswordResetLink works.
      try {
        await admin.auth().getUserByEmail(email);
      } catch (err) {
        if (err && err.code === 'auth/user-not-found') {
          const tempPw = require('crypto').randomBytes(24).toString('base64') + 'Aa1!';
          await admin.auth().createUser({ email, password: tempPw, emailVerified: false });
          console.log(`[TIA] requestPasswordReset: provisioned Auth account for ${email}`);
        } else {
          throw err;
        }
      }

      // Generate the Firebase password-reset link. The action handler is whatever
      // is configured in Firebase Console → Authentication → Templates → Action URL
      // (defaults to https://crompton-apps.firebaseapp.com/__/auth/action; when
      // /auth-action.html is set there, the link lands on our branded handler).
      const actionCodeSettings = {
        url: 'https://crompton-apps.web.app/index.html',
        handleCodeInApp: false
      };
      const resetLink = await admin.auth().generatePasswordResetLink(email, actionCodeSettings);

      // Send via SendGrid.
      const sgKey = SENDGRID_API_KEY.value();
      if (!sgKey) {
        console.error('[TIA] requestPasswordReset: SENDGRID_API_KEY is not set');
        throw new HttpsErrorV2('failed-precondition', 'Email service is not configured. Contact support.');
      }
      const sgMail = require('@sendgrid/mail');
      sgMail.setApiKey(sgKey);

      const msg = {
        to: email,
        from: { email: FROM_EMAIL, name: FROM_NAME },
        replyTo: REPLY_TO,
        subject: `Reset your ${APP_DISPLAY} password`,
        text: buildResetEmailText(displayName, resetLink),
        html: buildResetEmailHtml(displayName, resetLink),
        // Mail settings: bypass SendGrid spam filter for transactional auth emails.
        mailSettings: { sandboxMode: { enable: false } },
        // Use SendGrid categories so the dashboard groups reset emails together.
        categories: ['password-reset', 'tia']
      };

      try {
        await sgMail.send(msg);
        console.log(`[TIA] requestPasswordReset: sent reset email to ${email}`);
      } catch (sendErr) {
        const body = sendErr && sendErr.response && sendErr.response.body ? JSON.stringify(sendErr.response.body) : '';
        console.error('[TIA] requestPasswordReset SendGrid error:', sendErr && sendErr.message, body);
        throw new HttpsErrorV2('internal', 'Could not send reset email. Please try again later.');
      }

      return { ok: true, sent: true };
    } catch (err) {
      if (err instanceof HttpsErrorV2) throw err;
      console.error('[TIA] requestPasswordReset error:', err && err.message ? err.message : err);
      throw new HttpsErrorV2('internal', 'Could not process reset request. Please try again later.');
    }
  }
);
