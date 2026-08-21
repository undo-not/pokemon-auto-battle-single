from __future__ import annotations

import pytest

from champions_sim.core import canonical_hash
from champions_sim.grounding import (
    AndroidClientIdentityError,
    observe_android_client_build,
)
from champions_sim.grounding.android_client import (
    is_read_only_client_identity_service,
)


PACKAGE = "com.pokemon.champions"
BASE = "/data/app/~~fixture/com.pokemon.champions-fixture==/base.apk"
SPLIT = (
    "/data/app/~~fixture/com.pokemon.champions-fixture==/"
    "split_config.arm64_v8a.apk"
)
BASE_HASH = "1" * 64
SPLIT_HASH = "2" * 64


def _runner(service: str, max_bytes: int) -> bytes:
    assert max_bytes > 0
    responses = {
        f"exec:dumpsys package {PACKAGE}": (
            b"  versionCode=2026082101 minSdk=30 targetSdk=35\n"
            b"  versionName=1.0.0-test\n"
        ),
        f"exec:cmd package path {PACKAGE}": (
            f"package:{SPLIT}\npackage:{BASE}\n".encode()
        ),
        f"exec:sha256sum {BASE}": f"{BASE_HASH}  {BASE}\n".encode(),
        f"exec:sha256sum {SPLIT}": f"{SPLIT_HASH}  {SPLIT}\n".encode(),
    }
    return responses[service]


def test_client_build_binds_version_and_sorted_installed_apk_bytes() -> None:
    build = observe_android_client_build(PACKAGE, _runner)

    expected_entries = [
        {"name": "base.apk", "sha256": "sha256:" + BASE_HASH},
        {
            "name": "split_config.arm64_v8a.apk",
            "sha256": "sha256:" + SPLIT_HASH,
        },
    ]
    assert build.version_code == 2026082101
    assert build.version_name == "1.0.0-test"
    assert build.apk_count == 2
    assert build.apk_set_sha256 == "sha256:" + canonical_hash(
        {"apk_files": expected_entries}
    )


@pytest.mark.parametrize(
    "service",
    (
        f"exec:dumpsys package {PACKAGE}",
        f"exec:cmd package path {PACKAGE}",
        f"exec:sha256sum {BASE}",
    ),
)
def test_only_constrained_read_only_client_identity_services_are_allowed(
    service: str,
) -> None:
    assert is_read_only_client_identity_service(service)


@pytest.mark.parametrize(
    "service",
    (
        "exec:dumpsys package com.pokemon.champions;input tap 1 1",
        "exec:cmd package path com.pokemon.champions\ninput tap 1 1",
        "exec:sha256sum /data/app/../data/local/tmp/replaced.apk",
        "exec:sha256sum /sdcard/replaced.apk",
        "shell:input tap 1 1",
    ),
)
def test_client_identity_allowlist_rejects_injection_and_other_paths(
    service: str,
) -> None:
    assert not is_read_only_client_identity_service(service)


def test_client_build_rejects_ambiguous_version_and_misreported_hash_path() -> None:
    def ambiguous(service: str, max_bytes: int) -> bytes:
        if service.startswith("exec:dumpsys package "):
            return _runner(service, max_bytes) + b"  versionCode=2026082102\n"
        return _runner(service, max_bytes)

    with pytest.raises(AndroidClientIdentityError, match="unambiguous"):
        observe_android_client_build(PACKAGE, ambiguous)

    def wrong_hash_path(service: str, max_bytes: int) -> bytes:
        if service == f"exec:sha256sum {BASE}":
            return f"{BASE_HASH}  /data/app/other/base.apk\n".encode()
        return _runner(service, max_bytes)

    with pytest.raises(AndroidClientIdentityError, match="another path"):
        observe_android_client_build(PACKAGE, wrong_hash_path)
