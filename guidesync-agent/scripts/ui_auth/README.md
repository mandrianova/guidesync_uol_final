# UI authorization export

`export_local_storage_auth.js` builds the JSON expected by GuideSync's
**UI authorization value** field. It reads Auth0 SPA cache entries from the
currently authenticated product UI and optionally replaces `accessToken` with
a freshly pasted Bearer token.

1. Open the authenticated product UI, for example `https://console.ardor.cloud`.
2. Open DevTools → **Sources** → **Snippets** and create a snippet.
3. Paste the contents of `export_local_storage_auth.js` and run it.
4. Paste a fresh Bearer token into the prompt, or leave it empty to use the
   current `accessToken` from localStorage.
5. Paste the copied JSON into the GuideSync project field
   **UI authorization value**, with storage type **localStorage**, and save.

The script fails for expired JWTs and warns when a token has less than five
minutes remaining. It never sends authorization data over the network. Treat
the copied JSON as a secret and do not commit it or save it in logs.
