"""Drive tools/get_tokens.py against a stubbed Cognito and Daze API.

The script exchanges a Daze username and password for tokens, and the
whole design constraint it serves is that Home Assistant never receives
credentials. That makes two of its properties worth more than the rest,
and neither is visible by reading it:

    1. A failed self-check prints no tokens. The script verifies the
       tokens three ways before printing them, and a verification step
       that reports a problem and then prints anyway is worse than no
       verification, because it reads as a guarantee.
    2. Credentials never leave the process. Not through an argument,
       not through the environment, not to disk, not into a log, and
       not back out through an error path echoing a request body.

The real module is imported and its real functions are called, with
urllib.request.urlopen replaced by a router that answers as Cognito and
the Daze API do. rules.md section 3 records what happens otherwise: two
suites in this repository re-implemented the code they claimed to test
and went on passing through every regression in the real thing.

Network access: none. Every test here runs against the stub. The one
thing these tests cannot establish is whether the real Daze API accepts
a password-authentication token at all -- that needs a real account,
and is noted in the README rather than faked here.

Run with pytest, or standalone:

    python3 tests/test_qa_get_tokens.py
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import re
import sys
import types
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Self

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "get_tokens.py"
PACKAGE_DIR = ROOT / "custom_components" / "daze"


def _load_script() -> types.ModuleType:
    """Import tools/get_tokens.py as a module.

    It is a standalone script rather than part of a package, so it is
    loaded by path. Importing it must not run anything: everything is
    behind main(), and a module-level side effect would fire here.
    """
    spec = importlib.util.spec_from_file_location("daze_get_tokens", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["daze_get_tokens"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


# ------------------------------------------------------------------
# A stubbed Cognito and Daze API
# ------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for an http.client.HTTPResponse."""

    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self._body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class Router:
    """Answers the four requests the script makes, and records them.

    Each entry is (status, body). A status outside 2xx is raised as an
    HTTPError, which is how urllib really reports one -- the script's
    own _send catches it, and a stub that returned it as a normal
    response would skip that branch entirely.
    """

    def __init__(self) -> None:
        self.initiate_auth: tuple[int, Any] = (
            200,
            {
                "AuthenticationResult": {
                    "AccessToken": "ACCESS-TOKEN-VALUE",
                    "RefreshToken": "REFRESH-TOKEN-VALUE",
                    "ExpiresIn": 3600,
                }
            },
        )
        self.get_user: tuple[int, Any] = (
            200,
            {
                "Username": "someone",
                "UserAttributes": [
                    {"Name": "email", "Value": "someone@example.com"}
                ],
            },
        )
        self.daze_api: tuple[int, Any] = (200, [{"uid": "net-1"}])
        self.refresh: tuple[int, Any] = (
            200,
            {"access_token": "REFRESHED-ACCESS-TOKEN", "expires_in": 3600},
        )

        self.calls: list[str] = []
        self.sent_bodies: list[str] = []

    def __call__(
        self, request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        url = request.full_url
        target = request.get_header("X-amz-target", "")

        if request.data:
            self.sent_bodies.append(
                request.data.decode("utf-8", "replace")
            )

        if target.endswith("InitiateAuth"):
            self.calls.append("initiate_auth")
            status, body = self.initiate_auth
        elif target.endswith("GetUser"):
            self.calls.append("get_user")
            status, body = self.get_user
        elif "/oauth2/token" in url:
            self.calls.append("refresh")
            status, body = self.refresh
        elif url.startswith(script.API_BASE_URL):
            self.calls.append("daze_api")
            status, body = self.daze_api
        else:  # pragma: no cover - a request the script should not make
            raise AssertionError(f"unexpected request to {url}")

        if 200 <= status < 300:
            return _FakeResponse(status, body)

        raise urllib.error.HTTPError(
            url, status, "stubbed", {}, io.BytesIO(json.dumps(body).encode())
        )


def _run_main(
    router: Router,
    username: str = "someone@example.com",
    password: str = "correct-horse",
    argv: list[str] | None = None,
) -> tuple[int, str]:
    """Run the script's real main() against the router.

    Returns (exit code, everything printed to stdout). SystemExit is
    translated to a code so a test can assert on it without the runner
    exiting.
    """
    prompts = iter([username, password])

    real_urlopen = urllib.request.urlopen
    real_getpass = script.getpass.getpass
    real_argv = sys.argv

    urllib.request.urlopen = router  # type: ignore[assignment]
    script.getpass.getpass = lambda _prompt: next(prompts)
    sys.argv = argv if argv is not None else ["get_tokens.py"]

    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = script.main()
            except SystemExit as exit_called:
                code = int(exit_called.code or 0)
    finally:
        urllib.request.urlopen = real_urlopen  # type: ignore[assignment]
        script.getpass.getpass = real_getpass
        sys.argv = real_argv

    return code, out.getvalue()


# ------------------------------------------------------------------
# The constants are a copy, and copies drift
# ------------------------------------------------------------------


def test_endpoints_match_the_integration() -> None:
    """The script mirrors const.py, so it can go stale silently.

    rules.md section 2 has the precedent: a test file kept its own copy
    of models.py, the copy drifted from the real parser, and the tests
    asserted only what both versions satisfied. Here the stakes are
    higher than a stale test -- if Daze moves its app client or its API
    and const.py is updated, a script still pointing at the old one
    fails in a way that looks like a credential problem.
    """
    source = (PACKAGE_DIR / "const.py").read_text(encoding="utf-8")
    constants: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(
            node.value, ast.Constant
        ):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(
                    node.value.value, str
                ):
                    constants[target.id] = node.value.value

    mirrored = (
        "API_BASE_URL",
        "COGNITO_BASE_URL",
        "COGNITO_IDP_URL",
        "CLIENT_ID",
        "REDIRECT_URI",
        "GET_USER_TARGET",
    )

    for name in mirrored:
        assert name in constants, (
            f"{name} is no longer defined in const.py, so the copy in "
            "tools/get_tokens.py is pointing at something the "
            "integration has moved away from"
        )
        assert getattr(script, name) == constants[name], (
            f"tools/get_tokens.py has a stale {name}: it uses "
            f"{getattr(script, name)!r} and const.py now says "
            f"{constants[name]!r}"
        )


# ------------------------------------------------------------------
# Credentials must not leave the process
# ------------------------------------------------------------------


def test_the_script_refuses_command_line_arguments() -> None:
    """A password in argv is visible in ps and in shell history."""
    router = Router()
    code, output = _run_main(router, argv=["get_tokens.py", "someone"])

    assert code == 4, f"accepted an argument and exited {code}"
    assert router.calls == [], (
        "the script authenticated despite being given an argument"
    )
    assert "no arguments" in output.lower()


def test_the_password_is_never_printed() -> None:
    """Not on the happy path, and not on any failure path.

    The password is the one value in this process that has no business
    appearing anywhere, and an error path that echoes a request body
    would leak it -- InitiateAuth sends it in the body.
    """
    secret = "unmistakable-password-value"

    failures: dict[str, Router] = {}
    ok = Router()
    failures["success"] = ok

    rejected = Router()
    rejected.initiate_auth = (
        400,
        {
            "__type": "NotAuthorizedException",
            "message": "Incorrect username or password.",
        },
    )
    failures["rejected"] = rejected

    odd = Router()
    odd.initiate_auth = (
        400,
        {"__type": "SomethingNew", "message": "unrecognised"},
    )
    failures["unrecognised"] = odd

    for label, router in failures.items():
        _code, output = _run_main(router, password=secret)
        assert secret not in output, (
            f"the password appeared in the output on the {label} path"
        )


def test_no_credential_reaches_the_environment_or_disk() -> None:
    """Read the script's own source for the shapes that would do it.

    A behavioural test cannot prove a negative about every path, so
    this one is deliberately static: it looks for the specific
    mechanisms that would move a credential out of the process.
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))

    banned_calls = {"open", "input"}
    banned_attributes = {"getenv", "environ", "basicConfig"}
    found: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in banned_calls:
                found.append(func.id)
            if isinstance(func, ast.Attribute) and (
                func.attr in banned_attributes
            ):
                found.append(func.attr)
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            found.append("environ")

    assert not found, (
        "tools/get_tokens.py reads or writes somewhere a credential must "
        f"not go: {sorted(set(found))}. The password is read from a "
        "hidden prompt and held in memory only."
    )

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "logging" not in imported, (
        "the script imports logging; it is specified to log nothing"
    )
    assert "argparse" not in imported, (
        "the script imports argparse; it is specified to take no arguments"
    )
    assert "getpass" in imported, (
        "the script no longer reads its prompts through getpass, so the "
        "password would echo to the terminal"
    )


def test_the_password_goes_only_to_cognito_in_the_auth_request() -> None:
    """And in the plain-password flow, not an SRP one.

    If the flow name changed to an SRP variant the password would be
    sent where Cognito cannot use it, and the failure would read as bad
    credentials.
    """
    router = Router()
    secret = "another-distinct-password"
    _run_main(router, password=secret)

    carrying = [body for body in router.sent_bodies if secret in body]
    assert len(carrying) == 1, (
        f"the password was sent in {len(carrying)} requests; it belongs "
        "in exactly one, the InitiateAuth call"
    )

    payload = json.loads(carrying[0])
    assert payload["AuthFlow"] == "USER_PASSWORD_AUTH"
    assert payload["ClientId"] == script.CLIENT_ID
    assert payload["AuthParameters"]["PASSWORD"] == secret


# ------------------------------------------------------------------
# A failed check prints no tokens
# ------------------------------------------------------------------


def _assert_no_tokens(output: str) -> None:
    """Fail if either token value reached the output."""
    assert "ACCESS-TOKEN-VALUE" not in output, (
        "the access token was printed despite a failed check"
    )
    assert "REFRESH-TOKEN-VALUE" not in output, (
        "the refresh token was printed despite a failed check"
    )


def test_a_failed_get_user_check_prints_no_tokens() -> None:
    """Check 1 — Cognito itself rejects the new access token."""
    router = Router()
    router.get_user = (
        401,
        {"__type": "NotAuthorizedException", "message": "Invalid token"},
    )

    code, output = _run_main(router)

    assert code == 3, f"exited {code} rather than 3"
    assert "Check 1 failed" in output
    _assert_no_tokens(output)


def test_a_failed_daze_api_check_prints_no_tokens() -> None:
    """Check 2 — the scope question, and the one most likely to fire.

    A token minted from a password carries
    aws.cognito.signin.user.admin rather than the daze.api/daze.api
    scope the hosted-UI flow issues. If the Daze API requires the
    latter, this is where it shows.
    """
    router = Router()
    router.daze_api = (403, {"message": "Forbidden"})

    code, output = _run_main(router)

    assert code == 3, f"exited {code} rather than 3"
    assert "Check 2 failed" in output
    assert "scope" in output, (
        "a 403 from the Daze API should explain the scope difference, "
        "which is the likely cause and not otherwise guessable"
    )
    _assert_no_tokens(output)


def test_a_failed_refresh_check_prints_no_tokens() -> None:
    """Check 3 — the failure that would otherwise surface an hour later.

    The integration refreshes against the hosted-UI token endpoint,
    which is a different surface from the user pool API that issued
    these tokens. Setup would succeed and the integration would break
    later, looking unrelated to this script.
    """
    router = Router()
    router.refresh = (400, {"error": "invalid_grant"})

    code, output = _run_main(router)

    assert code == 3, f"exited {code} rather than 3"
    assert "Check 3 failed" in output
    _assert_no_tokens(output)


def test_tokens_missing_from_a_successful_reply_print_nothing() -> None:
    """A 200 carrying only one token is not a usable result."""
    router = Router()
    router.initiate_auth = (
        200,
        {"AuthenticationResult": {"AccessToken": "ACCESS-TOKEN-VALUE"}},
    )

    code, output = _run_main(router)

    assert code == 3, f"exited {code} rather than 3"
    _assert_no_tokens(output)


# ------------------------------------------------------------------
# Challenges are explained, not crashed through
# ------------------------------------------------------------------


def test_every_known_challenge_exits_cleanly_with_guidance() -> None:
    """MFA and a forced password change are the realistic ones.

    Each must explain itself and exit. A KeyError or an AttributeError
    here would read to the user as the script being broken rather than
    their account needing something.
    """
    for challenge in script.CHALLENGE_HELP:
        router = Router()
        router.initiate_auth = (
            200,
            {"ChallengeName": challenge, "Session": "opaque"},
        )

        code, output = _run_main(router)

        assert code == 2, (
            f"{challenge} exited {code} rather than 2"
        )
        assert challenge in output, (
            f"{challenge} was not named in the output"
        )
        assert "webportal.dazeservice.com" in output, (
            f"{challenge} did not point at the fallback route"
        )
        _assert_no_tokens(output)


def test_an_unknown_challenge_still_exits_cleanly() -> None:
    """Cognito may add one. A missing dict key must not crash.

    This is the test that would have caught a bare CHALLENGE_HELP[name]
    lookup, and the reason the script uses .get with a default.
    """
    router = Router()
    router.initiate_auth = (
        200,
        {"ChallengeName": "SOMETHING_ADDED_LATER", "Session": "opaque"},
    )

    code, output = _run_main(router)

    assert code == 2, f"exited {code} rather than 2"
    assert "SOMETHING_ADDED_LATER" in output
    _assert_no_tokens(output)


def test_rejected_credentials_exit_one_and_say_both_are_suspect() -> None:
    """The pool suppresses user-existence errors.

    So a wrong username and a wrong password give the identical
    message, and the username prompt is hidden. A user told only
    "incorrect" will retype the password repeatedly.
    """
    router = Router()
    router.initiate_auth = (
        400,
        {
            "__type": "NotAuthorizedException",
            "message": "Incorrect username or password.",
        },
    )

    code, output = _run_main(router)

    assert code == 1, f"exited {code} rather than 1"
    assert "username" in output.lower()
    assert router.calls == ["initiate_auth"], (
        f"kept going after a rejection: {router.calls}"
    )


def test_a_disabled_password_flow_is_reported_as_such() -> None:
    """If Daze turns USER_PASSWORD_AUTH off, the script is finished.

    That is a different situation from bad credentials and must not
    read as them, or the user will keep retyping a correct password.
    """
    router = Router()
    router.initiate_auth = (
        400,
        {
            "__type": "InvalidParameterException",
            "message": (
                "USER_PASSWORD_AUTH flow not enabled for this client"
            ),
        },
    )

    code, output = _run_main(router)

    assert code == 2, f"exited {code} rather than 2"
    assert "webportal.dazeservice.com" in output
    _assert_no_tokens(output)


# ------------------------------------------------------------------
# The happy path
# ------------------------------------------------------------------


def test_all_three_checks_run_before_anything_is_printed() -> None:
    """The ordering is the guarantee, not an implementation detail.

    A version that printed first and verified afterwards would satisfy
    every other test in this file.
    """
    router = Router()
    code, output = _run_main(router)

    assert code == 0, f"exited {code}: {output}"
    assert router.calls == [
        "initiate_auth",
        "get_user",
        "daze_api",
        "refresh",
    ], f"calls were {router.calls}"

    for marker in ("Check 1 passed", "Check 2 passed", "Check 3 passed"):
        assert marker in output, f"{marker!r} missing from the output"

    checks_end = output.index("Check 3 passed")
    assert output.index("ACCESS-TOKEN-VALUE") > checks_end, (
        "the access token was printed before the last check completed"
    )


def test_the_printed_tokens_are_the_ones_that_were_verified() -> None:
    """Not the fresher pair the refresh check produces.

    The refresh returns a newer access token, and printing it would
    hand the user a value that checks 1 and 2 never tested. Seconds of
    extra lifetime are not worth an unverified token.
    """
    router = Router()
    _code, output = _run_main(router)

    assert "ACCESS-TOKEN-VALUE" in output
    assert "REFRESH-TOKEN-VALUE" in output
    assert "REFRESHED-ACCESS-TOKEN" not in output, (
        "the token produced by the refresh check was printed instead of "
        "the one that checks 1 and 2 validated"
    )


def test_the_refresh_check_uses_the_endpoint_the_integration_uses() -> None:
    """Checking the wrong endpoint would prove nothing.

    The point of check 3 is that the user pool API and the hosted-UI
    token endpoint are different surfaces. Verifying against the one
    that issued the tokens would always pass and would catch nothing.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'f"{COGNITO_BASE_URL}/oauth2/token"' in source, (
        "check 3 no longer posts to the hosted-UI token endpoint, which "
        "is the one custom_components/daze/api/auth.py refreshes against"
    )

    integration = (PACKAGE_DIR / "api" / "auth.py").read_text(
        encoding="utf-8"
    )
    assert 'f"{COGNITO_BASE_URL}/oauth2/token"' in integration, (
        "the integration no longer refreshes against that endpoint, so "
        "check 3 is now verifying the wrong thing"
    )


def test_the_user_is_told_where_to_paste_the_tokens() -> None:
    """The script's output is the handover to Home Assistant."""
    router = Router()
    _code, output = _run_main(router)

    assert "Devices & services" in output
    assert "scrollback" in output, (
        "the user is not told to clear the terminal, where a refresh "
        "token otherwise sits in plain view"
    )


def test_a_network_failure_exits_four_rather_than_crashing() -> None:
    """A URLError is the common case on a laptop, not a bug."""
    router = Router()

    def _boom(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        raise urllib.error.URLError("name resolution failed")

    real = urllib.request.urlopen
    real_getpass = script.getpass.getpass
    real_argv = sys.argv
    prompts = iter(["someone@example.com", "password"])

    urllib.request.urlopen = _boom  # type: ignore[assignment]
    script.getpass.getpass = lambda _prompt: next(prompts)
    sys.argv = ["get_tokens.py"]

    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = script.main()
            except SystemExit as exit_called:
                code = int(exit_called.code or 0)
    finally:
        urllib.request.urlopen = real  # type: ignore[assignment]
        script.getpass.getpass = real_getpass
        sys.argv = real_argv

    assert code == 4, f"exited {code} rather than 4"
    assert router.calls == []


# ------------------------------------------------------------------
# The phone version
#
# tools/get_tokens.html does the same job from a browser, so it can be
# copied onto a phone and opened from local storage. It is a second
# implementation of the same protocol, which makes it a drift risk in
# exactly the way rules.md section 2 describes -- and unlike the Python
# script, it cannot be driven here, because there is no browser in this
# environment to run it in. So these tests check the properties that are
# true of the file itself: where it may send data, what it may load,
# what it must not keep, and whether its copy of the constants still
# matches.
# ------------------------------------------------------------------


HTML = ROOT / "tools" / "get_tokens.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _csp() -> str:
    """The Content-Security-Policy from the page's meta tag."""
    source = _html()
    match = re.search(
        r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"',
        source,
        re.IGNORECASE,
    )
    assert match, (
        "tools/get_tokens.html has no Content-Security-Policy meta tag. "
        "It is the control that stops code in this page from sending the "
        "password anywhere other than Daze."
    )
    return " ".join(match.group(1).split())


def test_the_page_may_only_talk_to_daze_and_cognito() -> None:
    """connect-src is the security control, not a formality.

    The page handles a password. If anything in it ever tried to send
    that password to a fourth host -- added deliberately, or pulled in
    by a careless edit -- this directive is what stops the request
    leaving the browser. Asserted against the hosts derived from
    const.py so the two cannot drift apart.
    """
    directives = {
        part.split()[0]: part.split()[1:]
        for part in _csp().split(";")
        if part.strip()
    }

    assert "connect-src" in directives, (
        "the page's CSP no longer restricts connect-src, so it may send "
        "the password to any host"
    )

    expected = {
        urllib.parse.urlparse(getattr(script, name)).netloc
        for name in ("API_BASE_URL", "COGNITO_BASE_URL", "COGNITO_IDP_URL")
    }
    allowed = {
        urllib.parse.urlparse(value).netloc
        for value in directives["connect-src"]
        if value.startswith("https://")
    }

    assert allowed == expected, (
        f"connect-src allows {sorted(allowed)} but the endpoints the page "
        f"actually needs are {sorted(expected)}. A host listed here and "
        "not needed is somewhere the password could be sent."
    )

    assert directives.get("default-src") == ["'none'"], (
        "default-src is not 'none', so the page may load external "
        "scripts, styles or images"
    )
    assert directives.get("form-action") == ["'none'"], (
        "form-action is not 'none', so a stray submit could post the "
        "credentials somewhere"
    )


def test_the_page_loads_nothing_from_a_third_party() -> None:
    """No CDN, no font, no analytics -- nothing.

    The reason this file is opened from local storage is that whoever
    serves the code sees the password. A single <script src> pointing at
    a CDN reintroduces exactly that party, and would do it quietly: the
    page would keep working.
    """
    source = _html()

    offenders = re.findall(
        r'(?:src|href)\s*=\s*"(?!#)([^"]*)"', source, re.IGNORECASE
    )
    remote = [
        value
        for value in offenders
        if value.startswith(("http://", "https://", "//"))
    ]

    assert not remote, (
        f"tools/get_tokens.html loads something remote: {remote}. Every "
        "asset must be inline so that opening the file locally really "
        "does mean nobody else supplies the code."
    )

    for pattern in ("@import", "url(http"):
        assert pattern not in source, (
            f"the page's CSS pulls in {pattern!r} from elsewhere"
        )


def test_the_page_keeps_nothing() -> None:
    """A stored password or token outlives the tab, and shouldn't.

    The script's equivalent is the static check on open() and environ.
    Here the storage surfaces are the browser's.
    """
    source = _html()
    banned = (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "showSaveFilePicker",
    )

    found = [name for name in banned if name in source]

    assert not found, (
        f"tools/get_tokens.html writes to browser storage: {found}. "
        "Nothing it handles may outlive the tab."
    )


def test_the_form_cannot_submit_anywhere() -> None:
    """Belt and braces with form-action 'none' in the CSP.

    A form with an action attribute would send the password as a
    request to that URL on a stray Enter press, before any script ran.
    """
    source = _html()
    forms = re.findall(r"<form\b[^>]*>", source, re.IGNORECASE)

    assert forms, "the page has no form, so these tests are checking nothing"
    for tag in forms:
        assert "action" not in tag.lower(), (
            f"a form declares an action, which can post the password: {tag}"
        )


def test_the_page_mirrors_the_integration_constants() -> None:
    """Same drift risk as the Python script, same check.

    A third copy of these values now exists. If Daze moves its app
    client, a stale copy here fails in a way that reads to the user as a
    rejected password.
    """
    source = _html()

    for name in (
        "API_BASE_URL",
        "COGNITO_BASE_URL",
        "COGNITO_IDP_URL",
        "CLIENT_ID",
        "REDIRECT_URI",
    ):
        expected = getattr(script, name)
        match = re.search(
            rf'var\s+{name}\s*=\s*"([^"]*)"', source
        )
        assert match, f"{name} is no longer defined in get_tokens.html"
        assert match.group(1) == expected, (
            f"get_tokens.html has a stale {name}: {match.group(1)!r} "
            f"against {expected!r} in the integration"
        )


def test_the_page_uses_the_plain_password_flow() -> None:
    """And sends the password in that one request only."""
    source = _html()

    assert 'AuthFlow: "USER_PASSWORD_AUTH"' in source, (
        "the page no longer requests USER_PASSWORD_AUTH, so the password "
        "would be sent where Cognito cannot use it"
    )
    assert source.count("PASSWORD:") == 1, (
        "the password is referenced in more than one request payload; it "
        "belongs in the sign-in call and nowhere else"
    )


def test_the_page_explains_the_same_challenges_as_the_script() -> None:
    """The two must not diverge on what they can and cannot handle.

    A challenge the script explains and the page crashes on would send
    a user round in circles, and the page is the one they will reach
    for on a phone.
    """
    keys = set(
        re.findall(r"^\s{4}([A-Z_]+):$", _html(), re.MULTILINE)
    )

    assert keys == set(script.CHALLENGE_HELP), (
        "the page and the script disagree about which Cognito challenges "
        f"they explain. Page: {sorted(keys)}. Script: "
        f"{sorted(script.CHALLENGE_HELP)}."
    )


def test_the_page_never_builds_markup_from_a_server_reply() -> None:
    """Error text comes back from Cognito and is rendered to the user.

    textContent is safe with it; the HTML sinks are not, and the CSP
    allows inline script, so an injection would execute.

    Matched on actual use rather than on the bare word. The first
    version asserted ``"innerHTML" not in source`` and failed on the
    comment that says textContent is used *instead of* innerHTML --
    the same over-broad match that
    tests/test_release_excludes_tools.py records in its own docstring.
    Twice now, so it is worth stating as a habit: assert on the
    construct, not on the string that names it.
    """
    source = _html()

    sinks = re.findall(
        r"\.(innerHTML|outerHTML|insertAdjacentHTML)\b"
        r"|\b(innerHTML|outerHTML)\s*="
        r"|\bdocument\.write\b",
        source,
    )

    assert not sinks, (
        "the page writes markup rather than text somewhere. "
        "Server-supplied error text is rendered to the user here, so it "
        f"must go through textContent. Found: {sinks}"
    )

    assert "textContent" in source, (
        "the page no longer uses textContent at all, which means the "
        "check above is passing because nothing renders anything"
    )


def test_the_page_tells_the_user_not_to_host_it() -> None:
    """The one instruction the whole delivery choice rests on."""
    source = _html().lower()

    assert "local file" in source or "own storage" in source, (
        "the page does not tell the reader to open it from local storage "
        "rather than from a website, which is the reason it is a file "
        "rather than a hosted page"
    )
    assert "home assistant host" in source, (
        "the page does not warn against putting it on the Home Assistant "
        "host"
    )


def _main() -> int:
    """Run every test in this module and report results."""
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]

    failures = 0
    for test in tests:
        try:
            test()
        except Exception as err:  # noqa: BLE001 - standalone runner
            failures += 1
            print(f"FAIL {test.__name__}: {type(err).__name__}: {err}")
        else:
            print(f"ok   {test.__name__}")

    print(f"\n{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
