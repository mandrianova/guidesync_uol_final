# UI authorization export

`export_local_storage_auth.js` builds the JSON expected by GuideSync's
**UI authorization value** field. It reads Auth0 SPA cache entries from the
currently authenticated product UI and optionally replaces `accessToken` with
a freshly pasted Bearer token.

To reuse the Auth0 entries already saved for a GuideSync project and replace
only its short-lived `accessToken`, run from the GuideSync directory:

```bash
make ui-auth-json PROJECT=Ardor
```

Paste a fresh Bearer token into the hidden terminal prompt, or leave it empty
to keep the saved value. The standalone Python helper reads the project's
existing authorization JSON from the local Compose Postgres database, replaces
`accessToken`, validates all JWT expiry timestamps, and copies the result to the
macOS clipboard. It does not control or inspect the browser.

Then paste the copied JSON into the GuideSync project field
   **UI authorization value**, with storage type **localStorage**, and save.

One Bearer token cannot be used to derive Auth0 access and ID tokens. When the
saved Auth0 entries expire, refresh the full JSON once by running
`export_local_storage_auth.js` as a DevTools Snippet on the authenticated UI.

The helper fails for expired JWTs and warns when a token has less than five
minutes remaining. The token is read without terminal echo and is not passed as
a process argument. Treat the copied JSON as a secret and do not commit it or
save it in logs.
