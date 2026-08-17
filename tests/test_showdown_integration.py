from __future__ import annotations

import json
import os
import queue
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
import champions_sim.showdown.resolver as resolver_module

from champions_sim.core.canonical import canonical_hash, canonical_json
from champions_sim.showdown import (
    ShowdownBridgeError,
    ShowdownClient,
    ShowdownProcessError,
    ShowdownResolutionError,
    resolve_showdown,
)
from champions_sim.showdown.audit import _generation_seed

from showdown_fixtures import (
    legal_team,
    opponent_team_with_private_item,
    pixilate_team,
    sodium_seed,
    throat_chop_team,
)


ROOT = Path(__file__).resolve().parents[1]


pytestmark = pytest.mark.skipif(
    os.environ.get("SHOWDOWN_INTEGRATION") != "1",
    reason="set SHOWDOWN_INTEGRATION=1 after bootstrapping the pinned external Showdown build",
)


@pytest.fixture(scope="module")
def client() -> ShowdownClient:
    instance = ShowdownClient()
    yield instance
    instance.close()


def test_dependency_identity_and_champions_format_are_verified(client: ShowdownClient) -> None:
    resolved = client.resolved

    assert resolved.head == resolved.manifest.commit
    assert resolved.tree == resolved.manifest.tree
    assert resolved.build_fingerprint == resolved.manifest.build.fingerprint_sha256
    assert len(resolved.manifest_sha256) == 64
    assert client.default_format_id == "gen9championsbssregmb"


def test_manifest_ruleset_mismatch_fails_before_session_creation(
    client: ShowdownClient, tmp_path: Path
) -> None:
    document = json.loads(client.resolved.manifest.path.read_text(encoding="utf-8"))
    document["formats"][0]["ruleset"] = ["Flat Rules"]
    hostile = tmp_path / "manifest.json"
    hostile.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeError, match="format ruleset mismatch"):
        ShowdownClient(
            root=client.resolved.root,
            node_executable=client.resolved.node_executable,
            manifest_path=hostile,
        )


def test_manifest_effective_rule_table_mismatch_fails_before_session_creation(
    client: ShowdownClient, tmp_path: Path
) -> None:
    document = json.loads(client.resolved.manifest.path.read_text(encoding="utf-8"))
    document["formats"][0]["rule_table"].remove("speciesclause")
    hostile = tmp_path / "manifest.json"
    hostile.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeError, match="effective rule table mismatch"):
        ShowdownClient(
            root=client.resolved.root,
            node_executable=client.resolved.node_executable,
            manifest_path=hostile,
        )


def test_team_validation_comes_from_showdown(client: ShowdownClient) -> None:
    assert client.validate_team(legal_team()) == ()

    invalid = legal_team()[:-1]
    problems = client.validate_team(invalid)
    assert problems
    assert any("at least 6" in problem for problem in problems)

    hostile = legal_team()
    hostile[0]["invented_field"] = "ignored-by-upstream-packer"
    with pytest.raises(ShowdownBridgeError) as captured:
        client.validate_team(hostile)
    assert captured.value.code == "INVALID_REQUEST"

    with pytest.raises(ShowdownBridgeError) as captured:
        client.validate_team(legal_team(), format_id="gen9customgame")
    assert captured.value.code == "UNBOUND_FORMAT"


def test_bound_random_team_generation_is_closed_and_target_validated(
    client: ShowdownClient,
) -> None:
    seeds = [_generation_seed("integration-generator", index) for index in range(4)]

    candidates = client.generate_random_team_candidates(
        generation_format_id="gen9championsrandombattle",
        seeds=seeds,
    )

    assert len(candidates) == 4
    assert len({canonical_hash(candidate["team"]) for candidate in candidates}) == 4
    for index, candidate in enumerate(candidates):
        assert candidate["generation_seed"] == list(seeds[index])
        assert len(candidate["team"]) == 6
        assert not candidate["problems"]
        assert client.validate_team(candidate["team"]) == ()
    with pytest.raises(ValueError, match="team-generation binding"):
        client.generate_random_team_candidates(
            generation_format_id="gen9championsbssregmb",
            seeds=seeds,
        )
    with pytest.raises(ValueError, match="four integers"):
        client.generate_random_team_candidates(
            generation_format_id="gen9championsrandombattle",
            seeds=[(1, 2, 3)],
        )
    with pytest.raises(ValueError, match="not a battle binding"):
        client.create_session(
            session_id="wrong-purpose",
            seed=sodium_seed(),
            p1_name="Alpha",
            p1_team=legal_team(),
            p2_name="Beta",
            p2_team=legal_team(),
            format_id="gen9championsrandombattle",
        )


def test_random_battle_audit_decision_bound_fails_closed(
    client: ShowdownClient,
) -> None:
    from champions_sim.showdown.audit import (
        RandomBattleAuditError,
        run_random_battle_audit,
    )

    with pytest.raises(RandomBattleAuditError, match="exceeded 1 decisions"):
        run_random_battle_audit(client, max_decisions=1)


def test_accepted_choice_consumes_request_until_next_engine_request(
    client: ShowdownClient,
) -> None:
    session = client.create_session(
        session_id="request-consumption",
        seed=sodium_seed(71),
        p1_name="Alpha",
        p1_team=legal_team(),
        p2_name="Beta",
        p2_team=opponent_team_with_private_item(),
    )
    try:
        p1_choice = session.observe("p1").legal_actions[0]
        p2_choice = session.observe("p2").legal_actions[0]

        session.choose("p1", p1_choice)

        assert session.observe("p1").legal_actions == ()
        with pytest.raises(ShowdownBridgeError) as captured:
            session.choose("p1", p1_choice)
        assert captured.value.code == "CHOICE_UNAVAILABLE"

        session.choose("p2", p2_choice)
        assert session.observe("p1").legal_actions
    finally:
        session.close()


def test_choice_canonicalization_matches_replay_input_exactly(
    client: ShowdownClient,
) -> None:
    session = client.create_session(
        session_id="choice-canonicalization",
        seed=sodium_seed(72),
        p1_name="Alpha",
        p1_team=legal_team(),
        p2_name="Beta",
        p2_team=opponent_team_with_private_item(),
    )
    try:
        p1_choice = "team 123"
        p2_choice = "team 456"

        _p1_summary, p1_input = session.choose_with_replay_input("p1", p1_choice)
        _p2_summary, p2_input = session.choose_with_replay_input("p2", p2_choice)
        replay = session.replay(allow_incomplete=True).to_dict()

        assert p1_input == ">p1 team 1, 2, 3"
        assert p2_input == ">p2 team 4, 5, 6"
        assert replay["input_log"][3:] == [p1_input, p2_input]
    finally:
        session.close()


def test_private_observation_legal_actions_damage_and_replay(client: ShowdownClient) -> None:
    session = client.create_session(
        session_id="integration-main",
        seed=sodium_seed(),
        p1_name="Alpha",
        p1_team=legal_team(),
        p2_name="Beta",
        p2_team=opponent_team_with_private_item(),
    )
    try:
        with pytest.raises(ShowdownBridgeError) as captured:
            session.replay()
        assert captured.value.code == "REPLAY_INCOMPLETE"

        preview = session.observe("p1")
        assert len(preview.legal_actions) == 120
        assert "team 123" in preview.legal_actions
        assert any(line.startswith("|poke|p2|Pikachu") for line in preview.visible_log)
        assert "lightball" not in canonical_json(preview)

        session.choose("p1", "team 123")
        session.choose("p2", "team 123")
        move_request = session.observe("p1", since=preview.next_sequence)
        assert "move 1" in move_request.legal_actions
        assert "switch 2" in move_request.legal_actions

        first = session.damage_sample("p1", "Thunderbolt")
        second = session.damage_sample("p1", "Thunderbolt")
        assert first == second
        assert first.damage is not None and first.damage > 0
        assert first.move_type == "Electric"
        assert first.move_category == "Special"
        assert first.damage_status == "value"
        assert first.clone_seed_before != first.clone_seed_after
        assert first.live_seed_before == first.live_seed_after == first.clone_seed_before

        status = session.damage_sample("p1", "Protect")
        assert status.damage is None
        assert status.move_category == "Status"
        assert status.damage_status == "non_damaging"

        session.choose("p1", "move 1")
        session.choose("p2", "move 1")
        replay = session.replay(allow_incomplete=True)
        replay_document = replay.to_dict()
        assert replay_document["engine"]["commit"] == client.resolved.manifest.commit
        assert len(replay_document["engine"]["bridge_sha256"]) == 64
        assert replay_document["format_id"] == client.default_format_id
        assert replay_document["input_log"][-2:] == [
            ">p1 move thunderbolt",
            ">p2 move thunderbolt",
        ]
        assert replay_document["replay_hash"] == replay.replay_hash
        assert "|t:|0" in replay_document["public_log"]
        replay_schema = json.loads(
            (ROOT / "data/schemas/showdown-replay.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(replay_schema).validate(replay_document)
    finally:
        session.close()


def test_damage_sample_applies_showdown_move_type_modification(
    client: ShowdownClient,
) -> None:
    team = pixilate_team()
    assert client.validate_team(team) == ()
    session = client.create_session(
        session_id="damage-modify-type",
        seed=sodium_seed(16),
        p1_name="Alpha",
        p1_team=team,
        p2_name="Beta",
        p2_team=legal_team(),
    )
    try:
        session.choose("p1", "team 123")
        session.choose("p2", "team 123")
        sample = session.damage_sample("p1", "Hyper Voice")
        assert sample.move_type == "Fairy"
        assert sample.move_category == "Special"
        assert sample.damage_status == "value"
        assert sample.damage is not None and sample.damage > 0
    finally:
        session.close()


def test_damage_sample_breaks_clone_aliases_even_when_move_events_log(
    client: ShowdownClient,
) -> None:
    first = client.create_session(
        session_id="damage-log-isolation-a",
        seed=sodium_seed(160),
        p1_name="Alpha",
        p1_team=pixilate_team(),
        p2_name="Beta",
        p2_team=throat_chop_team(),
    )
    control = client.create_session(
        session_id="damage-log-isolation-b",
        seed=sodium_seed(160),
        p1_name="Alpha",
        p1_team=pixilate_team(),
        p2_name="Beta",
        p2_team=throat_chop_team(),
    )
    try:
        for session in (first, control):
            session.choose("p1", "team 123")
            session.choose("p2", "team 123")
            session.choose("p1", "move 4")
            session.choose("p2", "move 1")

        with pytest.raises(ShowdownBridgeError) as captured:
            first.damage_sample("p1", "Hyper Voice")
        assert captured.value.code == "DAMAGE_UNAVAILABLE"

        for session in (first, control):
            session.choose("p1", "move 3")
            session.choose("p2", "move 2")

        assert first.replay(allow_incomplete=True).to_dict() == control.replay(
            allow_incomplete=True
        ).to_dict()
    finally:
        first.close()
        control.close()


def test_replay_round_trip_accepts_packed_defaults_and_optional_fields(
    client: ShowdownClient,
) -> None:
    team = legal_team()
    for pokemon in team:
        pokemon["level"] = 100
    team[0]["happiness"] = 200
    assert client.validate_team(team) == ()
    session = client.create_session(
        session_id="packed-defaults",
        seed=sodium_seed(48),
        p1_name="Alpha",
        p1_team=team,
        p2_name="Beta",
        p2_team=team,
    )
    try:
        session.choose("p1", "team 123")
        session.choose("p2", "team 123")
        replay = session.replay(allow_incomplete=True)
        assert client.replay_input_log(replay.to_dict()).to_dict() == replay.to_dict()
    finally:
        session.close()


def test_parent_node_injection_variables_do_not_reach_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NODE_OPTIONS", "--definitely-invalid-option")
    monkeypatch.setenv("NODE_PATH", "hostile-node-modules")
    monkeypatch.setenv("GIT_DIR", "hostile-git-dir")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "hostile-git-objects")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")

    with ShowdownClient() as isolated:
        assert isolated.validate_team(legal_team()) == ()


def test_equal_inputs_have_equal_replay_identity_and_sessions_are_isolated(
    client: ShowdownClient,
) -> None:
    sessions = [
        client.create_session(
            session_id=f"deterministic-{index}",
            seed=sodium_seed(32),
            p1_name="Alpha",
            p1_team=legal_team(),
            p2_name="Beta",
            p2_team=legal_team(),
        )
        for index in range(2)
    ]
    try:
        for session in sessions:
            session.choose("p1", "team 123")
            session.choose("p2", "team 123")
            session.choose("p1", "move 1")
            session.choose("p2", "move 1")
        assert sessions[0].replay(allow_incomplete=True).to_dict() == sessions[
            1
        ].replay(allow_incomplete=True).to_dict()
        assert sessions[0].observe("p1").session_id != sessions[1].observe("p1").session_id
    finally:
        for session in sessions:
            session.close()


def _complete_battle(client: ShowdownClient, session_id: str) -> dict[str, object]:
    session = client.create_session(
        session_id=session_id,
        seed=sodium_seed(64),
        p1_name="Alpha",
        p1_team=legal_team(),
        p2_name="Beta",
        p2_team=legal_team(),
    )
    try:
        for _decision in range(500):
            acted = False
            for player in ("p1", "p2"):
                observation = session.observe(player)
                if observation.ended:
                    replay = session.replay().to_dict()
                    assert replay["winner"] in {"Alpha", "Beta"}
                    assert replay["score"] is not None
                    return replay
                if observation.legal_actions:
                    preferred = next(
                        (
                            choice
                            for choice in observation.legal_actions
                            if choice in {"team 123", "move 1"}
                        ),
                        observation.legal_actions[0],
                    )
                    session.choose(player, preferred)
                    acted = True
            if not acted:
                raise AssertionError("battle stalled without a legal action")
        raise AssertionError("battle exceeded the decision budget")
    finally:
        session.close()


def test_terminal_battle_is_deterministic_and_replay_is_executable(
    client: ShowdownClient,
) -> None:
    first = _complete_battle(client, "complete-a")
    second = _complete_battle(client, "complete-b")

    assert first == second
    assert client.replay_input_log(first).to_dict() == first

    altered = deepcopy(first)
    altered["public_log"][-1] = "|win|Mallory"
    with pytest.raises(ValueError, match="replay hash"):
        client.replay_input_log(altered)

    illegal = deepcopy(first)
    illegal["input_log"][-1] = ">p2 move 999"
    illegal["replay_hash"] = canonical_hash(
        {key: value for key, value in illegal.items() if key != "replay_hash"}
    )
    with pytest.raises(ShowdownBridgeError) as captured:
        client.replay_input_log(illegal)
    assert captured.value.code == "INVALID_REPLAY"


def test_invalid_choice_fails_closed_without_killing_bridge(client: ShowdownClient) -> None:
    session = client.create_session(
        session_id="invalid-choice",
        seed=sodium_seed(96),
        p1_name="Alpha",
        p1_team=legal_team(),
        p2_name="Beta",
        p2_team=legal_team(),
    )
    try:
        with pytest.raises(ShowdownBridgeError) as captured:
            session.choose("p1", "move 999")
        assert captured.value.code == "CHOICE_REJECTED"
        assert client.validate_team(legal_team()) == ()
    finally:
        session.close()


def test_bridge_parser_rejects_duplicate_keys() -> None:
    resolved = resolve_showdown()
    bridge = Path(__file__).resolve().parents[1] / "bridge" / "showdown-bridge.cjs"
    process = subprocess.Popen(
        [
            str(resolved.node_executable),
            str(bridge),
            str(resolved.root),
            resolved.manifest.default_format.id,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        process.stdin.write(
            '{"protocol_version":"1.0.0","request_id":0,"method":"hello",'
            '"method":"hello","params":{}}\n'
        )
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        assert response["ok"] is False
        assert response["error"]["code"] == "DUPLICATE_JSON_KEY"
        process.stdin.write(
            '{"protocol_version":"1.0.0","request_id":1,"method":"hello",'
            '"params":{},"__proto__":{"polluted":true}}\n'
        )
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        assert response["ok"] is False
        assert response["error"]["code"] == "INVALID_REQUEST"
        process.stdin.write(
            '{"protocol_version":"1.0.0","request_id":1e9999,'
            '"method":"hello","params":{}}\n'
        )
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        assert response["ok"] is False
        assert response["error"]["code"] == "INVALID_JSON"
    finally:
        process.stdin.close()
        process.wait(timeout=5)


def test_terminated_bridge_never_falls_back() -> None:
    client = ShowdownClient()
    client.process._process.kill()
    client.process._process.wait(timeout=5)
    try:
        with pytest.raises(ShowdownProcessError, match="not running"):
            client.validate_team(legal_team())
    finally:
        client.close()


def test_timeout_terminates_the_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ShowdownClient()

    def time_out(*, timeout: float) -> str:
        assert timeout == client.process.timeout_seconds
        raise queue.Empty

    monkeypatch.setattr(client.process._responses, "get", time_out)
    try:
        with pytest.raises(ShowdownProcessError, match="timed out"):
            client.validate_team(legal_team())
        assert client.process._process.poll() is not None
    finally:
        client.close()


def test_manifest_identity_mismatch_fails_before_process_start(tmp_path: Path) -> None:
    resolved = resolve_showdown()
    document = json.loads(resolved.manifest.path.read_text(encoding="utf-8"))
    document["runtime_dependencies"][0]["runtime_files"][
        "node_modules/ts-chacha20/build/src/chacha20.js"
    ] = "0" * 64
    hostile = tmp_path / "manifest.json"
    hostile.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ShowdownResolutionError, match="runtime dependency hash mismatch"):
        resolve_showdown(
            root=resolved.root,
            node_executable=resolved.node_executable,
            manifest_path=hostile,
        )


def test_upstream_git_blob_mismatch_fails_before_process_start(tmp_path: Path) -> None:
    resolved = resolve_showdown()
    document = json.loads(resolved.manifest.path.read_text(encoding="utf-8"))
    document["source_files"]["LICENSE"] = "0" * 64
    document["upstream"]["license_sha256"] = "0" * 64
    hostile = tmp_path / "manifest.json"
    hostile.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ShowdownResolutionError, match="blob="):
        resolve_showdown(
            root=resolved.root,
            node_executable=resolved.node_executable,
            manifest_path=hostile,
        )


def test_dependency_origin_mismatch_fails_before_hash_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = resolve_showdown()
    real_run = resolver_module._run

    def changed_origin(
        arguments: list[str],
        *,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        if arguments[-3:] == ["remote", "get-url", "origin"]:
            return "https://example.invalid/lookalike.git"
        return real_run(arguments, cwd=cwd, environment=environment)

    monkeypatch.setattr(resolver_module, "_run", changed_origin)
    with pytest.raises(ShowdownResolutionError, match="origin mismatch"):
        resolve_showdown(
            root=resolved.root,
            node_executable=resolved.node_executable,
        )
