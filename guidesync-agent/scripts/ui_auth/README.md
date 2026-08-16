# UI authorization export

`export_local_storage_auth.js` builds the JSON expected by GuideSync's
**UI authorization value** field from the currently authenticated product UI.

To refresh the two Auth0 entries already saved for a GuideSync project, run
from the GuideSync directory:

```bash
make ui-auth-json PROJECT=Ardor
```

Paste the JWT from `body.access_token` of the
`default::openid profile email` entry, then the JWT from `id_token` of the
`@@user@@` entry. The inputs are hidden. The helper updates both Auth0 cache
entries directly in local Compose Postgres and removes the obsolete standalone
`accessToken` key. It does not control or inspect the browser.

The helper rejects expired JWTs. The tokens are read without terminal echo and
are not passed as process arguments. Do not commit them or save them in logs.
