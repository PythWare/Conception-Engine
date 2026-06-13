from __future__ import annotations

import gzip, json, mmap, shutil, struct
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .profiles import (
    CONTAINER_BGM,
    CONTAINER_MAIN,
    CONTAINER_VOICE,
    CONTAINERS,
    GameProfile,
)


TAILDATA_FILENAME = "conception_taildata.json"
TAILDATA_FORMAT = "conception-taildata"
BASE_VALUE = 16
GZIP_MAGIC = b"\x1f\x8b"

ProgressCallback = Callable[[int, int, str], None]


class CfsiFormatError(RuntimeError):
    pass


@dataclass(frozen=True)
class CfsiEntry:
    container: str
    folder: str
    filename: str
    path: str
    toc_offset: int
    stored_offset: int
    stored_size: int
    absolute_offset: int
    base_offset: int


class BinaryCursor:
    def __init__(self, data: mmap.mmap, label: str):
        self.data = data
        self.label = label
        self.pos = 0

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int):
        if offset < 0 or offset > len(self.data):
            raise CfsiFormatError(f"{self.label}: seek out of range at 0x{offset:x}")
        self.pos = offset

    def read(self, size: int) -> bytes:
        end = self.pos + size
        if end > len(self.data):
            raise CfsiFormatError(
                f"{self.label}: tried to read {size} bytes past EOF at 0x{self.pos:x}"
            )
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def skip(self, size: int):
        self.seek(self.pos + size)

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def u32(self) -> int:
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decode_name(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def normalize_entry_path(folder: str, filename: str) -> str:
    raw = f"{folder}{filename}".replace("\\", "/")
    parts: list[str] = []
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            parts.append("_")
            continue
        parts.append(part)
    if not parts:
        raise CfsiFormatError(f"Empty CFSI entry path for {folder!r} {filename!r}")
    return "/".join(parts)


def filesystem_path(root: Path, archive_path: str) -> Path:
    return root.joinpath(*archive_path.split("/"))


def make_entry(
    profile: GameProfile,
    container: str,
    folder: str,
    filename: str,
    toc_offset: int,
    stored_offset: int,
    stored_size: int,
) -> CfsiEntry:
    base_offset = profile.base_offsets[container]
    absolute_offset = stored_offset * BASE_VALUE + base_offset
    return CfsiEntry(
        container=container,
        folder=folder,
        filename=filename,
        path=normalize_entry_path(folder, filename),
        toc_offset=toc_offset,
        stored_offset=stored_offset,
        stored_size=stored_size,
        absolute_offset=absolute_offset,
        base_offset=base_offset,
    )


def parse_c1_main(profile: GameProfile, data: mmap.mmap) -> list[CfsiEntry]:
    cursor = BinaryCursor(data, CONTAINER_MAIN)
    entries: list[CfsiEntry] = []

    for folder_index in range(182):
        section_start = cursor.tell()
        cursor.u8()
        folder_name_len = cursor.u8()
        if folder_name_len > 60:
            cursor.seek(section_start)
            folder_name_len = cursor.u8()

        folder = decode_name(cursor.read(folder_name_len))
        count_offset = cursor.tell()
        marker = cursor.read(1)
        if marker in (b"\xfc", b"\xf8"):
            file_count = cursor.u16()
        else:
            cursor.seek(count_offset)
            file_count = cursor.u8()

        for file_index in range(file_count):
            filename_len = cursor.u8()
            filename = decode_name(cursor.read(filename_len))
            toc_offset = cursor.tell()
            stored_offset = cursor.u32()
            stored_size = cursor.u32()
            entries.append(
                make_entry(
                    profile,
                    CONTAINER_MAIN,
                    folder,
                    filename,
                    toc_offset,
                    stored_offset,
                    stored_size,
                )
            )

    return entries


def parse_c2_main(profile: GameProfile, data: mmap.mmap) -> list[CfsiEntry]:
    cursor = BinaryCursor(data, CONTAINER_MAIN)
    cursor.skip(3)
    entries: list[CfsiEntry] = []

    sections = (
        (302, 0, 0),
        (1, 2, 311),
        (93, 0, 0),
        (1, 2, 269),
    )
    for folder_count, extra_bytes, forced_file_count in sections:
        for folder_index in range(folder_count):
            folder_name_len = cursor.u8()
            folder = decode_name(cursor.read(folder_name_len))
            file_count = cursor.u8()
            if extra_bytes:
                cursor.skip(extra_bytes)

            count = forced_file_count or file_count
            for file_index in range(count):
                filename_len = cursor.u8()
                filename = decode_name(cursor.read(filename_len))
                toc_offset = cursor.tell()
                stored_offset = cursor.u32()
                stored_size = cursor.u32()
                entries.append(
                    make_entry(
                        profile,
                        CONTAINER_MAIN,
                        folder,
                        filename,
                        toc_offset,
                        stored_offset,
                        stored_size,
                    )
                )

    return entries


def parse_bgm(profile: GameProfile, data: mmap.mmap) -> list[CfsiEntry]:
    cursor = BinaryCursor(data, CONTAINER_BGM)
    cursor.skip(1)
    folder_name_len = cursor.u8()
    folder = decode_name(cursor.read(folder_name_len))
    file_count = cursor.u8()
    entries: list[CfsiEntry] = []

    for file_index in range(file_count):
        filename_len = cursor.u8()
        filename = decode_name(cursor.read(filename_len))
        toc_offset = cursor.tell()
        stored_offset = cursor.u32()
        stored_size = cursor.u32()
        entries.append(
            make_entry(
                profile,
                CONTAINER_BGM,
                folder,
                filename,
                toc_offset,
                stored_offset,
                stored_size,
            )
        )

    return entries


def parse_voice(profile: GameProfile, data: mmap.mmap) -> list[CfsiEntry]:
    cursor = BinaryCursor(data, CONTAINER_VOICE)
    cursor.skip(1)
    folder_name_len = cursor.u8()
    folder = decode_name(cursor.read(folder_name_len))
    cursor.skip(1)
    file_count = cursor.u16()
    entries: list[CfsiEntry] = []

    for file_index in range(file_count):
        filename_len = cursor.u8()
        filename = decode_name(cursor.read(filename_len))
        toc_offset = cursor.tell()
        stored_offset = cursor.u32()
        stored_size = cursor.u32()
        entries.append(
            make_entry(
                profile,
                CONTAINER_VOICE,
                folder,
                filename,
                toc_offset,
                stored_offset,
                stored_size,
            )
        )

    return entries


def parse_container_entries(
    profile: GameProfile, container: str, data: mmap.mmap
) -> list[CfsiEntry]:
    if container == CONTAINER_MAIN:
        if profile.game_id == "con1":
            return parse_c1_main(profile, data)
        if profile.game_id == "con2":
            return parse_c2_main(profile, data)
    if container == CONTAINER_BGM:
        return parse_bgm(profile, data)
    if container == CONTAINER_VOICE:
        return parse_voice(profile, data)
    raise CfsiFormatError(f"Unsupported CFSI container {container!r}")


def is_compressed_payload(payload: bytes) -> bool:
    return len(payload) >= 6 and payload[4:6] == GZIP_MAGIC


def decompress_payload(payload: bytes) -> bytes:
    if not is_compressed_payload(payload):
        return payload
    return gzip.decompress(payload[4:])


def make_conception_gzip_payload(data: bytes) -> bytes:
    gzip_stream = bytearray(gzip.compress(data, compresslevel=1, mtime=0))
    if len(gzip_stream) >= 10:
        gzip_stream[9] = 0x03
    return struct.pack("<I", len(data)) + bytes(gzip_stream)


def load_entries_by_container(
    profile: GameProfile, source_dir: Path
) -> dict[str, list[CfsiEntry]]:
    source_dir = Path(source_dir)
    entries_by_container: dict[str, list[CfsiEntry]] = {}
    for container in CONTAINERS:
        container_path = source_dir / container
        if not container_path.is_file():
            raise FileNotFoundError(f"Missing required CFSI container: {container_path}")

        with container_path.open("rb") as file_obj:
            with mmap.mmap(file_obj.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                entries_by_container[container] = parse_container_entries(
                    profile, container, mapped
                )

    return entries_by_container


def check_game(profile: GameProfile, source_dir: Path) -> dict:
    source_dir = Path(source_dir)
    summary = {
        "game": profile.game_id,
        "source_dir": str(source_dir),
        "containers": {},
        "total_entries": 0,
        "bad_entries": 0,
        "compressed_entries": 0,
    }

    for container in CONTAINERS:
        container_path = source_dir / container
        if not container_path.is_file():
            raise FileNotFoundError(f"Missing required CFSI container: {container_path}")

        with container_path.open("rb") as file_obj:
            with mmap.mmap(file_obj.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                entries = parse_container_entries(profile, container, mapped)
                bad_entries = 0
                compressed_entries = 0
                for entry in entries:
                    end = entry.absolute_offset + entry.stored_size
                    if entry.absolute_offset < 0 or end > len(mapped):
                        bad_entries += 1
                        continue
                    if (
                        entry.stored_size >= 6
                        and mapped[entry.absolute_offset + 4 : entry.absolute_offset + 6]
                        == GZIP_MAGIC
                    ):
                        compressed_entries += 1

                summary["containers"][container] = {
                    "entries": len(entries),
                    "bad_entries": bad_entries,
                    "compressed_entries": compressed_entries,
                    "size": container_path.stat().st_size,
                }
                summary["total_entries"] += len(entries)
                summary["bad_entries"] += bad_entries
                summary["compressed_entries"] += compressed_entries

    return summary


def copy_default_mods_file(profile: GameProfile, source_dir: Path):
    mods_path = Path(source_dir) / profile.enabled_mods_filename
    if not mods_path.exists():
        mods_path.write_text(
            json.dumps(
                {
                    "format": "conception-enabled-mods",
                    "version": 1,
                    "game": profile.game_id,
                    "mods": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def unpack_game(
    profile: GameProfile,
    source_dir: Path,
    output_dir: Path,
    progress: ProgressCallback | None = None,
    limit: int | None = None,
) -> dict:
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    entries_by_container = load_entries_by_container(profile, source_dir)
    available_total = sum(len(entries) for entries in entries_by_container.values())
    total = min(available_total, limit) if limit is not None else available_total
    done = 0

    manifest = {
        "format": TAILDATA_FORMAT,
        "version": 1,
        "game": profile.game_id,
        "game_label": profile.label,
        "created_utc": utc_now(),
        "source_dir": str(source_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "taildata_note": (
            "External metadata for taildata, used for mod applying/disabling. "
            "Keys are unpacked relative file paths."
        ),
        "files": {},
    }

    for container, entries in entries_by_container.items():
        if limit is not None and done >= limit:
            break
        container_path = source_dir / container
        with container_path.open("rb") as file_obj:
            with mmap.mmap(file_obj.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                for entry in entries:
                    if limit is not None and done >= limit:
                        break
                    end = entry.absolute_offset + entry.stored_size
                    if entry.absolute_offset < 0 or end > len(mapped):
                        raise CfsiFormatError(
                            f"{container}:{entry.path} points outside the container"
                        )

                    payload = mapped[entry.absolute_offset:end]
                    compressed = is_compressed_payload(payload)
                    try:
                        file_data = decompress_payload(payload)
                    except OSError as exc:
                        raise CfsiFormatError(
                            f"{container}:{entry.path} failed gzip decompression"
                        ) from exc

                    output_path = filesystem_path(output_dir, entry.path)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(file_data)

                    record = asdict(entry)
                    record.update(
                        {
                            "compressed": compressed,
                            "unpacked_size": len(file_data),
                            "stored_size": entry.stored_size,
                        }
                    )
                    manifest["files"][entry.path] = record

                    done += 1
                    if progress and (done == total or done % 100 == 0):
                        progress(done, total, f"Unpacked {entry.path}")

    taildata_path = output_dir / TAILDATA_FILENAME
    taildata_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if progress:
        progress(done, total, f"Wrote metadata {taildata_path.name}")

    return {
        "game": profile.game_id,
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "taildata_path": str(taildata_path),
        "files": total,
        "available_files": available_total,
    }
