# Password Reset — Setup Checklist

Built fresh on 2026-06-23. Email delivery switched to SendGrid (Firebase Auth's built-in SMTP path proved unreliable in this project).

## Architecture

```
User → "Forgot password?" → enters username/email
       │
       ▼
   firebase.functions().httpsCallable('requestPasswordReset')
       │   ├─ resolves identifier → email via tia_users RTDB
       │   ├─ ensures Firebase Auth account exists for that email
       │   ├─ admin.auth().generatePasswordResetLink(email) → reset URL
       │   └─ sends branded HTML email via SendGrid API
       ▼
   Email arrives in user's inbox (from noreply@cromptonapps.com)
       │
       ▼
   User clicks link → /auth-action.html?mode=resetPassword&oobCode=...
       │   ├─ verifyPasswordResetCode → shows new-password form
       │   └─ confirmPasswordReset → redirects to login
       ▼
   User signs in with new password
```

Why server-side SendGrid instead of Firebase Auth's `sendPasswordResetEmail`: emails routed through Firebase's SMTP (default sender OR Workspace SMTP relay) weren't arriving — the issue traced to a combination of sender-domain authentication and deliverability quirks. Server-side SendGrid eliminates Firebase from the delivery path entirely; we still use `admin.auth().generatePasswordResetLink()` so the reset codes are issued and verified by Firebase Auth (the link's `confirmPasswordReset` flow is unchanged).

## Files touched

- `functions/index.js` — `requestPasswordReset` v2 onCall callable that does the lookup, Auth provision, link generation, and SendGrid send (bottom of file)
- `functions/package.json` — added `@sendgrid/mail` dependency
- `auth-action.html` — **new** branded handler page for reset/verify links
- `app.js` — Forgot Password handler rewritten (search for `// Forgot Password — fresh flow (2026-06-23)`)
- `admin.html` — `adminForgotPassword()` rewritten to use the same flow
- `index.html`, `index_developer.html`, `index_formulas.html` — `#paneReset` accepts username OR email; `firebase-functions-compat.js` loaded; `app.js?v=` cache key bumped to `20260623-pwreset2`
- `firebase.json` — **no changes needed** (callable doesn't use a Hosting rewrite)

## One-time SendGrid setup

1. **Sign up** at https://sendgrid.com (free tier: 100 emails/day — plenty for password resets).

2. **Authenticate your sending domain** (`cromptonapps.com`). In SendGrid:
   - Settings → Sender Authentication → **Authenticate Your Domain**
   - Provider: Google (since cromptonapps.com DNS is on Workspace) or "Other Host"
   - Domain: `cromptonapps.com`
   - SendGrid issues 3 CNAME records (DKIM, link branding). Add them to your DNS at the registrar / Google Workspace DNS.
   - Click **Verify** in SendGrid once DNS has propagated (5–30 min usually).

3. **Create an API key**:
   - Settings → API Keys → **Create API Key**
   - Name: `Crompton TIA Password Reset`
   - Permissions: **Restricted Access** → only enable "Mail Send" → Full Access
   - Copy the key (shown once — store securely).

4. **Store the API key in Firebase Functions Secret Manager**:
   ```powershell
   cd "D:\Crompton Labs\APPS\Cromton-Traffic-Impact-Asssessment"
   firebase functions:secrets:set SENDGRID_API_KEY
   # Paste the SendGrid API key when prompted, then press Enter
   ```
   The secret stays in Google Secret Manager — never in your source code or git.

## Deploy steps

```powershell
# 1. Install dependencies
cd "D:\Crompton Labs\APPS\Cromton-Traffic-Impact-Asssessment\functions"
npm install
cd ..

# 2. Deploy the function (it'll pick up the new SENDGRID_API_KEY secret)
firebase deploy --only functions:requestPasswordReset

# 3. Deploy hosting (HTML, app.js)
firebase deploy --only hosting
```

## One-time Firebase Console configuration

These cannot be done via code — they must be set in the [Firebase Console](https://console.firebase.google.com/project/crompton-apps/authentication) once.

### 1. Authentication → Templates → Password reset

Click the pencil icon to edit, then **"customise action URL"** (small link below the template body).

- **Action URL**: `https://crompton-apps.web.app/auth-action.html`

  (Or your custom domain if you've added one to Firebase Hosting — e.g. `https://tia.cromptonapps.com/auth-action.html`. Whichever domain is in Hosting → Custom domain.)

- **Sender name**: `Crompton TIA` (optional — defaults to project name)
- **From**: Leave default (`noreply@crompton-apps.firebaseapp.com`) unless you've set up a custom sender domain.
- **Reply-to**: e.g. `support@cromptonconcepts.com.au` (optional).

Save the template.

### 2. Authentication → Settings → Authorized domains

Make sure each of these is listed:

- `crompton-apps.firebaseapp.com`
- `crompton-apps.web.app`
- `tia.cromptonapps.com` (if used)
- `localhost` (for local dev)

The `actionCodeSettings.url` we send must be on one of these domains, otherwise Firebase returns `auth/unauthorized-continue-uri`.

### 3. (Optional, recommended) Verify your sender domain

If you want the reset emails to come from `noreply@cromptonapps.com.au` instead of the default Firebase address — and avoid spam-folder routing — go to **Authentication → Templates → SMTP settings** and configure SendGrid or another SMTP provider with a verified sending domain. Firebase's default sender works but has lower deliverability and sometimes lands in spam (likely the actual cause of the previous "email never arrives" reports).

## Testing

Callables can't easily be hit with curl (the Firebase SDK adds auth-token wrapping). Test end-to-end via the UI:

End-to-end test:

1. Open `https://crompton-apps.web.app/`.
2. Click **Forgot password?**, enter your username or email, click **Send Reset Link**.
3. Wait <60s. Check inbox (and spam) at the email on file.
4. Click the link in the email. You should land on `/auth-action.html?mode=resetPassword&oobCode=...`.
5. Enter a new password (2× for confirmation). Submit.
6. You should see the success screen, auto-redirect to the login page after 5s.
7. Sign in with the new password.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Form accepts but no email arrives, email IS on file | Sender domain not verified, going to spam | Configure custom SMTP (Console step 3 above) |
| `auth/unauthorized-continue-uri` in console | Domain missing from authorized list | Add to Console step 2 |
| Link in email lands on a Firebase-branded page, not `/auth-action.html` | Action URL not set in template | Console step 1 |
| `/auth-action.html` shows "Link not valid" immediately | Code expired (1h default) or already used | Request a fresh link |
| Callable error `functions/internal` | Check Cloud Functions logs in Firebase Console → Functions → Logs | Look for `[TIA] requestPasswordReset error:` lines |
| Callable error `functions/unavailable` | Function not yet deployed, or wrong region | Redeploy with `firebase deploy --only functions:requestPasswordReset` |

## Rollback

If something is wrong and you need to revert:

```powershell
git checkout HEAD~1 -- functions/index.js firebase.json app.js admin.html index.html index_developer.html index_formulas.html
rm auth-action.html PASSWORD_RESET_SETUP.md
firebase deploy --only hosting,functions
```

The old in-page reset code will be back. Note this won't fix the underlying issue (Firebase silently no-ops for missing Auth users) — it just reverts to the previous broken state.
