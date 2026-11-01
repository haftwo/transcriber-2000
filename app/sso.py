"""Sign in with Microsoft (Entra ID, formerly Azure AD) using OpenID Connect.

Standard library only. Flow: authorization code + PKCE, with state and nonce kept in the
signed session cookie. The ID token comes straight from Microsoft's token endpoint over TLS,
authenticated with the client secret, so (per OpenID Connect Core 3.1.3.7) we check its claims
— issuer, audience, expiry, nonce — rather than its signature.
"""
import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

LOGIN_HOST = "https://login.microsoftonline.com"
SCOPES = "openid profile email"
CALLBACK_PATH = "/auth/microsoft/callback"
_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DOMAIN = re.compile(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")
_discovery_cache = {}  # tenant -> (fetched_at, config)


class SSOError(Exception):
    """Something went wrong signing in; the message is safe to show the user."""


def clean_tenant(tenant):
    """A specific directory only: its tenant ID (GUID) or a verified domain.
    'common', 'organizations' and 'consumers' would let any Microsoft account in."""
    tenant = (tenant or "").strip()
    if tenant.lower() in ("common", "organizations", "consumers"):
        raise ValueError("Use your own tenant ID or domain, not 'common', 'organizations' or 'consumers'")
    if tenant and not (_GUID.fullmatch(tenant) or _DOMAIN.fullmatch(tenant)):
        raise ValueError("Tenant should be a Directory (tenant) ID like 1234abcd-… or a domain like contoso.com")
    return tenant


def clean_client_id(cid):
    cid = (cid or "").strip()
    if cid and not _GUID.fullmatch(cid):
        raise ValueError("Client ID should be the Application (client) ID, like 1234abcd-…")
    return cid


def clean_domains(text):
    doms = [d.strip().lower().lstrip("@") for d in re.split(r"[,\s]+", text or "") if d.strip()]
    for d in doms:
        if not _DOMAIN.fullmatch(d):
            raise ValueError(f"'{d}' isn't a valid email domain")
    return ", ".join(doms)


def _get_json(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            msg = err.get("error_description") or err.get("error") or e.reason
        except (ValueError, OSError):
            msg = e.reason
        raise SSOError(f"Microsoft replied HTTP {e.code}: {str(msg).splitlines()[0][:300]}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SSOError(f"Can't reach Microsoft: {getattr(e, 'reason', e)}")


def discovery(tenant, fresh=False):
    """The tenant's OpenID configuration (endpoints and exact issuer). Cached for an hour."""
    hit = _discovery_cache.get(tenant)
    if hit and not fresh and time.time() - hit[0] < 3600:
        return hit[1]
    cfg = _get_json(f"{LOGIN_HOST}/{urllib.parse.quote(tenant)}/v2.0/.well-known/openid-configuration")
    if "authorization_endpoint" not in cfg or "issuer" not in cfg:
        raise SSOError("Microsoft didn't recognise that tenant")
    _discovery_cache[tenant] = (time.time(), cfg)
    return cfg


def check_credentials(tenant, client_id, secret):
    """Prove the tenant, client ID and secret work, without a user, by asking for an app-only
    token. Needs no API permissions. Returns the tenant's issuer."""
    cfg = discovery(tenant, fresh=True)
    _get_json(cfg["token_endpoint"], data=urllib.parse.urlencode({
        "client_id": client_id, "client_secret": secret, "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default"}).encode())
    return cfg["issuer"]


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def begin(settings, redirect_uri):
    """Returns (url to send the browser to, values to keep in the session until the callback)."""
    cfg = discovery(settings["sso_tenant_id"])
    state, nonce, verifier = _b64url(os.urandom(24)), _b64url(os.urandom(24)), _b64url(os.urandom(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    query = urllib.parse.urlencode({
        "client_id": settings["sso_client_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    pending = {"state": state, "nonce": nonce, "verifier": verifier,
               "redirect_uri": redirect_uri, "t": time.time()}
    return cfg["authorization_endpoint"] + "?" + query, pending


def _decode_claims(id_token):
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise SSOError("Microsoft sent back an ID token that couldn't be read")


def finish(settings, pending, code):
    """Swap the code for an ID token and check it. Returns the token's claims."""
    if time.time() - pending.get("t", 0) > 900:
        raise SSOError("The sign-in took too long. Please try again.")
    cfg = discovery(settings["sso_tenant_id"])
    form = urllib.parse.urlencode({
        "client_id": settings["sso_client_id"],
        "client_secret": settings["sso_client_secret"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending["redirect_uri"],
        "code_verifier": pending["verifier"],
        "scope": SCOPES,
    }).encode()
    tokens = _get_json(cfg["token_endpoint"], data=form)
    if "id_token" not in tokens:
        raise SSOError("Microsoft didn't return an ID token")
    claims = _decode_claims(tokens["id_token"])
    issuer = cfg["issuer"].replace("{tenantid}", str(claims.get("tid", "")))
    if claims.get("iss") != issuer:
        raise SSOError("That account isn't from the configured Microsoft tenant")
    aud = claims.get("aud")
    if aud != settings["sso_client_id"] and not (isinstance(aud, list) and settings["sso_client_id"] in aud):
        raise SSOError("The ID token was issued for a different app")
    now = time.time()
    if claims.get("exp", 0) < now - 300 or claims.get("nbf", 0) > now + 300:
        raise SSOError("The ID token has expired. Check the server's clock, then try again.")
    if claims.get("nonce") != pending["nonce"]:
        raise SSOError("The sign-in response didn't match this browser. Please try again.")
    if not claims.get("oid"):
        raise SSOError("Microsoft didn't say which account signed in")
    return claims


def username_for(claims):
    """The account's sign-in name (UPN or email), lower-case."""
    name = (claims.get("preferred_username") or claims.get("email") or claims.get("upn") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._@'+-]{2,100}", name):
        raise SSOError(f"The Microsoft account name '{name[:100]}' can't be used as a username here")
    return name
