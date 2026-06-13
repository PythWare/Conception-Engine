from __future__ import annotations

import json, struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .cfsi import BASE_VALUE
from .mod_package import ModPackageError, iter_package_payloads, read_package_manifest
from .profiles import CONTAINERS, GameProfile


ENABLED_FORMAT = "conception-enabled-mods"
ENABLED_VERSION = 1
ProgressCallback = Callable[[int, int, str], None]


class ModManagerError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def enabled_mods_path(profile: GameProfile, game_dir: Path) -> Path:
    return Path(game_dir) / profile.enabled_mods_filename


def empty_enabled_state(profile: GameProfile) -> dict:
    return {
        "format": ENABLED_FORMAT,
        "version": ENABLED_VERSION,
        "game": profile.game_id,
        "mods": [],
    }


def load_enabled_mods(profile: GameProfile, game_dir: Path) -> dict:
    path = enabled_mods_path(profile, game_dir)
    if not path.exists():
        return empty_enabled_state(profile)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModManagerError(f"Could not read enabled mods file: {path}") from exc
    if data.get("format") != ENABLED_FORMAT or data.get("game") != profile.game_id:
        raise ModManagerError(f"{path} is not a valid enabled-mods file for this game")
    data.setdefault("mods", [])
    return data


def save_enabled_mods(profile: GameProfile, game_dir: Path, data: dict):
    path = enabled_mods_path(profile, game_dir)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_enabled_mods(profile: GameProfile, game_dir: Path) -> list[dict]:
    return load_enabled_mods(profile, game_dir).get("mods", [])


def read_toc_pair(container_path: Path, toc_offset: int) -> tuple[int, int]:
    with container_path.open("rb") as file_obj:
        file_obj.seek(toc_offset)
        data = file_obj.read(8)
    if len(data) != 8:
        raise ModManagerError(f"TOC entry points outside container: {container_path}")
    return struct.unpack("<II", data)


def write_toc_pair(container_path: Path, toc_offset: int, stored_offset: int, stored_size: int):
    with container_path.open("r+b") as file_obj:
        file_obj.seek(toc_offset)
        file_obj.write(struct.pack("<II", stored_offset, stored_size))


def append_payload(
    profile: GameProfile, container_path: Path, container: str, payload: bytes
) -> tuple[int, int, int, int]:
    base_offset = profile.base_offsets[container]
    with container_path.open("ab") as file_obj:
        end_offset = file_obj.tell()
        pre_padding = (BASE_VALUE - ((end_offset - base_offset) % BASE_VALUE)) % BASE_VALUE
        if pre_padding:
            file_obj.write(b"\x00" * pre_padding)
        payload_offset = end_offset + pre_padding
        if payload_offset < base_offset:
            raise ModManagerError(
                f"{container_path} is smaller than the data base offset for {container}"
            )
        file_obj.write(payload)
        post_padding = (BASE_VALUE - (len(payload) % BASE_VALUE)) % BASE_VALUE
        if post_padding:
            file_obj.write(b"\x00" * post_padding)

    stored_offset = (payload_offset - base_offset) // BASE_VALUE
    if stored_offset > 0xFFFFFFFF or len(payload) > 0xFFFFFFFF:
        raise ModManagerError(f"Appended payload is too large for a 32-bit CFSI TOC entry")
    return payload_offset, stored_offset, len(payload), pre_padding + len(payload) + post_padding


def mod_targets(mod: dict) -> set[tuple[str, str, int]]:
    return {
        (entry["container"], entry["path"], int(entry["toc_offset"]))
        for entry in mod.get("entries", [])
    }


def has_later_owner(mods: list[dict], mod_index: int, target: tuple[str, str, int]) -> bool:
    for later_mod in mods[mod_index + 1 :]:
        if target in mod_targets(later_mod):
            return True
    return False


def containers_still_modded(mods: list[dict]) -> set[str]:
    containers: set[str] = set()
    for mod in mods:
        for entry in mod.get("entries", []):
            containers.add(entry["container"])
    return containers


def truncate_unmodded_containers(profile: GameProfile, game_dir: Path, remaining_mods: list[dict]):
    still_modded = containers_still_modded(remaining_mods)
    for container, size in profile.original_sizes.items():
        if container in still_modded:
            continue
        container_path = Path(game_dir) / container
        if container_path.exists() and container_path.stat().st_size > size:
            with container_path.open("r+b") as file_obj:
                file_obj.truncate(size)


def apply_mod_package(
    profile: GameProfile,
    game_dir: Path,
    package_path: Path,
    progress: ProgressCallback | None = None,
) -> dict:
    game_dir = Path(game_dir)
    package_path = Path(package_path)
    manifest = read_package_manifest(package_path)
    if manifest.get("game") != profile.game_id:
        raise ModPackageError(
            f"Package is for {manifest.get('game')!r}, not {profile.game_id!r}"
        )

    enabled_state = load_enabled_mods(profile, game_dir)
    mod_id = package_path.name
    if any(mod.get("id") == mod_id for mod in enabled_state["mods"]):
        raise ModManagerError(f"{mod_id} is already enabled")

    entries = manifest.get("entries", [])
    applied_entries: list[dict] = []
    total = len(entries)

    for index, (entry, payload) in enumerate(
        iter_package_payloads(package_path, manifest), start=1
    ):
        container = entry["container"]
        if container not in CONTAINERS:
            raise ModManagerError(f"Package references unknown container {container!r}")
        container_path = game_dir / container
        if not container_path.is_file():
            raise FileNotFoundError(f"Missing target CFSI container: {container_path}")

        toc_offset = int(entry["toc_offset"])
        previous_offset, previous_size = read_toc_pair(container_path, toc_offset)
        payload_offset, new_stored_offset, new_stored_size, appended_size = append_payload(
            profile, container_path, container, payload
        )
        write_toc_pair(container_path, toc_offset, new_stored_offset, new_stored_size)

        applied_entries.append(
            {
                "path": entry["path"],
                "container": container,
                "toc_offset": toc_offset,
                "previous_stored_offset": previous_offset,
                "previous_stored_size": previous_size,
                "default_stored_offset": int(entry["original_stored_offset"]),
                "default_stored_size": int(entry["original_stored_size"]),
                "new_stored_offset": new_stored_offset,
                "new_stored_size": new_stored_size,
                "payload_offset": payload_offset,
                "appended_size": appended_size,
            }
        )

        if progress:
            progress(index, total, f"Applied {entry['path']}")

    enabled_state["mods"].append(
        {
            "id": mod_id,
            "name": manifest.get("name") or package_path.stem,
            "package_path": str(package_path.resolve()),
            "description": manifest.get("description", ""),
            "applied_utc": utc_now(),
            "entries": applied_entries,
        }
    )
    save_enabled_mods(profile, game_dir, enabled_state)

    if progress:
        progress(total, total, f"Enabled {mod_id}")

    return {
        "mod_id": mod_id,
        "entries": len(applied_entries),
        "game": profile.game_id,
    }


def disable_mod(
    profile: GameProfile,
    game_dir: Path,
    mod_id: str,
    progress: ProgressCallback | None = None,
) -> dict:
    game_dir = Path(game_dir)
    enabled_state = load_enabled_mods(profile, game_dir)
    mods = enabled_state.get("mods", [])
    mod_index = next((index for index, mod in enumerate(mods) if mod.get("id") == mod_id), -1)
    if mod_index < 0:
        raise ModManagerError(f"{mod_id} is not currently enabled")

    mod = mods[mod_index]
    entries = list(reversed(mod.get("entries", [])))
    total = len(entries)
    restored = 0

    for index, entry in enumerate(entries, start=1):
        target = (entry["container"], entry["path"], int(entry["toc_offset"]))
        if has_later_owner(mods, mod_index, target):
            if progress:
                progress(index, total, f"Kept newer override for {entry['path']}")
            continue

        container_path = game_dir / entry["container"]
        write_toc_pair(
            container_path,
            int(entry["toc_offset"]),
            int(entry["previous_stored_offset"]),
            int(entry["previous_stored_size"]),
        )
        restored += 1
        if progress:
            progress(index, total, f"Disabled {entry['path']}")

    del mods[mod_index]
    enabled_state["mods"] = mods
    save_enabled_mods(profile, game_dir, enabled_state)
    truncate_unmodded_containers(profile, game_dir, mods)

    if progress:
        progress(total, total, f"Disabled {mod_id}")

    return {"mod_id": mod_id, "restored_entries": restored, "remaining_mods": len(mods)}


def disable_all_mods(
    profile: GameProfile,
    game_dir: Path,
    progress: ProgressCallback | None = None,
) -> dict:
    game_dir = Path(game_dir)
    enabled_state = load_enabled_mods(profile, game_dir)
    mods = enabled_state.get("mods", [])
    entries = [entry for mod in reversed(mods) for entry in reversed(mod.get("entries", []))]
    total = len(entries)

    for index, entry in enumerate(entries, start=1):
        container_path = game_dir / entry["container"]
        write_toc_pair(
            container_path,
            int(entry["toc_offset"]),
            int(entry["previous_stored_offset"]),
            int(entry["previous_stored_size"]),
        )
        if progress:
            progress(index, total, f"Restored {entry['path']}")

    for container, size in profile.original_sizes.items():
        container_path = game_dir / container
        if container_path.exists():
            with container_path.open("r+b") as file_obj:
                file_obj.truncate(size)

    enabled_state["mods"] = []
    save_enabled_mods(profile, game_dir, enabled_state)

    if progress:
        progress(total, total, "Disabled all mods")

    return {"disabled_mods": len(mods), "restored_entries": total}
