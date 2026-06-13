from __future__ import annotations

import json, shutil, subprocess
import tkinter as tk
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox

from .audio import WinMemoryAudioPlayer
from .mod_manager import apply_mod_package, disable_all_mods, disable_mod, list_enabled_mods
from .mod_package import (
    GENRES,
    ModPackageError,
    read_package_audio,
    read_package_images,
    read_package_manifest,
)
from .profiles import GAME_PROFILES, get_profile


try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageTk = None
    PIL_AVAILABLE = False


MANAGER_WIDTH = 1600
MANAGER_HEIGHT = 900
LEFT_WIDTH = 250
RIGHT_WIDTH = 360
TOP_HEIGHT = 82
STATUS_HEIGHT = 30

BG = "#120d1c"
BG_ALT = "#171020"
PANEL = "#1d1529"
PANEL_SOFT = "#2a203a"
FIELD = "#0d0a14"
TEXT = "#fff7ff"
TEXT_MUTED = "#d8c8f2"
ACCENT = "#e8c55b"
ACCENT_ALT = "#d89adf"
DANGER = "#d36d93"
OK = "#8ff0b4"
SHELF_DARK = "#1a1224"
SHELF_WOOD = "#3a241e"
SHELF_EDGE = "#7e573e"
BOOK_EDGE = "#ead7b5"
BOOK_PURPLE = "#684f8d"
BOOK_DAMAGED = "#7b465b"
BOOK_ENABLED = "#8a619d"
SELECTION = "#eadcff"

SETTINGS_FILENAME = "conception_toolkit_settings.json"
LIBRARY_FOLDER = "Mods"
ARCHIVE_TITLE = "Conception Arcane Royal Archive"

SHELF_GENRES = [
    "Gameplay",
    "Visual",
    "Audio",
    "User Interface",
    "Restoration",
    "Balance",
    "Experimental",
    "Miscellaneous",
    "Quarantine",
]

WORLD_LEFT = 0
SHELF_WIDTH = 980
SHELF_HEIGHT = 86
SHELF_GAP = 110
SHELF_TOP = 20
SHELF_POST_WIDTH = 10
SHELF_LABEL_WIDTH = 250
SHELF_LABEL_HEIGHT = 24
BOOK_WIDTH = 48
BOOK_HEIGHT = 142
BOOK_GAP = 18
BOOK_START_X = 54
BOOK_TEXT_ZOOM = 0.75
MIN_ZOOM = 0.35
MAX_ZOOM = 2.2
PREVIEW_WIDTH = 330
PREVIEW_HEIGHT = 210


@dataclass
class ArchiveVolume:
    package_path: Path
    filename: str
    title: str
    game: str
    game_label: str
    author: str
    version: str
    genre: str
    description: str
    entries: int
    status: str
    image_count: int
    has_audio: bool
    manifest: dict = field(default_factory=dict)
    parse_error: str = ""
    x: float = 0.0
    y: float = 0.0
    width: float = BOOK_WIDTH
    height: float = BOOK_HEIGHT


def shorten_path(path: Path, max_chars: int = 48) -> str:
    text = str(path)
    if len(text) <= max_chars:
        return text
    return "..." + text[-(max_chars - 3) :]


def load_settings(project_root: Path) -> dict:
    settings_path = project_root / SETTINGS_FILENAME
    default_settings = {
        "library_folder": str(project_root / LIBRARY_FOLDER),
        "game_roots": {
            "con1": str(project_root / "c1"),
            "con2": str(project_root / "c2"),
        },
    }
    if not settings_path.exists():
        return default_settings
    try:
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_settings
    default_settings["library_folder"] = loaded.get(
        "library_folder", default_settings["library_folder"]
    )
    default_settings["game_roots"].update(loaded.get("game_roots", {}))
    return default_settings


def save_settings(project_root: Path, settings: dict):
    settings_path = project_root / SETTINGS_FILENAME
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


class ArchiveManagerWindow(tk.Toplevel):
    def __init__(self, master, project_root: Path, initial_game: str = "con2"):
        super().__init__(master)
        self.project_root = Path(project_root)
        self.game_id = initial_game if initial_game in GAME_PROFILES else "con2"
        self.profile = get_profile(self.game_id)
        self.settings = load_settings(self.project_root)
        self.library_folder = Path(self.settings["library_folder"])
        self.library_folder.mkdir(parents=True, exist_ok=True)

        self.volumes: list[ArchiveVolume] = []
        self.selected_volume: ArchiveVolume | None = None
        self.current_images: list[bytes] = []
        self.current_audio: bytes | None = None
        self.image_index = 0
        self.preview_photo = None
        self.audio_player = WinMemoryAudioPlayer()
        self.audio_enabled = tk.BooleanVar(value=True)
        self.status_filter = tk.StringVar(value="all")
        self.genre_filter = tk.StringVar(value="all")
        self.search_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Archive ready.")

        self.view_x = -80.0
        self.view_y = -10.0
        self.zoom = 0.88
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_view_x = 0.0
        self.drag_view_y = 0.0
        self.render_pending = False
        self.search_after_id = None
        self.book_items: dict[int, ArchiveVolume] = {}

        self.title(ARCHIVE_TITLE)
        self.geometry(f"{MANAGER_WIDTH}x{MANAGER_HEIGHT}")
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close_window)

        self.build_ui()
        self.rescan_archive()

    def build_ui(self):
        self.top_bar = tk.Frame(self, bg=BG_ALT, height=TOP_HEIGHT)
        self.top_bar.pack(side="top", fill="x")
        self.top_bar.pack_propagate(False)

        tk.Label(
            self.top_bar,
            text=f"Arcane Royal Archive, {self.profile.short_label} Mod Manager",
            bg=BG_ALT,
            fg=TEXT,
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=14)

        top_buttons = [
            ("Import Volumes", self.import_volumes),
            ("Rescan Archive", self.rescan_archive),
            ("Open Library", self.open_library_folder),
            ("Overview", self.focus_overview),
        ]
        for text, command in top_buttons:
            self.make_button(self.top_bar, text, command).pack(side="left", padx=5)

        tk.Label(self.top_bar, text="Search", bg=BG_ALT, fg=TEXT_MUTED).pack(side="left", padx=(16, 6))
        self.search_entry = tk.Entry(
            self.top_bar,
            textvariable=self.search_var,
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=24,
        )
        self.search_entry.pack(side="left", ipady=6)
        self.search_entry.bind("<Return>", self.focus_search_match)
        self.search_var.trace_add("write", self.on_search_change)

        tk.Label(self.top_bar, text="Genre", bg=BG_ALT, fg=TEXT_MUTED).pack(side="left", padx=(14, 6))
        genre_menu = tk.OptionMenu(self.top_bar, self.genre_filter, "all", *SHELF_GENRES, command=lambda value: self.request_canvas_render())
        genre_menu.configure(bg=FIELD, fg=TEXT, relief="flat", highlightthickness=0, activebackground=ACCENT, width=14)
        genre_menu.pack(side="left")

        for label, value in [
            ("All", "all"),
            ("Enabled", "enabled"),
            ("Available", "available"),
            ("Damaged", "damaged"),
        ]:
            tk.Radiobutton(
                self.top_bar,
                text=label,
                variable=self.status_filter,
                value=value,
                command=self.request_canvas_render,
                bg=BG_ALT,
                fg=TEXT,
                activebackground=BG_ALT,
                activeforeground=TEXT,
                selectcolor=PANEL_SOFT,
                bd=0,
                highlightthickness=0,
            ).pack(side="left", padx=(12, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(side="top", fill="both", expand=True)

        self.left_panel = tk.Frame(body, bg=PANEL, width=LEFT_WIDTH)
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)
        self.build_left_panel()

        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.start_canvas_drag)
        self.canvas.bind("<B1-Motion>", self.drag_canvas)
        self.canvas.bind("<ButtonRelease-1>", self.finish_canvas_drag)
        self.canvas.bind("<Double-Button-1>", self.center_selected_volume)
        self.canvas.bind("<MouseWheel>", self.zoom_canvas)
        self.canvas.bind("<Configure>", self.request_canvas_render)

        self.right_panel = tk.Frame(body, bg=BG_ALT, width=RIGHT_WIDTH)
        self.right_panel.pack(side="right", fill="y")
        self.right_panel.pack_propagate(False)
        self.build_right_panel()

        self.status_bar = tk.Label(
            self,
            textvariable=self.status_var,
            bg=BG_ALT,
            fg=OK,
            anchor="w",
            font=("Segoe UI", 9),
        )
        self.status_bar.pack(side="bottom", fill="x", ipady=4)

    def build_left_panel(self):
        tk.Label(
            self.left_panel,
            text="Archivist Controls",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", padx=14, pady=(20, 8))

        tk.Label(
            self.left_panel,
            text=(
                "Drag to pan, wheel to zoom, and double click a selected book to center it."
            ),
            bg=PANEL,
            fg=TEXT_MUTED,
            justify="left",
            wraplength=210,
        ).pack(anchor="w", padx=14)

        for text, command in [
            ("Apply Selected", self.apply_selected_volume),
            ("Disable Selected", self.disable_selected_volume),
            (f"Disable All {self.profile.short_label}", self.disable_all_current_game),
            ("Reveal Selected", self.reveal_selected_volume),
        ]:
            self.make_button(self.left_panel, text, command).pack(fill="x", padx=38, pady=(12, 0))

        self.make_separator(self.left_panel)
        tk.Label(self.left_panel, text="Game Root", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14)
        self.root_labels: dict[str, tk.Label] = {}
        tk.Label(self.left_panel, text=self.profile.short_label, bg=PANEL, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
        root_label = tk.Label(
            self.left_panel,
            text=shorten_path(Path(self.settings["game_roots"][self.game_id]), 34),
            bg=PANEL,
            fg=TEXT_MUTED,
            wraplength=210,
            justify="left",
        )
        root_label.pack(anchor="w", padx=14, pady=(4, 0))
        self.root_labels[self.game_id] = root_label
        self.make_button(self.left_panel, "Set Game Root", self.set_game_root).pack(anchor="w", padx=14, pady=(6, 0))

        self.make_separator(self.left_panel)
        tk.Label(self.left_panel, text="Library", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14)
        self.library_label = tk.Label(
            self.left_panel,
            text=shorten_path(self.library_folder, 34),
            bg=PANEL,
            fg=TEXT_MUTED,
            wraplength=210,
            justify="left",
        )
        self.library_label.pack(anchor="w", padx=14, pady=(4, 0))

    def build_right_panel(self):
        tk.Label(
            self.right_panel,
            text="Catalogue Entry",
            bg=BG_ALT,
            fg=TEXT,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", padx=14, pady=(20, 8))
        self.title_label = tk.Label(
            self.right_panel,
            text="No volume selected",
            bg=BG_ALT,
            fg=TEXT,
            font=("Segoe UI", 13, "bold"),
            wraplength=330,
            justify="left",
        )
        self.title_label.pack(anchor="w", padx=14)
        self.meta_label = tk.Label(
            self.right_panel,
            text="",
            bg=BG_ALT,
            fg=TEXT_MUTED,
            justify="left",
            wraplength=330,
        )
        self.meta_label.pack(anchor="w", padx=14, pady=(12, 8))

        self.preview_canvas = tk.Canvas(
            self.right_panel,
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            bg=FIELD,
            highlightthickness=1,
            highlightbackground=PANEL_SOFT,
        )
        self.preview_canvas.pack(padx=14, pady=(8, 4))
        nav = tk.Frame(self.right_panel, bg=BG_ALT)
        nav.pack(fill="x", padx=14)
        self.make_button(nav, "< Prev", lambda: self.cycle_image(-1), width=8).pack(side="left")
        self.image_count_label = tk.Label(nav, text="0 / 0", bg=BG_ALT, fg=TEXT, width=10)
        self.image_count_label.pack(side="left", padx=8)
        self.make_button(nav, "Next >", lambda: self.cycle_image(1), width=8).pack(side="left")
        tk.Checkbutton(
            nav,
            text="Audio",
            variable=self.audio_enabled,
            command=self.refresh_audio_state,
            bg=BG_ALT,
            fg=TEXT,
            activebackground=BG_ALT,
            activeforeground=TEXT,
            selectcolor=PANEL_SOFT,
            bd=0,
            highlightthickness=0,
        ).pack(side="right")

        tk.Label(self.right_panel, text="Description", bg=BG_ALT, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(18, 6))
        self.description_text = tk.Text(
            self.right_panel,
            height=9,
            bg=FIELD,
            fg=TEXT,
            relief="flat",
            wrap="word",
            font=("Segoe UI", 9),
        )
        self.description_text.pack(fill="x", padx=14)
        self.description_text.configure(state="disabled")

        notes = tk.Frame(self.right_panel, bg=BG_ALT, highlightthickness=1, highlightbackground=PANEL_SOFT)
        notes.pack(fill="x", padx=14, pady=(16, 0))
        tk.Label(notes, text="Archive Notes", bg=BG_ALT, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        tk.Label(
            notes,
            text="Enabled books glow and sit slightly forward.\nUnreadable books are confined to the Quarantine shelf.",
            bg=BG_ALT,
            fg=TEXT_MUTED,
            justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 10))
        self.draw_empty_preview()

    def make_button(self, parent, text, command, width=None):
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=PANEL_SOFT,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="#151018",
            relief="flat",
            width=width,
            padx=10,
            pady=8,
        )
        return button

    def make_separator(self, parent):
        tk.Frame(parent, bg=TEXT_MUTED, height=1).pack(fill="x", padx=14, pady=18)

    def make_option_row(self, parent, label, variable, values):
        tk.Label(parent, text=label, bg=PANEL, fg=TEXT_MUTED).pack(anchor="w", padx=14, pady=(8, 2))
        option = tk.OptionMenu(parent, variable, *values, command=lambda value: self.request_canvas_render())
        option.configure(bg="#dedbd2", fg="#111111", relief="flat", width=18)
        option.pack(anchor="w", padx=14)

    def set_status(self, text: str, color: str = OK):
        self.status_var.set(text)
        self.status_bar.configure(fg=color)

    def visible_volumes(self) -> list[ArchiveVolume]:
        search_text = self.search_var.get().strip().lower()
        status_filter = self.status_filter.get()
        genre_filter = self.genre_filter.get()
        visible: list[ArchiveVolume] = []
        for volume in self.volumes:
            if status_filter != "all" and volume.status.lower() != status_filter:
                continue
            if genre_filter != "all" and volume.genre != genre_filter:
                continue
            if search_text and search_text not in volume.title.lower() and search_text not in volume.filename.lower():
                continue
            visible.append(volume)
        return visible

    def rescan_archive(self):
        selected_filename = self.selected_volume.filename if self.selected_volume else None
        self.volumes = []
        enabled_names = self.enabled_mod_names()
        package_paths = list(self.library_folder.glob(f"*{self.profile.package_extension}"))

        for package_path in sorted(package_paths, key=lambda item: item.name.lower()):
            try:
                manifest = read_package_manifest(package_path)
                game_id = manifest.get("game", "")
                if game_id != self.game_id:
                    raise ModPackageError(
                        f"Volume is for {game_id or 'unknown'}, not {self.profile.short_label}"
                    )
                title = manifest.get("name") or package_path.stem
                genre = manifest.get("genre") or "Miscellaneous"
                if genre not in SHELF_GENRES:
                    genre = "Miscellaneous"
                enabled = package_path.name in enabled_names
                status = "Enabled" if enabled else "Available"
                volume = ArchiveVolume(
                    package_path=package_path,
                    filename=package_path.name,
                    title=title,
                    game=game_id,
                    game_label=self.profile.label,
                    author=manifest.get("author", "Unknown"),
                    version=manifest.get("mod_version", "1"),
                    genre=genre,
                    description=manifest.get("description", ""),
                    entries=len(manifest.get("entries", [])),
                    status=status,
                    image_count=len(manifest.get("images", [])),
                    has_audio=bool(manifest.get("audio")),
                    manifest=manifest,
                )
            except Exception as exc:
                volume = ArchiveVolume(
                    package_path=package_path,
                    filename=package_path.name,
                    title=package_path.stem,
                    game="unknown",
                    game_label="Unknown",
                    author="Unknown",
                    version="Unknown",
                    genre="Quarantine",
                    description="No description available.",
                    entries=0,
                    status="Damaged",
                    image_count=0,
                    has_audio=False,
                    manifest={},
                    parse_error=str(exc),
                )
            self.volumes.append(volume)

        self.layout_volumes()
        self.request_canvas_render()
        self.update_stats()
        match = next((volume for volume in self.volumes if volume.filename == selected_filename), None)
        if match:
            self.select_volume(match, focus=False)
        else:
            self.clear_selection()

    def enabled_mod_names(self) -> set[str]:
        try:
            game_root = Path(self.settings["game_roots"][self.game_id])
            return {mod["id"] for mod in list_enabled_mods(self.profile, game_root)}
        except Exception:
            return set()

    def layout_volumes(self):
        genre_counts = {genre: 0 for genre in SHELF_GENRES}
        for volume in self.volumes:
            genre = volume.genre if volume.genre in SHELF_GENRES else "Miscellaneous"
            if volume.status == "Damaged":
                genre = "Quarantine"
                volume.genre = genre
            index = genre_counts[genre]
            genre_counts[genre] += 1
            shelf_index = SHELF_GENRES.index(genre)
            volume.x = WORLD_LEFT + BOOK_START_X + index * (BOOK_WIDTH + BOOK_GAP)
            volume.y = SHELF_TOP + shelf_index * SHELF_GAP + SHELF_HEIGHT - BOOK_HEIGHT - 8
            volume.width = BOOK_WIDTH
            volume.height = BOOK_HEIGHT

    def update_stats(self):
        enabled_count = sum(1 for volume in self.volumes if volume.status == "Enabled")
        damaged_count = sum(1 for volume in self.volumes if volume.status == "Damaged")
        self.set_status(
            f"Archive refreshed. {len(self.volumes)} volume(s), {enabled_count} enabled, {damaged_count} damaged.",
            OK,
        )

    def request_canvas_render(self, event=None):
        if self.render_pending:
            return
        self.render_pending = True
        self.after(16, self.render_library_canvas)

    def render_library_canvas(self):
        self.render_pending = False
        self.canvas.delete("library")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        self.canvas.create_rectangle(0, 0, width, height, fill=BG, outline="", tags="library")
        self.book_items.clear()

        for shelf_index, genre in enumerate(SHELF_GENRES):
            shelf_y = SHELF_TOP + shelf_index * SHELF_GAP
            self.draw_shelf(genre, shelf_y)

        for volume in self.visible_volumes():
            self.draw_book(volume)

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.view_x) * self.zoom, (y - self.view_y) * self.zoom

    def screen_to_world(self, x: float, y: float) -> tuple[float, float]:
        return x / self.zoom + self.view_x, y / self.zoom + self.view_y

    def draw_shelf(self, genre: str, shelf_y: float):
        x1, y1 = self.world_to_screen(WORLD_LEFT, shelf_y)
        x2, y2 = self.world_to_screen(WORLD_LEFT + SHELF_WIDTH, shelf_y + SHELF_HEIGHT)
        post_width = SHELF_POST_WIDTH * self.zoom
        label_x1, label_y1 = self.world_to_screen(WORLD_LEFT + 340, shelf_y + 4)
        label_x2, label_y2 = self.world_to_screen(WORLD_LEFT + 340 + SHELF_LABEL_WIDTH, shelf_y + SHELF_LABEL_HEIGHT)

        shelf_fill = "#261731" if genre != "Quarantine" else "#2e1728"
        edge = DANGER if genre == "Quarantine" else SHELF_EDGE
        self.canvas.create_rectangle(x1, y1, x2, y2, fill=shelf_fill, outline=PANEL_SOFT, tags="library")
        self.canvas.create_rectangle(x1, y2 - 16 * self.zoom, x2, y2, fill=SHELF_WOOD, outline=edge, tags="library")
        for post_index in range(0, 8):
            post_x = x1 + post_index * ((x2 - x1) / 7)
            self.canvas.create_rectangle(post_x, y1 + 2, post_x + post_width, y2 - 3, fill="#241914", outline=edge, tags="library")
        self.canvas.create_rectangle(label_x1, label_y1, label_x2, label_y2, fill=BG_ALT, outline=ACCENT if genre != "Quarantine" else DANGER, width=2, tags="library")
        self.canvas.create_text((label_x1 + label_x2) / 2, (label_y1 + label_y2) / 2, text=genre, fill=TEXT, font=("Segoe UI", max(8, int(10 * self.zoom)), "bold"), tags="library")

    def draw_book(self, volume: ArchiveVolume):
        x1, y1 = self.world_to_screen(volume.x, volume.y)
        x2, y2 = self.world_to_screen(volume.x + volume.width, volume.y + volume.height)
        book_fill = BOOK_PURPLE
        if volume.status == "Enabled":
            book_fill = BOOK_ENABLED
            y1 -= 8 * self.zoom
            y2 -= 8 * self.zoom
        if volume.status == "Damaged":
            book_fill = BOOK_DAMAGED

        item = self.canvas.create_rectangle(x1, y1, x2, y2, fill=book_fill, outline=BOOK_EDGE, width=2, tags="library")
        self.book_items[item] = volume
        self.canvas.create_rectangle(x2 - 9 * self.zoom, y1 + 8 * self.zoom, x2 - 2 * self.zoom, y2 - 8 * self.zoom, fill=BOOK_EDGE, outline="", tags="library")
        self.canvas.create_rectangle(x1 + 3 * self.zoom, y1 + 15 * self.zoom, x2 - 8 * self.zoom, y1 + 30 * self.zoom, fill=ACCENT_ALT, outline="", tags="library")
        if volume == self.selected_volume:
            self.canvas.create_rectangle(x1 - 9, y1 - 9, x2 + 9, y2 + 9, outline=SELECTION, width=2, tags="library")
        if self.zoom >= BOOK_TEXT_ZOOM:
            display = volume.title if len(volume.title) <= 26 else volume.title[:23] + "..."
            self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=display, fill=TEXT, font=("Segoe UI", max(8, int(9 * self.zoom)), "bold"), angle=90, tags="library")
        self.canvas.tag_bind(item, "<Button-1>", lambda event, selected=volume: self.select_volume(selected))

    def start_canvas_drag(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.drag_view_x = self.view_x
        self.drag_view_y = self.view_y

    def drag_canvas(self, event):
        dx = (event.x - self.drag_start_x) / self.zoom
        dy = (event.y - self.drag_start_y) / self.zoom
        self.view_x = self.drag_view_x - dx
        self.view_y = self.drag_view_y - dy
        self.request_canvas_render()

    def finish_canvas_drag(self, event):
        world_x, world_y = self.screen_to_world(event.x, event.y)
        for volume in reversed(self.visible_volumes()):
            if volume.x <= world_x <= volume.x + volume.width and volume.y <= world_y <= volume.y + volume.height:
                self.select_volume(volume, focus=False)
                break

    def zoom_canvas(self, event):
        old_zoom = self.zoom
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        if new_zoom == old_zoom:
            return
        world_x, world_y = self.screen_to_world(event.x, event.y)
        self.zoom = new_zoom
        self.view_x = world_x - event.x / self.zoom
        self.view_y = world_y - event.y / self.zoom
        self.request_canvas_render()

    def focus_volume(self, volume: ArchiveVolume, zoom: float | None = None):
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        if zoom is not None:
            self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        center_x = volume.x + volume.width / 2
        center_y = volume.y + volume.height / 2
        self.view_x = center_x - canvas_width / (2 * self.zoom)
        self.view_y = center_y - canvas_height / (2 * self.zoom)
        self.request_canvas_render()

    def center_selected_volume(self, event=None):
        if self.selected_volume:
            self.focus_volume(self.selected_volume, zoom=max(self.zoom, 1.0))

    def focus_overview(self):
        self.view_x = -120
        self.view_y = -20
        self.zoom = 0.78
        self.request_canvas_render()

    def on_search_change(self, name=None, index=None, mode=None):
        self.request_canvas_render()
        if self.search_after_id is not None:
            self.after_cancel(self.search_after_id)
        self.search_after_id = self.after(240, self.perform_search_focus)

    def perform_search_focus(self):
        self.search_after_id = None
        if not self.search_var.get().strip():
            return
        matches = self.visible_volumes()
        if len(matches) == 1:
            self.select_volume(matches[0], focus=True)

    def focus_search_match(self, event=None):
        matches = self.visible_volumes()
        if not matches:
            self.set_status("No matching volume found.", DANGER)
            return
        self.select_volume(matches[0], focus=True)

    def select_volume(self, volume: ArchiveVolume, focus: bool = True):
        self.selected_volume = volume
        self.current_images = []
        self.current_audio = None
        self.image_index = 0
        self.title_label.configure(text=volume.title)
        meta_lines = [
            f"File: {volume.filename}",
            f"Entries: {volume.entries}",
            f"Game: {volume.game_label}",
            f"Genre: {volume.genre}",
            f"Author: {volume.author}",
            f"Version: {volume.version}",
            f"Status: {volume.status}",
        ]
        if volume.manifest.get("entries"):
            meta_lines.append(f"Primary Container: {volume.manifest['entries'][0].get('container')}")
        if volume.parse_error:
            meta_lines.append(f"Parse Note: {volume.parse_error}")
        self.meta_label.configure(text="\n".join(meta_lines))
        self.description_text.configure(state="normal")
        self.description_text.delete("1.0", "end")
        self.description_text.insert("1.0", volume.description or "No description available.")
        self.description_text.configure(state="disabled")

        if not volume.parse_error:
            try:
                self.current_images = read_package_images(volume.package_path, volume.manifest)
                self.current_audio = read_package_audio(volume.package_path, volume.manifest)
            except ModPackageError as exc:
                self.current_images = []
                self.current_audio = None
                self.set_status(str(exc), DANGER)
        self.update_image_display()
        self.refresh_audio_state()
        if focus:
            self.focus_volume(volume, zoom=max(self.zoom, 1.0))
        else:
            self.request_canvas_render()

    def clear_selection(self):
        self.selected_volume = None
        self.current_images = []
        self.current_audio = None
        self.image_index = 0
        self.stop_audio()
        self.title_label.configure(text="No volume selected")
        self.meta_label.configure(text="")
        self.description_text.configure(state="normal")
        self.description_text.delete("1.0", "end")
        self.description_text.configure(state="disabled")
        self.draw_empty_preview()
        self.request_canvas_render()

    def draw_empty_preview(self):
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(PREVIEW_WIDTH / 2, PREVIEW_HEIGHT / 2, text="No preview", fill=TEXT_MUTED, font=("Segoe UI", 10))
        self.image_count_label.configure(text="0 / 0")

    def update_image_display(self):
        if not self.current_images:
            self.draw_empty_preview()
            return
        self.image_index %= len(self.current_images)
        image_data = self.current_images[self.image_index]
        self.preview_canvas.delete("all")
        if PIL_AVAILABLE:
            try:
                image = Image.open(BytesIO(image_data)).convert("RGB")
                image = image.resize((PREVIEW_WIDTH, PREVIEW_HEIGHT))
                self.preview_photo = ImageTk.PhotoImage(image)
                self.preview_canvas.create_image(0, 0, anchor="nw", image=self.preview_photo)
            except Exception as exc:
                self.preview_canvas.create_text(PREVIEW_WIDTH / 2, PREVIEW_HEIGHT / 2, text=f"Preview error\n{exc}", fill=DANGER, justify="center")
        else:
            self.preview_canvas.create_text(PREVIEW_WIDTH / 2, PREVIEW_HEIGHT / 2, text="Pillow is needed for scaled previews", fill=DANGER, justify="center")
        self.image_count_label.configure(text=f"{self.image_index + 1} / {len(self.current_images)}")

    def cycle_image(self, delta: int):
        if not self.current_images:
            return
        self.image_index = (self.image_index + delta) % len(self.current_images)
        self.update_image_display()

    def refresh_audio_state(self):
        if not self.selected_volume:
            return
        if not self.current_audio:
            self.stop_audio()
            return
        if not self.audio_enabled.get():
            self.stop_audio()
            return
        if not self.audio_player.play_loop_bytes(self.current_audio):
            self.set_status("Embedded audio is unavailable or not a WAV.", DANGER)

    def stop_audio(self):
        self.audio_player.stop()

    def import_volumes(self):
        paths = filedialog.askopenfilenames(
            title="Import Conception mod volumes",
            filetypes=[
                (f"{self.profile.short_label} Packages", f"*{self.profile.package_extension}"),
                ("All Files", "*.*"),
            ],
        )
        if not paths:
            return
        for path_text in paths:
            source = Path(path_text)
            target = self.library_folder / source.name
            if source.resolve() == target.resolve():
                continue
            shutil.copy2(source, target)
        self.rescan_archive()

    def open_library_folder(self):
        folder = filedialog.askdirectory(initialdir=self.library_folder, title="Select archive library folder")
        if not folder:
            return
        self.library_folder = Path(folder)
        self.library_folder.mkdir(parents=True, exist_ok=True)
        self.settings["library_folder"] = str(self.library_folder)
        save_settings(self.project_root, self.settings)
        self.library_label.configure(text=shorten_path(self.library_folder, 34))
        self.rescan_archive()

    def set_game_root(self):
        folder = filedialog.askdirectory(
            initialdir=self.settings["game_roots"].get(self.game_id, str(self.project_root)),
            title=f"Select {self.profile.short_label} CFSI folder",
        )
        if not folder:
            return
        self.settings["game_roots"][self.game_id] = folder
        save_settings(self.project_root, self.settings)
        self.root_labels[self.game_id].configure(text=shorten_path(Path(folder), 34))
        self.rescan_archive()

    def apply_selected_volume(self):
        volume = self.selected_volume
        if not volume:
            messagebox.showinfo("Apply Volume", "Select a volume first.")
            return
        if volume.parse_error or volume.status == "Damaged":
            messagebox.showerror("Apply Volume", "Damaged volumes cannot be applied.")
            return
        game_root = Path(self.settings["game_roots"][self.game_id])
        try:
            result = apply_mod_package(self.profile, game_root, volume.package_path)
        except Exception as exc:
            messagebox.showerror("Apply Failed", str(exc))
            return
        self.set_status(f"Enabled {result['mod_id']} with {result['entries']} patched files.", OK)
        self.rescan_archive()

    def disable_selected_volume(self):
        volume = self.selected_volume
        if not volume:
            messagebox.showinfo("Disable Volume", "Select a volume first.")
            return
        game_root = Path(self.settings["game_roots"][self.game_id])
        try:
            result = disable_mod(self.profile, game_root, volume.filename)
        except Exception as exc:
            messagebox.showerror("Disable Failed", str(exc))
            return
        self.set_status(f"Disabled {result['mod_id']} and restored {result['restored_entries']} entries.", OK)
        self.rescan_archive()

    def disable_all_current_game(self):
        if not messagebox.askyesno("Disable All", f"Disable all {self.profile.short_label} mods and truncate containers?"):
            return
        try:
            result = disable_all_mods(self.profile, Path(self.settings["game_roots"][self.game_id]))
        except Exception as exc:
            messagebox.showerror("Disable All Failed", str(exc))
            return
        self.set_status(f"Disabled {result['disabled_mods']} {self.profile.short_label} mods.", OK)
        self.rescan_archive()

    def reveal_selected_volume(self):
        if not self.selected_volume:
            return
        try:
            subprocess.Popen(["explorer", f"/select,{self.selected_volume.package_path}"])
        except OSError as exc:
            messagebox.showerror("Reveal Failed", str(exc))

    def close_window(self):
        self.stop_audio()
        self.destroy()
