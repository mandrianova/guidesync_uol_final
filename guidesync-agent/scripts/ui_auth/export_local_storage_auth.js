(() => {
  const AUTH0_PREFIX = "@@auth0spajs@@";
  const EXPIRY_WARNING_SECONDS = 5 * 60;

  const enteredToken = window.prompt(
    "Fresh accessToken (Bearer prefix is accepted). Leave empty to use the current localStorage value."
  );
  if (enteredToken === null) {
    console.info("GuideSync UI authorization export cancelled.");
    return;
  }

  const accessToken = (
    enteredToken.trim() || window.localStorage.getItem("accessToken") || ""
  ).replace(/^Bearer\s+/i, "");
  if (!accessToken) {
    throw new Error("No accessToken was provided or found in localStorage.");
  }

  const auth0Keys = Object.keys(window.localStorage).filter((key) =>
    key.startsWith(AUTH0_PREFIX)
  );
  if (auth0Keys.length === 0) {
    throw new Error(
      "No Auth0 SPA cache entries were found. Run this script on the authenticated product UI origin."
    );
  }

  const authorization = { accessToken };
  for (const key of auth0Keys) {
    const value = window.localStorage.getItem(key);
    if (value !== null) {
      authorization[key] = value;
    }
  }

  function jwtExpiration(token) {
    const parts = token.split(".");
    if (parts.length !== 3) {
      return null;
    }
    try {
      const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
      const padded = payload.padEnd(Math.ceil(payload.length / 4) * 4, "=");
      const bytes = Uint8Array.from(window.atob(padded), (character) =>
        character.charCodeAt(0)
      );
      const claims = JSON.parse(new TextDecoder().decode(bytes));
      return typeof claims.exp === "number" ? claims.exp : null;
    } catch {
      return null;
    }
  }

  const expirations = [{ source: "accessToken", expiresAt: jwtExpiration(accessToken) }];
  for (const key of auth0Keys) {
    try {
      const cacheEntry = JSON.parse(authorization[key]);
      const cachedToken = cacheEntry?.body?.access_token || cacheEntry?.id_token;
      if (cachedToken) {
        expirations.push({ source: key, expiresAt: jwtExpiration(cachedToken) });
      }
    } catch {
      console.warn(`Auth0 cache entry is not valid JSON: ${key}`);
    }
  }

  const now = Math.floor(Date.now() / 1000);
  for (const item of expirations) {
    if (item.expiresAt === null) {
      console.warn(`Could not read JWT expiration: ${item.source}`);
    } else if (item.expiresAt <= now) {
      throw new Error(`JWT is already expired: ${item.source}`);
    } else if (item.expiresAt - now < EXPIRY_WARNING_SECONDS) {
      console.warn(`JWT expires in less than 5 minutes: ${item.source}`);
    }
  }

  const output = JSON.stringify(authorization);
  globalThis.__GUIDESYNC_UI_AUTH_JSON__ = output;

  if (typeof copy === "function") {
    copy(output);
    console.info(
      `Copied GuideSync UI authorization JSON with ${Object.keys(authorization).length} keys.`
    );
  } else {
    void navigator.clipboard.writeText(output).then(
      () =>
        console.info(
          `Copied GuideSync UI authorization JSON with ${Object.keys(authorization).length} keys.`
        ),
      () =>
        console.info(
          "Clipboard access failed. Run copy(__GUIDESYNC_UI_AUTH_JSON__) in DevTools."
        )
    );
  }

  console.table(
    expirations.map((item) => ({
      source: item.source,
      expiresAt: item.expiresAt
        ? new Date(item.expiresAt * 1000).toISOString()
        : "unknown"
    }))
  );
})();
