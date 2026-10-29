#!/usr/bin/env python3
"""Run every standalone test module and report a combined result.

The suites are written to run without pytest so they can be executed
on a machine that has nothing installed beyond Python and aiohttp,
which is the situation when checking a fix against a charger.

Usage:

    python3 tests/run_all.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# test_sensor.py is absent below because it has no _main() and so is
# driven by pytest alone. Registering it here without one would print
# "ok" with a blank summary and add 0 to the total — a suite reported as
# passing having run nothing.
#
# test_control.py was deleted rather than registered. Its 38 tests
# imported nothing from custom_components, so none of them could fail on
# a regression in the integration; test_entities.py covers the same
# behaviours against the real entities.
STANDALONE = (
    # First: a commit carrying a device identifier is the one failure
    # here that cannot be undone by a later commit. See rules.md
    # section 0, and the module's own docstring.
    "test_no_device_identifiers.py",
    # Second for the same reason as the first: a release that ships the
    # token-minting script puts a password-handling tool on every
    # user's Home Assistant host, and a published release asset is not
    # something a later commit takes back.
    "test_release_excludes_tools.py",
    "test_translations.py",
    "test_auth_getuser.py",
    "test_payload.py",
    "test_qa_invariants.py",
    "test_entities.py",
    "test_solar.py",
    "test_qa_solar_invariants.py",
    "test_solar_controller.py",
    "test_solar_sensor.py",
    "test_coordinator.py",
    "test_init_entry.py",
    "test_config_flow.py",
    "test_sensor_filtering.py",
    "test_diagnostics.py",
    "test_session.py",
)


def main() -> int:
    """Run each suite in turn and summarise."""
    total_passed = 0
    total_failed = 0
    failed_modules: list[str] = []

    for name in STANDALONE:
        path = TESTS_DIR / name
        if not path.exists():
            print(f"SKIP {name}: not found")
            continue

        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            check=False,  # a failing suite is a result, not an error
        )

        summary = ""
        for line in reversed(result.stdout.splitlines()):
            if "passed," in line:
                summary = line.strip()
                break

        status = "ok  " if result.returncode == 0 else "FAIL"
        print(f"{status} {name:28s} {summary}")

        if result.returncode != 0:
            failed_modules.append(name)
            for line in result.stdout.splitlines():
                if line.startswith("FAIL"):
                    print(f"       {line}")
            if result.stderr.strip():
                print(f"       stderr: {result.stderr.strip()[:300]}")

        # "28 passed, 0 failed" - strip the comma before matching.
        parts = summary.replace(",", "").split()
        if len(parts) >= 4 and parts[1] == "passed" and parts[3] == "failed":
            total_passed += int(parts[0])
            total_failed += int(parts[2])

    print()
    print(f"{total_passed} passed, {total_failed} failed "
          f"across {len(STANDALONE)} module(s)")

    if failed_modules:
        print(f"failing modules: {', '.join(failed_modules)}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
