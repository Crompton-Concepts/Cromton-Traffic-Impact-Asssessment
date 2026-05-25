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

/**
 * adminSetUserPassword — callable by signed-in admins only.
 * Uses Admin SDK to set (or create) a Firebase Auth account with a specific password,
 * bypassing the client-side limitation that only the current user can change their own password.
 *
 * Called from admin.html when the admin sets/resets a user's password.
 */
exports.adminSetUserPassword = functions.https.onCall(async (data, context) => {
  if (!context.auth) {
    throw new functions.https.HttpsError('unauthenticated', 'Must be signed in.');
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
    throw new functions.https.HttpsError('permission-denied', 'Admin privileges required.');
  }

  const { email, newPassword } = data || {};
  if (!email || typeof newPassword !== 'string' || newPassword.length < 8) {
    throw new functions.https.HttpsError('invalid-argument', 'Valid email and password (8+ chars) required.');
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
    throw new functions.https.HttpsError('internal', err.message || String(err));
  }
});
