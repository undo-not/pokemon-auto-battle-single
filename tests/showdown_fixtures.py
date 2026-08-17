"""Small legal Champions teams for the pinned Showdown integration tests."""

from __future__ import annotations

from copy import deepcopy


TEAM = [
    {
        "species": "Pikachu",
        "ability": "Static",
        "moves": ["Thunderbolt", "Quick Attack", "Protect", "Nuzzle"],
        "nature": "Timid",
        "level": 50,
    },
    {
        "species": "Charizard",
        "ability": "Blaze",
        "moves": ["Flamethrower", "Air Slash", "Protect", "Dragon Pulse"],
        "nature": "Timid",
        "level": 50,
    },
    {
        "species": "Garchomp",
        "ability": "Rough Skin",
        "moves": ["Earthquake", "Dragon Claw", "Protect", "Swords Dance"],
        "nature": "Jolly",
        "level": 50,
    },
    {
        "species": "Gengar",
        "ability": "Cursed Body",
        "moves": ["Shadow Ball", "Sludge Bomb", "Protect", "Hypnosis"],
        "nature": "Timid",
        "level": 50,
    },
    {
        "species": "Dragonite",
        "ability": "Multiscale",
        "moves": ["Dragon Claw", "Extreme Speed", "Protect", "Dragon Dance"],
        "nature": "Adamant",
        "level": 50,
    },
    {
        "species": "Lucario",
        "ability": "Inner Focus",
        "moves": ["Close Combat", "Extreme Speed", "Protect", "Swords Dance"],
        "nature": "Jolly",
        "level": 50,
    },
]


def legal_team() -> list[dict[str, object]]:
    return deepcopy(TEAM)


def opponent_team_with_private_item() -> list[dict[str, object]]:
    team = legal_team()
    team[0]["item"] = "Light Ball"
    return team


def sodium_seed(offset: int = 0) -> str:
    return "sodium," + "".join(f"{(offset + index) % 256:02x}" for index in range(32))
