"""Keep tools/get_tokens.py out of everything a user installs.

The script mints Daze tokens from a username and password. It is meant
to run on the operator's own machine and nowhere else -- the integration
is built to hold tokens only, and a password-handling script sitting on
a Home Assistant host is the thing that design exists to prevent.

Three separate mechanisms keep it off that host, and this suite holds
all three in place, because each fails silently on its own:

    1. HACS installs custom_components/<domain> only. A file that
       appears under custom_components/ is installed on every user's
       host, whatever it was written for.
    2. GitHub builds its release source archives with git archive, which
       honours export-ignore in .gitattributes. Without that rule the
       script ships in every release tarball.
    3. hacs.json must not set zip_release (or filename, or
       content_in_root), any of which changes what HACS packages and
       could reintroduce paths this suite checks are absent.

The assertion that matters is the second one, and it is made against
git archive's real output rather than by reading .gitattributes and
believing it. A rule can be present and not take effect -- a pattern
that does not match, a rule listed under a path git does not apply it
to -- and rules.md section 3 is a long record of tests in this
repository that passed by checking the description of a thing instead
of the thing. The .gitattributes content is checked too, but as a
second, narrower assertion: it names which rule went missing when the
archive check fails, which the archive output alone cannot say.

Note what export-ignore does not do, since a reader could reasonably
over-read this suite: the script stays in the repository, stays visible
on GitHub, and still arrives with a git clone. These checks are about
the artefact people install, not about concealment.

Run with pytest, or standalone:

    python3 tests/test_release_excludes_tools.py
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The script this suite exists for. Named rather than globbed: a glob
# would quietly start passing if the file were renamed, which is the
# moment the protection is most likely to have been lost.
SCRIPT_NAME = "get_tokens.py"
SCRIPT_PATH = "tools/get_tokens.py"


def _archive_bytes() -> bytes:
    """Return the release source archive git would build for HEAD.

    Never skips. A suite that skips when git is missing is a suite that
    reports success having checked nothing, which is rules.md section
    3's defect moved into the runner -- and the only thing checked here
    is a property of the git tree, so there is no meaningful run
    without git. Every environment this gate runs in -- the repository
    itself and CI -- has git.

    Binary, not text: this is a tar stream, and decoding it as UTF-8
    corrupts it.
    """
    try:
        result = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as err:  # git not installed
        raise AssertionError(
            "git is not available, so the release-archive contents cannot "
            "be checked. This is a failure rather than a skip on purpose: "
            "the check would otherwise report success having verified "
            "nothing."
        ) from err
    except subprocess.CalledProcessError as err:
        raise AssertionError(
            "git archive failed with status "
            f"{err.returncode}: {err.stderr.decode('utf-8', 'replace')[:300]}"
        ) from err

    return result.stdout


def _archive_paths() -> list[str]:
    """Every path git archive would put in a release tarball.

    Read with tarfile rather than by piping to tar, so the check does
    not depend on a second external program being present. `git archive
    HEAD | tar -t` at a shell is the same listing.
    """
    with tarfile.open(fileobj=io.BytesIO(_archive_bytes())) as archive:
        return archive.getnames()


# ------------------------------------------------------------------
# 1. Not under custom_components/
# ------------------------------------------------------------------


def test_token_script_is_not_under_custom_components() -> None:
    """HACS installs custom_components/ -- so the script must not be in it.

    Checked by walking the directory rather than by asserting the
    script's intended path exists, because the failure this guards
    against is a copy appearing somewhere under custom_components/, at
    any depth, under any parent.
    """
    package = ROOT / "custom_components"
    offenders = [
        str(path.relative_to(ROOT))
        for path in package.rglob(SCRIPT_NAME)
    ]

    assert not offenders, (
        f"{SCRIPT_NAME} is under custom_components/, which HACS installs "
        f"on every user's Home Assistant host: {offenders}. It handles a "
        "Daze username and password and must only ever run on the "
        "operator's own machine."
    )


def test_nothing_under_custom_components_prompts_for_a_password() -> None:
    """The narrower rule behind the path check.

    Moving the file is one way to break the design constraint; writing
    a second password prompt straight into the integration is another,
    and the path check above would not see it. The integration receives
    tokens only -- nothing it installs should ever ask for a password.
    """
    package = ROOT / "custom_components"
    offenders = []

    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "getpass" in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, (
        "a file installed on the Home Assistant host reads a password "
        f"interactively: {offenders}. Home Assistant must receive tokens "
        "only, never Daze credentials."
    )


# ------------------------------------------------------------------
# 2. Not in the release source archive
# ------------------------------------------------------------------


def test_release_archive_excludes_the_token_script() -> None:
    """The check this suite exists for, made against git's real output."""
    paths = _archive_paths()

    offenders = [path for path in paths if path.endswith(SCRIPT_NAME)]

    assert not offenders, (
        f"{SCRIPT_PATH} is in the release source archive GitHub builds "
        f"for a release: {offenders}. Add an export-ignore rule for it "
        "in .gitattributes."
    )


def test_release_archive_excludes_the_whole_tools_directory() -> None:
    """Broader than the rule above, and the reason it is phrased so.

    Several scripts under tools/ write to a charger. None of them
    belongs in something a user downloads and runs, so the directory is
    excluded wholesale rather than one file at a time -- which also
    means a tool added later is covered without anyone remembering to
    extend a list.
    """
    offenders = [
        path for path in _archive_paths() if path.startswith("tools/")
    ]

    assert not offenders, (
        "the release source archive contains files from tools/: "
        f"{offenders[:10]}. The directory is meant to be excluded "
        "wholesale by .gitattributes."
    )


def test_release_archive_still_contains_the_integration() -> None:
    """The control for the two assertions above.

    An export-ignore rule that matched too much, an archive command
    that produced nothing, or a tar invocation returning an empty list
    would satisfy every 'is absent' check in this file. Asserting that
    what should ship does ship is what separates "excluded correctly"
    from "excluded everything".
    """
    paths = _archive_paths()

    assert "custom_components/daze/manifest.json" in paths, (
        "the release source archive does not contain the integration's "
        "manifest, so the archive or its export-ignore rules exclude far "
        "more than intended. Archive listed "
        f"{len(paths)} path(s)."
    )


# ------------------------------------------------------------------
# 3. The rules that produce the above
# ------------------------------------------------------------------


def test_gitattributes_carries_the_export_ignore_rule() -> None:
    """Names which rule went missing when the archive check fails.

    Deliberately a weaker assertion than the archive checks, and kept
    only for that diagnostic value: the presence of a line in
    .gitattributes is not evidence that git applies it.
    """
    attributes = ROOT / ".gitattributes"

    assert attributes.is_file(), (
        ".gitattributes is missing, so nothing keeps tools/ out of the "
        "release source archives GitHub builds with git archive."
    )

    text = attributes.read_text(encoding="utf-8")
    rules = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert any(
        rule.startswith("tools/") and "export-ignore" in rule
        for rule in rules
    ), (
        "no export-ignore rule for tools/ in .gitattributes. Found: "
        f"{rules}"
    )


def test_hacs_json_does_not_repackage_the_repository() -> None:
    """HACS must keep installing custom_components/daze and nothing else.

    zip_release makes HACS install a release asset instead of the
    directory, and content_in_root changes which directory that is.
    Either would move the boundary this suite's first check relies on,
    and neither would fail any other test here.
    """
    config = json.loads(
        (ROOT / "hacs.json").read_text(encoding="utf-8")
    )

    for key in ("zip_release", "filename", "content_in_root"):
        assert key not in config, (
            f"hacs.json sets {key!r}, which changes what HACS installs. "
            "The check that the token script is not under "
            "custom_components/ assumes HACS installs that directory and "
            "nothing else."
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
