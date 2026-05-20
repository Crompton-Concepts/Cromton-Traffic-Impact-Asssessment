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

const { onRequest } = require('firebase-functions/v2/https');
const { beforeUserCreated } = require('firebase-functions/v2/identity');

// Cloud Function v2 uses modular imports
const functions = require('firebase-functions');
const admin     = require('firebase-admin');

admin.initializeApp();

const USERS_PATH = 'tia_users';

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
exports.provisionAuthUser = functions.auth.user().onCreate(async (user) => {
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
