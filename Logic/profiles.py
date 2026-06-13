from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CONTAINER_MAIN = "00000000.cfsi"
CONTAINER_BGM = "bgm.cfsi"
CONTAINER_VOICE = "voice.cfsi"
CONTAINERS = (CONTAINER_MAIN, CONTAINER_BGM, CONTAINER_VOICE)


@dataclass(frozen=True)
class GameProfile:
    game_id: str
    label: str
    short_label: str
    default_folder: str
    package_extension: str
    enabled_mods_filename: str
    output_folder: str
    base_offsets: dict[str, int]
    original_sizes: dict[str, int]

    def default_source_dir(self, project_root: Path) -> Path:
        return project_root / self.default_folder

    def default_output_dir(self, project_root: Path) -> Path:
        return project_root / "Unpacked_Files" / self.output_folder


GAME_PROFILES: dict[str, GameProfile] = {
    "con1": GameProfile(
        game_id="con1",
        label="Conception 1/Plus",
        short_label="Conception 1",
        default_folder="c1",
        package_extension=".con1p",
        enabled_mods_filename="Conception_1.MODS.json",
        output_folder="Conception_1",
        base_offsets={
            CONTAINER_MAIN: 0x3B800,
            CONTAINER_BGM: 0x480,
            CONTAINER_VOICE: 0xAFDF0,
        },
        original_sizes={
            CONTAINER_MAIN: 5_122_184_048,
            CONTAINER_BGM: 115_141_072,
            CONTAINER_VOICE: 1_402_511_648,
        },
    ),
    "con2": GameProfile(
        game_id="con2",
        label="Conception II",
        short_label="Conception II",
        default_folder="c2",
        package_extension=".con2p",
        enabled_mods_filename="Conception_II.MODS.json",
        output_folder="Conception_II",
        base_offsets={
            CONTAINER_MAIN: 0x2D7A0,
            CONTAINER_BGM: 0x520,
            CONTAINER_VOICE: 0x95690,
        },
        original_sizes={
            CONTAINER_MAIN: 2_929_987_872,
            CONTAINER_BGM: 107_557_248,
            CONTAINER_VOICE: 1_122_974_352,
        },
    ),
}


def get_profile(game_id: str) -> GameProfile:
    try:
        return GAME_PROFILES[game_id]
    except KeyError as exc:
        known = ", ".join(sorted(GAME_PROFILES))
        raise ValueError(f"Unknown game id {game_id!r}. Expected one of: {known}") from exc
