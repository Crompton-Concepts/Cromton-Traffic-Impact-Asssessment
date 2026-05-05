/**
 * TIA User Sync Module — user-sync.js
 *
 * Wraps Firebase Realtime Database to provide cross-device user account sync.
 * Falls back silently to localStorage-only mode if Firebase is not configured
 * or is unreachable.
 *
 * Exposed as window.TIASync = { pullAll, saveUser, deleteUser,
 *                                restoreUser, purgeUser, isEnabled }
 */
(function () {
  'use strict';

  const USERS_PATH        = 'tia_users';
  const DELETED_PATH      = 'tia_deleted_users';
  const USERS_STORE_KEY   = 'crompton_tia_users';
  const DELETED_STORE_KEY = 'crompton_tia_deleted_users';
  const PULL_TIMEOUT_MS   = 3000; // max wait for Firebase on login

  let _db          = null;
  let _syncEnabled = false;

  // ── Initialise ────────────────────────────────────────────────────────────
  function _init() {
    // Guard: config must exist and must not be the placeholder
    if (
      typeof FIREBASE_CONFIG === 'undefined' ||
      !FIREBASE_CONFIG.apiKey ||
      FIREBASE_CONFIG.apiKey === 'YOUR_API_KEY' ||
      !FIREBASE_CONFIG.databaseURL ||
      FIREBASE_CONFIG.databaseURL.includes('YOUR_PROJECT_ID')
    ) {
      console.warn('[TIASync] firebase-config.js not filled in — running in local-only mode.');
      return;
    }

    try {
      // Avoid re-initialising if another script already called initializeApp
      if (!firebase.apps.length) {
        firebase.initializeApp(FIREBASE_CONFIG);
      }
      _db = firebase.database();
      _syncEnabled = true;
      console.info('[TIASync] Connected to Firebase Realtime Database ✓');
    } catch (err) {
      console.warn('[TIASync] Firebase init failed — local-only mode:', err.message);
    }
  }

  // ── Local helpers ─────────────────────────────────────────────────────────
  function _getLocal(key) {
    try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch { return {}; }
  }
  function _setLocal(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (_) {}
  }

  // ── Timeout race ──────────────────────────────────────────────────────────
  function _withTimeout(promise, ms) {
    const timer = new Promise(resolve => setTimeout(resolve, ms, null));
    return Promise.race([promise, timer]);
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Pull all users from Firebase and merge into localStorage.
   * Remote record always wins for same-key conflicts.
   * Returns true on success, false on failure/timeout.
   */
  async function pullAll() {
    if (!_syncEnabled || !_db) return false;
    try {
      const result = await _withTimeout(_db.ref(USERS_PATH).get(), PULL_TIMEOUT_MS);
      if (!result) return false; // timeout

      if (result.exists()) {
        const remote  = result.val() || {};
        const local   = _getLocal(USERS_STORE_KEY);
        // Remote wins — but keep any local-only keys (e.g. default admin seeded on first load)
        const merged  = Object.assign({}, local, remote);
        _setLocal(USERS_STORE_KEY, merged);
      }

      // Also sync deleted users table
      const delResult = await _withTimeout(_db.ref(DELETED_PATH).get(), PULL_TIMEOUT_MS);
      if (delResult && delResult.exists()) {
        _setLocal(DELETED_STORE_KEY, delResult.val() || {});
      }

      return true;
    } catch (err) {
      console.warn('[TIASync] pullAll failed:', err.message);
      return false;
    }
  }

  /**
   * Save (create or update) a single user record to Firebase.
   * Also mirrors to localStorage immediately.
   */
  async function saveUser(username, record) {
    if (!username || !record) return false;

    // Always update localStorage first (instant)
    const local = _getLocal(USERS_STORE_KEY);
    local[username] = record;
    _setLocal(USERS_STORE_KEY, local);

    if (!_syncEnabled || !_db) return false;
    try {
      await _db.ref(`${USERS_PATH}/${username}`).set(record);
      return true;
    } catch (err) {
      console.warn('[TIASync] saveUser failed:', err.message);
      return false;
    }
  }

  /**
   * Soft-delete a user: updates the main users path (marks deleted=true)
   * and writes to the deleted archive path.
   */
  async function deleteUser(username, mainRecord, archivedRecord) {
    if (!username) return false;

    // Mirror to localStorage
    if (mainRecord) {
      const local = _getLocal(USERS_STORE_KEY);
      local[username] = mainRecord;
      _setLocal(USERS_STORE_KEY, local);
    }
    if (archivedRecord) {
      const deleted = _getLocal(DELETED_STORE_KEY);
      deleted[username] = archivedRecord;
      _setLocal(DELETED_STORE_KEY, deleted);
    }

    if (!_syncEnabled || !_db) return false;
    try {
      const updates = {};
      if (mainRecord)    updates[`${USERS_PATH}/${username}`]   = mainRecord;
      if (archivedRecord) updates[`${DELETED_PATH}/${username}`] = archivedRecord;
      await _db.ref().update(updates);
      return true;
    } catch (err) {
      console.warn('[TIASync] deleteUser failed:', err.message);
      return false;
    }
  }

  /**
   * Restore a deleted user: writes back to users path, removes from deleted path.
   */
  async function restoreUser(username, record) {
    if (!username || !record) return false;

    // Mirror to localStorage
    const local = _getLocal(USERS_STORE_KEY);
    local[username] = record;
    _setLocal(USERS_STORE_KEY, local);
    const deleted = _getLocal(DELETED_STORE_KEY);
    delete deleted[username];
    _setLocal(DELETED_STORE_KEY, deleted);

    if (!_syncEnabled || !_db) return false;
    try {
      const updates = {};
      updates[`${USERS_PATH}/${username}`]  = record;
      updates[`${DELETED_PATH}/${username}`] = null; // removes the node
      await _db.ref().update(updates);
      return true;
    } catch (err) {
      console.warn('[TIASync] restoreUser failed:', err.message);
      return false;
    }
  }

  /**
   * Permanently delete a user from both paths.
   */
  async function purgeUser(username) {
    if (!username) return false;

    // Mirror to localStorage
    const local = _getLocal(USERS_STORE_KEY);
    if (local[username] && local[username].deleted) delete local[username];
    _setLocal(USERS_STORE_KEY, local);
    const deleted = _getLocal(DELETED_STORE_KEY);
    delete deleted[username];
    _setLocal(DELETED_STORE_KEY, deleted);

    if (!_syncEnabled || !_db) return false;
    try {
      const updates = {};
      updates[`${USERS_PATH}/${username}`]  = null;
      updates[`${DELETED_PATH}/${username}`] = null;
      await _db.ref().update(updates);
      return true;
    } catch (err) {
      console.warn('[TIASync] purgeUser failed:', err.message);
      return false;
    }
  }

  /**
   * Push the full admin-side users+deleted DBs to Firebase.
   * Used by admin portal after bulk changes.
   */
  async function pushAll(usersDb, deletedDb) {
    if (!_syncEnabled || !_db) return false;
    try {
      const updates = {};
      if (usersDb)   updates[USERS_PATH]   = usersDb;
      if (deletedDb) updates[DELETED_PATH] = deletedDb;
      await _db.ref().update(updates);
      return true;
    } catch (err) {
      console.warn('[TIASync] pushAll failed:', err.message);
      return false;
    }
  }

  function isEnabled() { return _syncEnabled; }

  // ── Bootstrap ─────────────────────────────────────────────────────────────
  _init();

  window.TIASync = {
    pullAll,
    saveUser,
    deleteUser,
    restoreUser,
    purgeUser,
    pushAll,
    isEnabled
  };

})();
