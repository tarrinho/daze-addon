#!/usr/bin/env python3
"""Mint Daze access and refresh tokens from a username and password.

Run this on your own machine. Never install it on the Home Assistant
host, and never give Home Assistant your Daze username or password —
the integration is built to hold tokens only, and this script exists so
that stays true. Paste the two tokens it prints into Home Assistant's
re-authentication dialog.

The script is a standalone tool. It is not imported by the integration,
it is not installed by HACS (which only installs custom_components/daze),
and .gitattributes keeps it out of the release source archives.

Usage:

    python3 tools/get_tokens.py

The username and password are read from hidden prompts on stdin. They
are never accepted as command-line arguments (visible in ``ps`` and in
shell history) or as environment variables, never written to disk, and
never printed back. Nothing is logged.

Before printing anything, three checks run against the freshly minted
tokens, because a token that Cognito issues is not necessarily a token
the Daze API accepts, and a refresh token that fails does so about an
hour later, inside Home Assistant, looking unrelated:

    1. Cognito GetUser accepts the access token.
    2. A real Daze API call succeeds with it.
    3. The refresh token is accepted by the hosted-UI token endpoint,
       which is the endpoint the integration refreshes against.

If any check fails, the script says which one and prints no tokens.

Exit codes:
    0 - all three checks passed, tokens printed
    1 - authentication rejected (username or password)
    2 - the pool requires a challenge this script cannot complete
        (MFA, or a forced password change)
    3 - tokens were issued but a self-check failed; none printed
    4 - network or unexpected error
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# Mirrors custom_components/daze/const.py
API_BASE_URL = "https://webapi.dazeservice.com/v3"
COGNITO_BASE_URL = "https://daze.auth.eu-central-1.amazoncognito.com"
COGNITO_IDP_URL = "https://cognito-idp.eu-central-1.amazonaws.com/"
CLIENT_ID = "4m0rp7oqarbrc3hn67ivvonba8"
REDIRECT_URI = "https://webportal.dazeservice.com/authentication/callback"

INITIATE_AUTH_TARGET = "AWSCognitoIdentityProviderService.InitiateAuth"
GET_USER_TARGET = "AWSCognitoIdentityProviderService.GetUser"
AMZ_JSON = "application/x-amz-json-1.1"

TIMEOUT = 30

# Cognito replies to InitiateAuth with one of these instead of tokens
# when the account needs something more than a password. None of them
# can be completed without extra input this script deliberately does
# not collect, so each is explained and exited on rather than guessed
# at.
CHALLENGE_HELP = {
    "SMS_MFA": (
        "The account has SMS multi-factor authentication enabled. This "
        "script cannot complete it. Sign in at "
        "https://webportal.dazeservice.com and copy the tokens out of "
        "the browser instead — tools/check_daze_tokens.py documents "
        "where to find them."
    ),
    "SOFTWARE_TOKEN_MFA": (
        "The account has app-based (TOTP) multi-factor authentication "
        "enabled. This script cannot complete it. Sign in at "
        "https://webportal.dazeservice.com and copy the tokens out of "
        "the browser instead."
    ),
    "SELECT_MFA_TYPE": (
        "The account has more than one multi-factor method enabled and "
        "Cognito is asking which to use. This script cannot complete "
        "that. Sign in at https://webportal.dazeservice.com instead."
    ),
    "MFA_SETUP": (
        "The pool requires multi-factor authentication to be set up "
        "before sign-in can complete. Do that at "
        "https://webportal.dazeservice.com first."
    ),
    "NEW_PASSWORD_REQUIRED": (
        "The account must change its password before it can sign in. "
        "Do that at https://webportal.dazeservice.com first, then run "
        "this script again."
    ),
    "DEVICE_SRP_AUTH": (
        "The pool requires device-level SRP authentication, which this "
        "script does not implement. Sign in at "
        "https://webportal.dazeservice.com instead."
    ),
    "PASSWORD_VERIFIER": (
        "The pool answered with an SRP challenge, which means plain "
        "password authentication is not usable for this account. Sign "
        "in at https://webportal.dazeservice.com instead."
    ),
}


def _send(request: urllib.request.Request) -> tuple[int, dict]:
    """Send a request and return (status, parsed body).

    A non-2xx reply is a result here rather than an exception: Cognito
    and the Daze API both describe their failures in the body, and the
    caller needs to read them.
    """
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", "replace")
        status = err.code
    except urllib.error.URLError as err:
        print(f"Network error: {err.reason}", file=sys.stderr)
        raise SystemExit(4) from err

    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {}

    return status, body if isinstance(body, dict) else {}


def _post_amz(target: str, payload: dict) -> tuple[int, dict]:
    """POST a Cognito user pool API operation."""
    request = urllib.request.Request(
        COGNITO_IDP_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": AMZ_JSON, "X-Amz-Target": target},
        method="POST",
    )
    return _send(request)


def _describe_error(body: dict) -> str:
    """Summarise a Cognito error without echoing the whole body.

    Only the two fields Cognito uses to name a failure are read. The
    body is not printed wholesale, so nothing that was sent can come
    back out through an error path.
    """
    kind = str(body.get("__type", "")).split("#")[-1] or "unknown error"
    message = str(body.get("message", "")).strip()
    return f"{kind}: {message}" if message else kind


def _authenticate(username: str, password: str) -> dict:
    """Exchange a username and password for tokens.

    Returns the AuthenticationResult dict. Exits on anything else.
    """
    status, body = _post_amz(
        INITIATE_AUTH_TARGET,
        {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": CLIENT_ID,
            "AuthParameters": {"USERNAME": username, "PASSWORD": password},
        },
    )

    if status == 200 and "AuthenticationResult" in body:
        return body["AuthenticationResult"]

    # A challenge is a successful request that cannot be finished here.
    challenge = body.get("ChallengeName")
    if challenge:
        print(f"\nCognito asked for a further step: {challenge}")
        print(CHALLENGE_HELP.get(
            challenge,
            "This script cannot complete that step. Sign in at "
            "https://webportal.dazeservice.com instead.",
        ))
        raise SystemExit(2)

    kind = str(body.get("__type", ""))

    if "NotAuthorizedException" in kind:
        print("\nAuthentication was rejected.")
        print(
            "Cognito returns the same message for a wrong username and a "
            "wrong password, because this pool has user-existence errors "
            "suppressed. Check both. Note that the username prompt is "
            "hidden, so a typo there looks identical to a bad password."
        )
        raise SystemExit(1)

    if "UserNotConfirmedException" in kind:
        print("\nThe account exists but has never been confirmed.")
        print("Confirm it at https://webportal.dazeservice.com first.")
        raise SystemExit(1)

    if "PasswordResetRequiredException" in kind:
        print("\nThe account requires a password reset before sign-in.")
        print("Reset it at https://webportal.dazeservice.com first.")
        raise SystemExit(1)

    if "InvalidParameterException" in kind and "USER_PASSWORD_AUTH" in str(
        body.get("message", "")
    ):
        print(
            "\nThe Daze app client no longer permits plain password "
            "authentication, so this script cannot mint tokens any more."
        )
        print(
            "Sign in at https://webportal.dazeservice.com and copy the "
            "tokens out of the browser instead."
        )
        raise SystemExit(2)

    print(f"\nAuthentication failed (HTTP {status}): {_describe_error(body)}")
    raise SystemExit(1)


def _check_get_user(access_token: str) -> str:
    """Check 1 — Cognito accepts the access token. Returns the email."""
    status, body = _post_amz(GET_USER_TARGET, {"AccessToken": access_token})

    if status != 200:
        print(
            "Check 1 failed — Cognito GetUser rejected the new access "
            f"token (HTTP {status}): {_describe_error(body)}"
        )
        raise SystemExit(3)

    email = ""
    for attribute in body.get("UserAttributes", []):
        if isinstance(attribute, dict) and attribute.get("Name") == "email":
            email = str(attribute.get("Value", ""))
            break

    if not email:
        print(
            "Check 1 failed — GetUser accepted the token but reported no "
            "email address, which the Daze API needs to look up networks."
        )
        raise SystemExit(3)

    print("Check 1 passed — Cognito accepts the access token.")
    return email


def _check_daze_api(access_token: str, email: str) -> None:
    """Check 2 — the Daze API accepts the access token.

    This is the check worth having. Tokens minted here carry the
    'aws.cognito.signin.user.admin' scope rather than the
    'daze.api/daze.api' scope the hosted-UI flow issues, and whether
    the Daze API cares has never been established. Calling the first
    endpoint the config flow calls settles it before the token ever
    reaches Home Assistant.
    """
    url = (
        f"{API_BASE_URL}/users/{urllib.parse.quote(email)}"
        "/networks?includeStats=true"
    )
    request = urllib.request.Request(
        url,
        headers={"authorization": f"Bearer {access_token}"},
        method="GET",
    )
    status, _body = _send(request)

    if status != 200:
        print(
            f"Check 2 failed — the Daze API rejected the access token "
            f"(HTTP {status})."
        )
        if status in (401, 403):
            print(
                "That status means the token authenticates to Cognito but "
                "is not accepted by the Daze API, most likely because a "
                "password-authentication token does not carry the "
                "'daze.api/daze.api' scope the hosted-UI flow issues. If "
                "so, tokens have to be copied out of the web portal "
                "instead and this script cannot be used."
            )
        raise SystemExit(3)

    print("Check 2 passed — the Daze API accepts the access token.")


def _check_refresh(refresh_token: str) -> None:
    """Check 3 — the hosted-UI token endpoint accepts the refresh token.

    The integration refreshes against COGNITO_BASE_URL/oauth2/token,
    which is a different surface from the user pool API that issued
    these tokens. If it rejects them the integration does not fail at
    setup, it fails about an hour later on the first refresh, which is
    far harder to connect back to here.

    The refreshed access token is discarded. Cognito does not invalidate
    a refresh token by using it, so this costs nothing, and printing the
    token that checks 1 and 2 actually validated is worth more than
    printing one that is a few seconds newer.
    """
    request = urllib.request.Request(
        f"{COGNITO_BASE_URL}/oauth2/token",
        data=urllib.parse.urlencode(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        ).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
        },
        method="POST",
    )
    status, body = _send(request)

    if status != 200 or "access_token" not in body:
        error = str(body.get("error", "")) or _describe_error(body)
        print(
            f"Check 3 failed — the token endpoint the integration "
            f"refreshes against rejected the new refresh token "
            f"(HTTP {status}): {error}"
        )
        print(
            "Setup in Home Assistant would succeed and then fail about an "
            "hour later. Tokens are not printed for that reason."
        )
        raise SystemExit(3)

    print("Check 3 passed — the refresh token works where it has to.")


def main() -> int:
    """Prompt, authenticate, verify, then print the tokens."""
    if len(sys.argv) > 1:
        print(
            "This script takes no arguments. The password is read from a "
            "hidden prompt so it cannot appear in 'ps' output or in shell "
            "history, and it is not read from the environment either.",
            file=sys.stderr,
        )
        return 4

    print(__doc__.split("Usage:")[0].strip())
    print()
    print("Run this on your own machine, not on the Home Assistant host.")
    print()

    username = getpass.getpass("Daze username/email (hidden): ").strip()
    password = getpass.getpass("Daze password (hidden): ")

    if not username or not password:
        print("\nBoth a username and a password are required.")
        return 1

    print("\nAuthenticating...")
    result = _authenticate(username, password)

    # Drop the password as soon as it is no longer needed. CPython makes
    # no promise about when the string leaves memory, so this is tidiness
    # rather than a guarantee.
    del password

    access_token = result.get("AccessToken", "")
    refresh_token = result.get("RefreshToken", "")

    if not access_token or not refresh_token:
        print(
            "Cognito returned a success without both tokens, which the "
            "integration needs. Nothing to print."
        )
        return 3

    print("Tokens issued. Verifying them before printing...\n")

    email = _check_get_user(access_token)
    _check_daze_api(access_token, email)
    _check_refresh(refresh_token)

    expires_in = result.get("ExpiresIn")
    print("\nAll three checks passed.\n")
    print("Paste these into Home Assistant: Settings -> Devices & services")
    print("-> Daze -> reconfigure/re-authenticate.\n")
    print(f"Access token:\n{access_token}\n")
    print(f"Refresh token:\n{refresh_token}\n")
    if isinstance(expires_in, int):
        print(
            f"The access token expires in {expires_in} seconds; the "
            "integration refreshes it from the refresh token after that."
        )
    print(
        "Neither token was written to disk. Clear your terminal scrollback "
        "when you are done — a refresh token is a credential and lives far "
        "longer than the access token."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
