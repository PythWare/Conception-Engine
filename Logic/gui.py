from __future__ import annotations

import queue, threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from .archive_manager import ArchiveManagerWindow
from .cfsi import TAILDATA_FILENAME, check_game, unpack_game
from .mod_package import GENRES, MAX_PREVIEW_IMAGES, create_mod_package, find_taildata_for_folder
from .profiles import GAME_PROFILES, GameProfile, get_profile


try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageTk = None
    PIL_AVAILABLE = False


WIDTH = 980
HEIGHT = 620

BG_COLOR = "#1a1a1a"
ACCENT = "#f4b400"
INACTIVE = "#444"
STRIP = "#666"
TEXT = "white"
PANEL_2 = "#555555"
PANEL_3 = "#ffffff"
PANEL_BG = "#0f141b"
PANEL_HEAD = "#1c2734"
FIELD_BG = "#1a212a"
MUTED = "#b8c2ce"
SUCCESS = "#6ecb7f"
ERROR = "#ff7c91"

TITLE = "Conception Engine"

MAIN_BUTTONS = ["Tools", "Guide"]
SUB_OPTIONS = {
    "Tools": ["Conception 1", "Conception II", "Close"],
    "Guide": ["CFSI Guide", "Package Guide", "Close"],
}
SUB_SUB_OPTIONS = {
    "Conception 1": ["Unpack", "Mod Creator", "Mod Manager"],
    "Conception II": ["Unpack", "Mod Creator", "Mod Manager"],
    "CFSI Guide": ["Info", "Credits"],
    "Package Guide": ["Info", "Format"],
}
GAME_BY_SUB = {
    "Conception 1": "con1",
    "Conception II": "con2",
}

MAIN_BUTTON_X = 60
MAIN_BUTTON_Y = 120
MAIN_BUTTON_GAP = 100
MAIN_BUTTON_RADIUS = 30
SUB_STRIP_X = 140
SUB_STRIP_Y = 100
SUB_BUTTON_WIDTH = 180
SUB_BUTTON_HEIGHT = 50
SUB_BUTTON_GAP = 60
ACTION_STRIP_X = 340
ACTION_STRIP_Y = 100
ACTION_BUTTON_WIDTH = 180
ACTION_BUTTON_HEIGHT = 50
ACTION_BUTTON_GAP = 60

PANEL_X = 520
PANEL_Y = 42
PANEL_WIDTH = 420
PANEL_HEIGHT = 600
GUIDE_PANEL_HEIGHT = 330

LOG_HEIGHT = 9
CREATOR_PREVIEW_WIDTH = 160
CREATOR_PREVIEW_HEIGHT = 90


GUIDE_CONTENT = {
    ("CFSI Guide", "Info"): (
        "CFSI Guide",
        "Conception 1 and Conception II share the append and patch idea but their "
        "main CFSI tables use different offsets and directory walks. The selected game "
        "controls which parser and package extension are used.",
    ),
    ("CFSI Guide", "Credits"): (
        "Credits",
        "CFSI reversing and gzip header behavior: Myself (PythWare)",
    ),
    ("Package Guide", "Info"): (
        "Package Guide",
        "Mod packages are custom Conception Arcane volumes. File payloads are packed "
        "for the manager to append with compression decided from conception_taildata.json.",
    ),
    ("Package Guide", "Format"): (
        "Package Format",
        ".con1p and .con2p files store a binary signature, a JSON manifest, CFSI ready "
        "payloads, optional preview image blobs, and optional in-memory WAV audio.",
    ),
}


def shorten_path_smart(path):
    text = str(path)
    if len(text) <= 42:
        return text
    return "..." + text[-39:]


class ConceptionApp:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.ui_state = {"main": None, "sub": None}
        self.panel_state = {
            "visible": False,
            "kind": None,
            "x": PANEL_X,
            "y": PANEL_Y,
            "height": PANEL_HEIGHT,
            "dragging": False,
        }
        self.selected_game = "con2"
        self.main_buttons = []
        self.sub_buttons = []
        self.action_buttons = []
        self.drag_data = {"x": 0, "y": 0}
        self.worker = None
        self.work_queue: queue.Queue = queue.Queue()
        self.manager_window = None
        self.creator_image_paths: list[Path] = []
        self.creator_audio_path: Path | None = None
        self.creator_preview_photo = None

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry(f"{WIDTH}x{HEIGHT}+300+160")
        self.root.wm_attributes("-transparentcolor", BG_COLOR)
        self.root.attributes("-topmost", True)

        self.canvas = tk.Canvas(
            self.root,
            width=WIDTH,
            height=HEIGHT,
            bg=BG_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack()

        self.create_unpack_widgets()
        self.create_creator_widgets()
        self.create_guide_widgets()
        self.bind_events()
        self.redraw_navigation()

    @property
    def profile(self) -> GameProfile:
        return get_profile(self.selected_game)

    def bind_events(self):
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.root.bind("<Button-3>", self.start_window_drag)
        self.root.bind("<B3-Motion>", self.do_window_drag)
        self.root.bind("<Escape>", self.close_app)
        self.root.bind("<F1>", self.toggle_topmost)

    def create_header(self, panel, title, close_command):
        header = tk.Frame(panel, bg=PANEL_HEAD, height=28)
        header.pack(fill="x")
        header.pack_propagate(False)
        label = tk.Label(
            header,
            text=title,
            bg=PANEL_HEAD,
            fg=TEXT,
            font=("Segoe UI", 10, "bold"),
        )
        label.pack(side="left", padx=8)
        close = tk.Button(
            header,
            text="X",
            command=close_command,
            bg="#4a4f57",
            fg=TEXT,
            relief="flat",
            width=3,
            font=("Segoe UI", 8, "bold"),
        )
        close.pack(side="right", padx=4, pady=4)
        for widget in (header, label):
            widget.bind("<Button-1>", self.start_panel_drag)
            widget.bind("<B1-Motion>", self.do_panel_drag)
            widget.bind("<ButtonRelease-1>", self.stop_panel_drag)
        return header

    def create_labeled_entry(self, parent, label, variable, command=None):
        row = tk.Frame(parent, bg=PANEL_BG)
        row.pack(fill="x", padx=8, pady=4)
        tk.Label(row, text=label, bg=PANEL_BG, fg=TEXT, width=12, anchor="w", font=("Segoe UI", 8, "bold")).pack(side="left")
        entry = tk.Entry(row, textvariable=variable, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        entry.pack(side="left", fill="x", expand=True, ipady=3)
        if command:
            tk.Button(row, text="...", command=command, width=3, bg=ACCENT, fg="black", relief="flat").pack(side="left", padx=(5, 0))
        return entry

    def create_panel_button(self, parent, text, command, color=PANEL_2):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=TEXT if color != ACCENT else "black",
            activebackground=ACCENT,
            activeforeground="black",
            relief="flat",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=6,
        )

    def create_unpack_widgets(self):
        panel = tk.Frame(self.root, bg=PANEL_BG)
        self.create_header(panel, "CFSI Unpack", self.hide_panel)
        self.unpack_source_var = tk.StringVar()
        self.unpack_output_var = tk.StringVar()
        self.unpack_status_var = tk.StringVar(value="Select a game and unpack source.")
        self.create_labeled_entry(panel, "CFSI Folder", self.unpack_source_var, self.browse_unpack_source)
        self.create_labeled_entry(panel, "Output", self.unpack_output_var, self.browse_unpack_output)
        row = tk.Frame(panel, bg=PANEL_BG)
        row.pack(fill="x", padx=8, pady=6)
        self.create_panel_button(row, "Check", self.start_check, PANEL_2).pack(side="left", fill="x", expand=True)
        self.create_panel_button(row, "Unpack", self.start_unpack, ACCENT).pack(side="left", fill="x", expand=True, padx=(6, 0))
        tk.Label(panel, textvariable=self.unpack_status_var, bg=PANEL_BG, fg=MUTED, wraplength=PANEL_WIDTH - 30, justify="left").pack(fill="x", padx=8, pady=(0, 4))
        self.unpack_log = tk.Text(
            panel,
            height=LOG_HEIGHT,
            bg=FIELD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("Consolas", 8),
        )
        self.unpack_log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.unpack_panel = panel

    def create_creator_widgets(self):
        panel = tk.Frame(self.root, bg=PANEL_BG)
        self.create_header(panel, "Mod Creator", self.hide_panel)
        body = self.create_creator_scroll_body(panel)
        self.creator_source_var = tk.StringVar()
        self.creator_taildata_var = tk.StringVar()
        self.creator_output_var = tk.StringVar()
        self.creator_name_var = tk.StringVar()
        self.creator_author_var = tk.StringVar(value="Unknown")
        self.creator_version_var = tk.StringVar(value="1")
        self.creator_genre_var = tk.StringVar(value="Miscellaneous")
        self.creator_status_var = tk.StringVar(value="Pack a folder using conception_taildata.json.")

        self.create_labeled_entry(body, "Files", self.creator_source_var, self.browse_creator_source)
        self.create_labeled_entry(body, "Taildata", self.creator_taildata_var, self.browse_creator_taildata)
        self.create_labeled_entry(body, "Package", self.creator_output_var, self.browse_creator_output)
        self.create_labeled_entry(body, "Name", self.creator_name_var)
        self.create_labeled_entry(body, "Author", self.creator_author_var)
        self.create_labeled_entry(body, "Version", self.creator_version_var)

        genre_row = tk.Frame(body, bg=PANEL_BG)
        genre_row.pack(fill="x", padx=8, pady=4)
        tk.Label(genre_row, text="Genre", bg=PANEL_BG, fg=TEXT, width=12, anchor="w", font=("Segoe UI", 8, "bold")).pack(side="left")
        genre_menu = tk.OptionMenu(genre_row, self.creator_genre_var, *GENRES)
        genre_menu.configure(bg=FIELD_BG, fg=TEXT, relief="flat", highlightthickness=0, activebackground=ACCENT)
        genre_menu.pack(side="left", fill="x", expand=True)

        media_row = tk.Frame(body, bg=PANEL_BG)
        media_row.pack(fill="x", padx=8, pady=6)
        left = tk.Frame(media_row, bg=PANEL_BG)
        left.pack(side="left", fill="both", expand=True)
        self.creator_images_list = tk.Listbox(
            left,
            height=4,
            bg=FIELD_BG,
            fg=TEXT,
            relief="flat",
            selectbackground=ACCENT,
            selectforeground="black",
            font=("Consolas", 8),
        )
        self.creator_images_list.pack(fill="both", expand=True)
        self.creator_images_list.bind("<<ListboxSelect>>", self.update_creator_preview_from_selection)
        media_buttons = tk.Frame(left, bg=PANEL_BG)
        media_buttons.pack(fill="x", pady=(4, 0))
        self.create_panel_button(media_buttons, "+ Img", self.add_creator_images).pack(side="left", fill="x", expand=True)
        self.create_panel_button(media_buttons, "- Img", self.remove_creator_image).pack(side="left", fill="x", expand=True, padx=(4, 0))

        right = tk.Frame(media_row, bg=PANEL_BG)
        right.pack(side="left", padx=(8, 0))
        self.creator_preview_canvas = tk.Canvas(
            right,
            width=CREATOR_PREVIEW_WIDTH,
            height=CREATOR_PREVIEW_HEIGHT,
            bg=FIELD_BG,
            highlightthickness=0,
        )
        self.creator_preview_canvas.pack()
        audio_row = tk.Frame(right, bg=PANEL_BG)
        audio_row.pack(fill="x", pady=(4, 0))
        self.create_panel_button(audio_row, "WAV", self.set_creator_audio).pack(side="left", fill="x", expand=True)
        self.create_panel_button(audio_row, "Clear", self.clear_creator_audio).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.creator_audio_label = tk.Label(right, text="No WAV", bg=PANEL_BG, fg=MUTED, wraplength=CREATOR_PREVIEW_WIDTH)
        self.creator_audio_label.pack(fill="x")

        tk.Label(body, text="Description", bg=PANEL_BG, fg=TEXT, anchor="w", font=("Segoe UI", 8, "bold")).pack(fill="x", padx=8)
        self.creator_description = tk.Text(
            body,
            height=5,
            bg=FIELD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("Segoe UI", 8),
        )
        self.creator_description.pack(fill="both", expand=True, padx=8, pady=(2, 6))
        bottom = tk.Frame(body, bg=PANEL_BG)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        self.create_panel_button(bottom, "Create Package", self.start_create_package, ACCENT).pack(side="left")
        tk.Label(bottom, textvariable=self.creator_status_var, bg=PANEL_BG, fg=MUTED, wraplength=240, justify="left").pack(side="left", padx=8)
        self.draw_creator_preview_empty()
        self.creator_panel = panel
        self.bind_creator_mousewheel_tree(panel)

    def create_creator_scroll_body(self, panel):
        shell = tk.Frame(panel, bg=PANEL_BG)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg=PANEL_BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=PANEL_BG)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.creator_scroll_canvas = canvas
        return body

    def bind_creator_mousewheel_tree(self, widget):
        widget.bind("<MouseWheel>", self.on_creator_mousewheel, add="+")
        for child in widget.winfo_children():
            self.bind_creator_mousewheel_tree(child)

    def on_creator_mousewheel(self, event):
        steps = int(-event.delta / 120) if event.delta else 0
        if steps == 0:
            steps = -1 if event.delta > 0 else 1
        self.creator_scroll_canvas.yview_scroll(steps, "units")
        return "break"

    def create_guide_widgets(self):
        panel = tk.Frame(self.root, bg=PANEL_BG)
        self.create_header(panel, "Guide", self.hide_panel)
        self.guide_title_var = tk.StringVar(value="Guide")
        tk.Label(panel, textvariable=self.guide_title_var, bg=PANEL_BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
        self.guide_text = tk.Text(
            panel,
            height=12,
            bg=FIELD_BG,
            fg=TEXT,
            relief="flat",
            wrap="word",
            font=("Segoe UI", 9),
        )
        self.guide_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.guide_text.configure(state="disabled")
        self.guide_panel = panel

    def sync_game_defaults(self):
        profile = self.profile
        self.unpack_source_var.set(str(profile.default_source_dir(self.project_root)))
        self.unpack_output_var.set(str(profile.default_output_dir(self.project_root)))
        current_name = self.creator_name_var.get().strip()
        if not current_name or current_name.startswith("New_con"):
            self.creator_name_var.set(f"New_{profile.game_id}_mod")
        current_output = self.creator_output_var.get().strip()
        output_name = Path(current_output).name if current_output else ""
        if not current_output or output_name.startswith("New_con"):
            self.creator_output_var.set(str(self.project_root / f"New_{profile.game_id}_mod{profile.package_extension}"))

    def draw_title(self):
        self.canvas.create_text(
            WIDTH // 2,
            25,
            text=TITLE,
            fill="#BF98D9",
            font=("Segoe UI", 14, "bold"),
            tags="nav",
        )

    def draw_main(self):
        buttons = []
        for index, name in enumerate(MAIN_BUTTONS):
            x = MAIN_BUTTON_X
            y = MAIN_BUTTON_Y + index * MAIN_BUTTON_GAP
            selected = self.ui_state["main"] == name
            self.canvas.create_oval(
                x - MAIN_BUTTON_RADIUS,
                y - MAIN_BUTTON_RADIUS,
                x + MAIN_BUTTON_RADIUS,
                y + MAIN_BUTTON_RADIUS,
                fill=ACCENT if selected else INACTIVE,
                outline="",
                tags="nav",
            )
            self.canvas.create_text(
                x,
                y,
                text=name[0],
                fill=TEXT,
                font=("Segoe UI", 12, "bold"),
                tags="nav",
            )
            buttons.append((name, (x, y, MAIN_BUTTON_RADIUS)))
        return buttons

    def draw_strip(self):
        if not self.ui_state["main"]:
            return []
        items = SUB_OPTIONS[self.ui_state["main"]]
        buttons = []
        self.canvas.create_rectangle(
            SUB_STRIP_X - 10,
            SUB_STRIP_Y - 10,
            SUB_STRIP_X + SUB_BUTTON_WIDTH + 10,
            SUB_STRIP_Y + len(items) * SUB_BUTTON_GAP,
            fill=PANEL_2,
            outline="",
            tags="nav",
        )
        for index, text in enumerate(items):
            y = SUB_STRIP_Y + index * SUB_BUTTON_GAP
            selected = self.ui_state["sub"] == text
            self.canvas.create_rectangle(
                SUB_STRIP_X,
                y,
                SUB_STRIP_X + SUB_BUTTON_WIDTH,
                y + SUB_BUTTON_HEIGHT,
                fill=ACCENT if selected else STRIP,
                outline="",
                tags="nav",
            )
            self.canvas.create_text(SUB_STRIP_X + SUB_BUTTON_WIDTH / 2, y + SUB_BUTTON_HEIGHT / 2, text=text, fill=TEXT, tags="nav")
            buttons.append((text, (SUB_STRIP_X, y, SUB_STRIP_X + SUB_BUTTON_WIDTH, y + SUB_BUTTON_HEIGHT)))
        return buttons

    def draw_action_strip(self):
        if not self.ui_state["sub"]:
            return []
        items = SUB_SUB_OPTIONS.get(self.ui_state["sub"], [])
        if not items:
            return []
        buttons = []
        self.canvas.create_rectangle(
            ACTION_STRIP_X - 10,
            ACTION_STRIP_Y - 10,
            ACTION_STRIP_X + ACTION_BUTTON_WIDTH + 10,
            ACTION_STRIP_Y + len(items) * ACTION_BUTTON_GAP,
            fill=PANEL_3,
            outline="",
            tags="nav",
        )
        for index, text in enumerate(items):
            y = ACTION_STRIP_Y + index * ACTION_BUTTON_GAP
            self.canvas.create_rectangle(
                ACTION_STRIP_X,
                y,
                ACTION_STRIP_X + ACTION_BUTTON_WIDTH,
                y + ACTION_BUTTON_HEIGHT,
                fill="#dddddd",
                outline="",
                tags="nav",
            )
            self.canvas.create_text(ACTION_STRIP_X + ACTION_BUTTON_WIDTH / 2, y + ACTION_BUTTON_HEIGHT / 2, text=text, fill="black", tags="nav")
            buttons.append((text, (ACTION_STRIP_X, y, ACTION_STRIP_X + ACTION_BUTTON_WIDTH, y + ACTION_BUTTON_HEIGHT)))
        return buttons

    def redraw_navigation(self):
        self.canvas.delete("nav")
        self.draw_title()
        self.main_buttons = self.draw_main()
        self.sub_buttons = self.draw_strip()
        self.action_buttons = self.draw_action_strip()

    def draw_panel_shell(self, panel, height=None):
        self.canvas.delete("panel")
        self.panel_state["visible"] = True
        panel_height = height or PANEL_HEIGHT
        self.panel_state["height"] = panel_height
        x = self.panel_state["x"]
        y = self.panel_state["y"]
        self.canvas.create_rectangle(x, y, x + PANEL_WIDTH, y + panel_height, fill="#202833", outline="", tags="panel")
        self.canvas.create_rectangle(x + 3, y + 3, x + PANEL_WIDTH - 3, y + panel_height - 3, outline="#3a4656", tags="panel")
        self.canvas.create_window(
            x + 6,
            y + 6,
            anchor="nw",
            window=panel,
            width=PANEL_WIDTH - 12,
            height=panel_height - 12,
            tags="panel",
        )

    def hide_panel(self):
        self.panel_state["visible"] = False
        self.panel_state["kind"] = None
        self.canvas.delete("panel")

    def show_unpack_panel(self):
        self.sync_game_defaults()
        self.panel_state["kind"] = "unpack"
        self.unpack_status_var.set(f"{self.profile.label} unpack target ready.")
        self.draw_panel_shell(self.unpack_panel, PANEL_HEIGHT)

    def show_creator_panel(self):
        self.sync_game_defaults()
        self.panel_state["kind"] = "creator"
        self.creator_status_var.set(f"Creating {self.profile.package_extension} for {self.profile.short_label}.")
        self.draw_panel_shell(self.creator_panel, PANEL_HEIGHT)

    def show_guide_panel(self, title, text):
        self.panel_state["kind"] = "guide"
        self.guide_title_var.set(title)
        self.guide_text.configure(state="normal")
        self.guide_text.delete("1.0", "end")
        self.guide_text.insert("1.0", text)
        self.guide_text.configure(state="disabled")
        self.draw_panel_shell(self.guide_panel, GUIDE_PANEL_HEIGHT)

    def point_in_circle(self, x, y, cx, cy, radius):
        return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2

    def point_in_rect(self, x, y, rect):
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def on_left_click(self, event):
        x, y = event.x, event.y
        if y < 50:
            return
        for name, (cx, cy, radius) in self.main_buttons:
            if self.point_in_circle(x, y, cx, cy, radius):
                if self.ui_state["main"] == name:
                    self.ui_state["main"] = None
                    self.ui_state["sub"] = None
                else:
                    self.ui_state["main"] = name
                    self.ui_state["sub"] = None
                self.hide_panel()
                self.redraw_navigation()
                return
        for name, rect in self.sub_buttons:
            if self.point_in_rect(x, y, rect):
                if name == "Close":
                    self.ui_state["sub"] = None
                    self.hide_panel()
                elif self.ui_state["sub"] == name:
                    self.ui_state["sub"] = None
                    self.hide_panel()
                else:
                    self.ui_state["sub"] = name
                    self.hide_panel()
                    if name in GAME_BY_SUB:
                        self.selected_game = GAME_BY_SUB[name]
                        self.sync_game_defaults()
                self.redraw_navigation()
                return
        for name, rect in self.action_buttons:
            if self.point_in_rect(x, y, rect):
                self.handle_action(name)
                return

    def handle_action(self, name):
        sub = self.ui_state["sub"]
        if sub in GAME_BY_SUB:
            self.selected_game = GAME_BY_SUB[sub]
        if name == "Unpack":
            self.show_unpack_panel()
            return
        if name == "Mod Creator":
            self.show_creator_panel()
            return
        if name == "Mod Manager":
            self.open_manager_window()
            return
        guide_key = (sub, name)
        if guide_key in GUIDE_CONTENT:
            title, text = GUIDE_CONTENT[guide_key]
            self.show_guide_panel(title, text)

    def start_window_drag(self, event):
        self.drag_data["x"] = event.x_root
        self.drag_data["y"] = event.y_root

    def do_window_drag(self, event):
        dx = event.x_root - self.drag_data["x"]
        dy = event.y_root - self.drag_data["y"]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")
        self.drag_data["x"] = event.x_root
        self.drag_data["y"] = event.y_root

    def start_panel_drag(self, event):
        self.panel_state["dragging"] = True
        self.panel_state["drag_x_root"] = event.x_root
        self.panel_state["drag_y_root"] = event.y_root

    def do_panel_drag(self, event):
        if not self.panel_state.get("dragging"):
            return
        dx = event.x_root - self.panel_state["drag_x_root"]
        dy = event.y_root - self.panel_state["drag_y_root"]
        self.panel_state["x"] += dx
        self.panel_state["y"] += dy
        self.panel_state["drag_x_root"] = event.x_root
        self.panel_state["drag_y_root"] = event.y_root
        self.canvas.move("panel", dx, dy)

    def stop_panel_drag(self, event):
        self.panel_state["dragging"] = False

    def toggle_topmost(self, event=None):
        current = bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", not current)

    def close_app(self, event=None):
        if self.manager_window and self.manager_window.winfo_exists():
            self.manager_window.close_window()
        self.root.destroy()

    def browse_unpack_source(self):
        path = filedialog.askdirectory(initialdir=self.project_root, title="Select folder with CFSI files")
        if path:
            self.unpack_source_var.set(path)

    def browse_unpack_output(self):
        path = filedialog.askdirectory(initialdir=self.project_root, title="Select output folder")
        if path:
            self.unpack_output_var.set(path)

    def browse_creator_source(self):
        path = filedialog.askdirectory(initialdir=self.project_root, title="Select folder of modded files")
        if not path:
            return
        self.creator_source_var.set(path)
        taildata = find_taildata_for_folder(Path(path))
        if taildata:
            self.creator_taildata_var.set(str(taildata))

    def browse_creator_taildata(self):
        path = filedialog.askopenfilename(
            initialdir=self.project_root,
            title="Select conception taildata",
            filetypes=[("Conception Taildata", f"*{TAILDATA_FILENAME}"), ("JSON", "*.json"), ("All Files", "*.*")],
        )
        if path:
            self.creator_taildata_var.set(path)

    def browse_creator_output(self):
        profile = self.profile
        path = filedialog.asksaveasfilename(
            initialdir=self.project_root,
            defaultextension=profile.package_extension,
            filetypes=[(f"{profile.short_label} Package", f"*{profile.package_extension}"), ("All Files", "*.*")],
        )
        if path:
            self.creator_output_var.set(path)

    def add_creator_images(self):
        paths = filedialog.askopenfilenames(
            title="Select preview images",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.gif;*.bmp"), ("All Files", "*.*")],
        )
        for path_text in paths:
            if len(self.creator_image_paths) >= MAX_PREVIEW_IMAGES:
                break
            path = Path(path_text)
            if path not in self.creator_image_paths:
                self.creator_image_paths.append(path)
                self.creator_images_list.insert("end", path.name)
        if self.creator_image_paths:
            self.draw_creator_preview(self.creator_image_paths[-1])

    def remove_creator_image(self):
        selection = self.creator_images_list.curselection()
        if not selection:
            return
        index = selection[0]
        del self.creator_image_paths[index]
        self.creator_images_list.delete(index)
        if self.creator_image_paths:
            self.draw_creator_preview(self.creator_image_paths[min(index, len(self.creator_image_paths) - 1)])
        else:
            self.draw_creator_preview_empty()

    def update_creator_preview_from_selection(self, event=None):
        selection = self.creator_images_list.curselection()
        if selection:
            self.draw_creator_preview(self.creator_image_paths[selection[0]])

    def draw_creator_preview_empty(self):
        self.creator_preview_canvas.delete("all")
        self.creator_preview_canvas.create_text(CREATOR_PREVIEW_WIDTH / 2, CREATOR_PREVIEW_HEIGHT / 2, text="No Preview", fill=MUTED)

    def draw_creator_preview(self, image_path: Path):
        self.creator_preview_canvas.delete("all")
        if not PIL_AVAILABLE:
            self.creator_preview_canvas.create_text(CREATOR_PREVIEW_WIDTH / 2, CREATOR_PREVIEW_HEIGHT / 2, text="Pillow missing", fill=ERROR)
            return
        try:
            image = Image.open(image_path).convert("RGB")
            image = image.resize((CREATOR_PREVIEW_WIDTH, CREATOR_PREVIEW_HEIGHT))
            self.creator_preview_photo = ImageTk.PhotoImage(image)
            self.creator_preview_canvas.create_image(0, 0, anchor="nw", image=self.creator_preview_photo)
        except Exception as exc:
            self.creator_preview_canvas.create_text(CREATOR_PREVIEW_WIDTH / 2, CREATOR_PREVIEW_HEIGHT / 2, text=str(exc), fill=ERROR)

    def set_creator_audio(self):
        path = filedialog.askopenfilename(title="Select WAV audio", filetypes=[("WAV Audio", "*.wav"), ("All Files", "*.*")])
        if path:
            self.creator_audio_path = Path(path)
            self.creator_audio_label.configure(text=Path(path).name, fg=SUCCESS)

    def clear_creator_audio(self):
        self.creator_audio_path = None
        self.creator_audio_label.configure(text="No WAV", fg=MUTED)

    def open_manager_window(self):
        if self.manager_window and self.manager_window.winfo_exists():
            self.manager_window.lift()
            self.manager_window.focus_force()
            return
        self.manager_window = ArchiveManagerWindow(self.root, self.project_root, self.selected_game)

    def append_unpack_log(self, message):
        self.unpack_log.insert("end", message + "\n")
        self.unpack_log.see("end")

    def progress_callback(self, done, total, message):
        self.work_queue.put(("progress", done, total, message))

    def run_worker(self, title, work, done_handler):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "A task is already running.")
            return

        def runner():
            try:
                result = work()
                self.work_queue.put(("done", title, result, done_handler))
            except Exception as exc:
                self.work_queue.put(("error", title, exc, None))

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()
        self.root.after(80, self.poll_worker)

    def poll_worker(self):
        while True:
            try:
                event = self.work_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                name, done, total, message = event
                self.unpack_status_var.set(f"{done}/{max(1, total)} - {message}")
                self.creator_status_var.set(f"{done}/{max(1, total)} - {message}")
                if self.panel_state["kind"] == "unpack":
                    self.append_unpack_log(message)
            elif kind == "done":
                name, title, result, handler = event
                if handler:
                    handler(result)
            elif kind == "error":
                name, title, exc, handler = event
                messagebox.showerror(title, str(exc))
        if self.worker and self.worker.is_alive():
            self.root.after(80, self.poll_worker)

    def start_check(self):
        profile = self.profile
        source_dir = Path(self.unpack_source_var.get())

        def work():
            return check_game(profile, source_dir)

        def done(summary):
            lines = [f"Check for {profile.label}"]
            for container, data in summary["containers"].items():
                lines.append(
                    f"{container}: {data['entries']} files, {data['compressed_entries']} compressed, {data['bad_entries']} bad"
                )
            text = "\n".join(lines)
            self.append_unpack_log(text)
            self.unpack_status_var.set("Check complete.")

        self.run_worker("Check", work, done)

    def start_unpack(self):
        profile = self.profile
        source_dir = Path(self.unpack_source_var.get())
        output_dir = Path(self.unpack_output_var.get())

        def work():
            return unpack_game(profile, source_dir, output_dir, progress=self.progress_callback)

        def done(result):
            self.unpack_status_var.set(f"Unpacked {result['files']} files. Taildata: {result['taildata_path']}")
            messagebox.showinfo("Unpack Complete", f"Unpacked {result['files']} files.\n{result['taildata_path']}")

        self.run_worker("Unpack", work, done)

    def start_create_package(self):
        profile = self.profile
        source_folder = Path(self.creator_source_var.get())
        output_path = Path(self.creator_output_var.get())
        taildata = Path(self.creator_taildata_var.get()) if self.creator_taildata_var.get().strip() else None
        description = self.creator_description.get("1.0", "end").strip()

        def work():
            return create_mod_package(
                profile,
                source_folder,
                output_path,
                self.creator_name_var.get(),
                description,
                taildata_path=taildata,
                author=self.creator_author_var.get(),
                version=self.creator_version_var.get(),
                genre=self.creator_genre_var.get(),
                image_paths=self.creator_image_paths,
                audio_path=self.creator_audio_path,
                progress=self.progress_callback,
            )

        def done(result):
            self.creator_status_var.set(
                f"Created {result['entries']} files, {result['images']} previews. {result['package_path']}"
            )
            messagebox.showinfo("Package Created", f"Created package:\n{result['package_path']}")

        self.run_worker("Create Package", work, done)

    def run(self):
        self.root.mainloop()


def run_app(project_root: Path | None = None):
    app = ConceptionApp(project_root or Path.cwd())
    app.run()
