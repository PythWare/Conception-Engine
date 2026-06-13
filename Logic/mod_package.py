from __future__ import annotations

import hashlib, json, mimetypes, struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .cfsi import TAILDATA_FILENAME, make_conception_gzip_payload
from .profiles import GameProfile


PACKAGE_MAGIC = b"CONCEPTION_ARCANE_VOLUME"
PACKAGE_FORMAT = "conception-arcane-volume"
PACKAGE_VERSION = 2
HEADER_SIZE_STRUCT = struct.Struct("<I")
MAX_PREVIEW_IMAGES = 5
DEFAULT_GENRE = "Miscellaneous"
GENRES = [
    "Gameplay",
    "Visual",
    "Audio",
    "User Interface",
    "Restoration",
    "Balance",
    "Experimental",
    "Miscellaneous",
]

ProgressCallback = Callable[[int, int, str], None]


class ModPackageError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_taildata(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModPackageError(f"Could not read taildata manifest: {path}") from exc
    if data.get("format") != "conception-taildata":
        raise ModPackageError(f"{path} is not a Conception taildata manifest")
    return data


def find_taildata_for_folder(source_folder: Path) -> Path | None:
    source_folder = Path(source_folder).resolve()
    candidates = [source_folder, *source_folder.parents]
    for candidate in candidates:
        taildata_path = candidate / TAILDATA_FILENAME
        if taildata_path.is_file():
            return taildata_path
    return None


def normalize_genre(genre: str) -> str:
    clean_genre = (genre or "").strip()
    return clean_genre if clean_genre in GENRES else DEFAULT_GENRE


def candidate_relative_paths(
    file_path: Path, source_folder: Path, taildata_root: Path
) -> Iterable[str]:
    try:
        yield file_path.relative_to(taildata_root).as_posix()
    except ValueError:
        pass
    try:
        yield file_path.relative_to(source_folder).as_posix()
    except ValueError:
        pass


def read_exact(file_obj, size: int) -> bytes:
    data = file_obj.read(size)
    if len(data) != size:
        raise ModPackageError("Package ended before the expected payload was read")
    return data


def package_data_start(header_size: int) -> int:
    return len(PACKAGE_MAGIC) + HEADER_SIZE_STRUCT.size + header_size


def read_package_manifest(package_path: Path) -> dict:
    package_path = Path(package_path)
    try:
        with package_path.open("rb") as file_obj:
            magic = read_exact(file_obj, len(PACKAGE_MAGIC))
            if magic != PACKAGE_MAGIC:
                raise ModPackageError("Missing or invalid Conception package signature")
            header_size = HEADER_SIZE_STRUCT.unpack(read_exact(file_obj, HEADER_SIZE_STRUCT.size))[0]
            header_data = read_exact(file_obj, header_size)
    except OSError as exc:
        raise ModPackageError(f"Could not read mod package: {package_path}") from exc

    try:
        manifest = json.loads(header_data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ModPackageError(f"Package manifest is not valid JSON: {package_path}") from exc

    if manifest.get("format") != PACKAGE_FORMAT:
        raise ModPackageError(f"{package_path} is not a Conception Arcane package")
    if int(manifest.get("version", 0)) != PACKAGE_VERSION:
        raise ModPackageError(
            f"Unsupported package version {manifest.get('version')!r}"
        )
    manifest["header_size"] = header_size
    manifest["package_path"] = str(package_path)
    return manifest


def file_payloads_size(manifest: dict) -> int:
    return sum(int(entry["payload_size"]) for entry in manifest.get("entries", []))


def image_payloads_size(manifest: dict) -> int:
    return sum(int(image["size"]) for image in manifest.get("images", []))


def iter_package_payloads(package_path: Path, manifest: dict):
    header_size = int(manifest["header_size"])
    with Path(package_path).open("rb") as file_obj:
        file_obj.seek(package_data_start(header_size))
        for entry in manifest.get("entries", []):
            payload_size = int(entry["payload_size"])
            yield entry, read_exact(file_obj, payload_size)


def read_package_images(package_path: Path, manifest: dict) -> list[bytes]:
    header_size = int(manifest["header_size"])
    images: list[bytes] = []
    with Path(package_path).open("rb") as file_obj:
        file_obj.seek(package_data_start(header_size) + file_payloads_size(manifest))
        for image in manifest.get("images", []):
            images.append(read_exact(file_obj, int(image["size"])))
    return images


def read_package_audio(package_path: Path, manifest: dict) -> bytes | None:
    audio = manifest.get("audio")
    if not audio:
        return None
    header_size = int(manifest["header_size"])
    start = (
        package_data_start(header_size)
        + file_payloads_size(manifest)
        + image_payloads_size(manifest)
    )
    with Path(package_path).open("rb") as file_obj:
        file_obj.seek(start)
        return read_exact(file_obj, int(audio["size"]))


def read_binary_asset(path: Path) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise ModPackageError(f"Could not read asset: {path}") from exc


def build_image_records(image_paths: list[Path]) -> tuple[list[dict], list[bytes]]:
    records: list[dict] = []
    blobs: list[bytes] = []
    for image_path in image_paths[:MAX_PREVIEW_IMAGES]:
        data = read_binary_asset(image_path)
        mime_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
        records.append(
            {
                "name": image_path.name,
                "size": len(data),
                "mime": mime_type,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        blobs.append(data)
    return records, blobs


def build_audio_record(audio_path: Path | None) -> tuple[dict | None, bytes | None]:
    if audio_path is None:
        return None, None
    data = read_binary_asset(audio_path)
    record = {
        "name": audio_path.name,
        "size": len(data),
        "mime": "audio/wav",
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    return record, data


def create_mod_package(
    profile: GameProfile,
    source_folder: Path,
    output_path: Path,
    name: str,
    description: str,
    taildata_path: Path | None = None,
    author: str = "Unknown",
    version: str = "1",
    genre: str = DEFAULT_GENRE,
    image_paths: list[Path] | None = None,
    audio_path: Path | None = None,
    progress: ProgressCallback | None = None,
) -> dict:
    source_folder = Path(source_folder).resolve()
    output_path = Path(output_path).resolve()
    name = name.strip() or output_path.stem
    author = author.strip() or "Unknown"
    version = version.strip() or "1"
    description = description.strip()
    genre = normalize_genre(genre)

    if not source_folder.is_dir():
        raise ModPackageError(f"Source folder does not exist: {source_folder}")

    if taildata_path is None:
        taildata_path = find_taildata_for_folder(source_folder)
    if taildata_path is None:
        raise ModPackageError(
            f"No {TAILDATA_FILENAME} found in the selected folder or its parents"
        )
    taildata_path = Path(taildata_path).resolve()
    taildata_root = taildata_path.parent

    taildata = load_taildata(taildata_path)
    if taildata.get("game") != profile.game_id:
        raise ModPackageError(
            f"Taildata is for {taildata.get('game')!r}, not {profile.game_id!r}"
        )
    records = taildata.get("files", {})

    source_files = [
        path
        for path in source_folder.rglob("*")
        if path.is_file()
        and path.name != TAILDATA_FILENAME
        and path.suffix.lower() not in {".con1p", ".con2p"}
    ]

    manifest_entries: list[dict] = []
    payloads: list[bytes] = []
    seen_paths: set[str] = set()
    total = len(source_files)

    for index, file_path in enumerate(source_files, start=1):
        relative_path = None
        for candidate in candidate_relative_paths(file_path, source_folder, taildata_root):
            if candidate in records:
                relative_path = candidate
                break

        if relative_path is None or relative_path in seen_paths:
            if progress:
                progress(index, total, f"Skipped {file_path.name}")
            continue

        record = records[relative_path]
        file_data = file_path.read_bytes()
        payload = (
            make_conception_gzip_payload(file_data)
            if record.get("compressed")
            else file_data
        )
        payloads.append(payload)
        seen_paths.add(relative_path)

        manifest_entries.append(
            {
                "path": relative_path,
                "container": record["container"],
                "toc_offset": int(record["toc_offset"]),
                "original_stored_offset": int(record["stored_offset"]),
                "original_stored_size": int(record["stored_size"]),
                "compressed": bool(record.get("compressed")),
                "unpacked_size": len(file_data),
                "payload_size": len(payload),
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        if progress:
            progress(index, total, f"Packed {relative_path}")

    if not manifest_entries:
        raise ModPackageError(
            "No selected files matched the unpack taildata. Select an unpacked folder "
            "or provide the matching taildata manifest."
        )

    image_records, image_blobs = build_image_records(image_paths or [])
    audio_record, audio_blob = build_audio_record(audio_path)

    if output_path.suffix.lower() != profile.package_extension:
        output_path = output_path.with_suffix(profile.package_extension)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    package_manifest = {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "game": profile.game_id,
        "game_label": profile.label,
        "name": name,
        "author": author,
        "mod_version": version,
        "genre": genre,
        "description": description,
        "created_utc": utc_now(),
        "source_folder": str(source_folder),
        "taildata_path": str(taildata_path),
        "entries": manifest_entries,
        "images": image_records,
        "audio": audio_record,
    }

    header_data = json.dumps(package_manifest, indent=2).encode("utf-8")
    with output_path.open("wb") as file_obj:
        file_obj.write(PACKAGE_MAGIC)
        file_obj.write(HEADER_SIZE_STRUCT.pack(len(header_data)))
        file_obj.write(header_data)
        for payload in payloads:
            file_obj.write(payload)
        for image_blob in image_blobs:
            file_obj.write(image_blob)
        if audio_blob:
            file_obj.write(audio_blob)

    if progress:
        progress(len(manifest_entries), len(manifest_entries), f"Created {output_path.name}")

    return {
        "package_path": str(output_path),
        "entries": len(manifest_entries),
        "images": len(image_records),
        "has_audio": audio_record is not None,
        "game": profile.game_id,
    }
