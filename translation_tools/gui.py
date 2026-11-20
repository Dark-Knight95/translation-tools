"""A shared Tkinter desktop interface for both translation utilities."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import (BatchResult, Cancelled, Operation, ValidationError, natural_key,
                   parse_shift, path_key, plan_copies, plan_subtitles,
                   read_subtitle, run_batch, shift_subtitles)

BG = "#111820"
PANEL = "#18222d"
FIELD = "#101923"
LINE = "#304152"
FG = "#edf3f7"
MUTED = "#a2b4c4"
ACCENT = "#74dec5"
ACCENT_DARK = "#153f39"
ERROR = "#ffacac"
FONT = "Segoe UI"


def open_folder(folder: str, parent):
    path = Path(folder).expanduser()
    if not path.is_dir():
        messagebox.showwarning("Choose a folder", "Choose an existing output folder first.", parent=parent)
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(path.resolve()))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path.resolve())])
    except OSError as error:
        messagebox.showerror("Could not open folder", str(error), parent=parent)


def make_tree(parent, columns, *, height=6):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[col[0] for col in columns], show="headings",
                        height=height, selectmode="extended")
    for name, title, width in columns:
        tree.heading(name, text=title)
        tree.column(name, width=width, minwidth=65, stretch=True)
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree.tag_configure("error", foreground=ERROR)
    tree.tag_configure("saved", foreground=ACCENT)
    tree.tag_configure("muted", foreground=MUTED)
    return frame, tree


class FileList(ttk.Frame):
    """Ordered files; visible order is the order used for pairing."""
    def __init__(self, parent, title, caption, on_change, *, subtitles=False):
        super().__init__(parent, style="Card.TFrame", padding=10)
        self.files: list[Path] = []
        self.on_change = on_change
        self.subtitles = subtitles
        self.locked = False
        self.controls = []
        header = ttk.Frame(self, style="Card.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text=title, style="CardTitle.TLabel").pack(side="left")
        self.count = ttk.Label(header, text="0 files", style="CardMuted.TLabel")
        self.count.pack(side="right")
        ttk.Label(self, text=caption, style="CardMuted.TLabel").pack(anchor="w", pady=(3, 6))
        frame, self.tree = make_tree(self, [("number", "#", 40), ("file", "Filename", 200)], height=3)
        self.tree.column("number", stretch=False, width=40, minwidth=40)
        frame.pack(fill="both", expand=True)
        buttons = ttk.Frame(self, style="Card.TFrame")
        buttons.pack(fill="x", pady=(6, 0))
        for text, command in [("Add files", self.add), ("Remove", self.remove),
                              ("Clear", self.clear), ("↑", lambda: self.move(-1)),
                              ("↓", lambda: self.move(1)), ("Sort 1–10", self.sort)]:
            button = ttk.Button(buttons, text=text, command=command, style="Small.TButton")
            button.pack(side="left", padx=(0, 4))
            self.controls.append(button)
        self.tree.bind("<Delete>", lambda event: self.remove())
        self.tree.bind("<<TreeviewSelect>>", self.show_path)
        self.path_text = ttk.Label(self, text="No files selected", style="CardMuted.TLabel", anchor="w")
        self.path_text.pack(fill="x", pady=(5, 0))

    def set_locked(self, locked):
        self.locked = locked
        for control in self.controls:
            control.configure(state="disabled" if locked else "normal")

    def refresh(self, selected=()):
        self.tree.delete(*self.tree.get_children())
        for index, path in enumerate(self.files):
            self.tree.insert("", "end", iid=str(index), values=(index + 1, path.name))
        self.count.configure(text=f"{len(self.files)} file{'s' if len(self.files) != 1 else ''}")
        for index in selected:
            if 0 <= index < len(self.files):
                self.tree.selection_add(str(index))
        self.path_text.configure(text=str(self.files[0]) if self.files else "No files selected")
        self.on_change()

    def add(self):
        if self.locked:
            return
        types = [("Subtitles", "*.srt *.ass *.SRT *.ASS"), ("All files", "*.*")] if self.subtitles else [("All files", "*.*")]
        selected = filedialog.askopenfilenames(title="Select subtitle files" if self.subtitles else "Select files", filetypes=types, parent=self)
        self.add_paths(selected)

    def add_paths(self, paths):
        if self.locked:
            return
        known = {path_key(path) for path in self.files}
        for filename in paths:
            path = Path(filename).expanduser().resolve()
            if path_key(path) not in known:
                known.add(path_key(path))
                self.files.append(path)
        self.refresh()

    def remove(self):
        if self.locked:
            return
        selected = {int(item) for item in self.tree.selection()}
        self.files = [path for index, path in enumerate(self.files) if index not in selected]
        self.refresh()

    def clear(self):
        if not self.locked:
            self.files.clear()
            self.refresh()

    def move(self, direction):
        if self.locked:
            return
        selected = sorted(int(item) for item in self.tree.selection())
        if not selected:
            return
        if (direction < 0 and selected[0] == 0) or (direction > 0 and selected[-1] == len(self.files) - 1):
            return
        for index in selected if direction < 0 else reversed(selected):
            self.files[index], self.files[index + direction] = self.files[index + direction], self.files[index]
        self.refresh([index + direction for index in selected])

    def sort(self):
        if not self.locked:
            self.files.sort(key=natural_key)
            self.refresh()

    def show_path(self, event=None):
        selected = self.tree.selection()
        if selected:
            self.path_text.configure(text=str(self.files[int(selected[0])]))


class ToolTab(ttk.Frame):
    """Shared planning, output, progress and background-execution controls."""
    def __init__(self, parent, app):
        super().__init__(parent, padding=(18, 10))
        self.app = app
        self.plan: list[Operation] = []
        self.folder = tk.StringVar()
        self.collision = tk.StringVar(value="Add a number")
        self.status = tk.StringVar(value="Add your files to get started.")
        self.controls = []
        self.file_lists = []
        self.last_result: BatchResult | None = None
        self.folder.trace_add("write", lambda *args: self.invalidate())
        self.collision.trace_add("write", lambda *args: self.invalidate())

    def invalidate(self):
        self.plan = []
        if hasattr(self, "run_button") and not self.app.busy:
            self.run_button.configure(state="disabled")
        if hasattr(self, "preview_tree"):
            self.preview_tree.delete(*self.preview_tree.get_children())
        if hasattr(self, "status") and not self.app.busy:
            self.status.set("Inputs changed. Preview the outputs before running.")

    def output_controls(self):
        card = ttk.Frame(self, style="Card.TFrame", padding=10)
        card.pack(fill="x", pady=(8, 0))
        ttk.Label(card, text="Output folder", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(card, textvariable=self.folder)
        entry.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        browse = ttk.Button(card, text="Browse…", command=self.browse)
        browse.grid(row=1, column=1, padx=(8, 0), pady=(7, 0))
        ttk.Label(card, text="If a name exists", style="CardMuted.TLabel").grid(row=0, column=2, sticky="w", padx=(20, 0))
        combo = ttk.Combobox(card, textvariable=self.collision, state="readonly", width=17,
                             values=["Add a number", "Skip", "Stop and review"])
        combo.grid(row=1, column=2, padx=(20, 0), pady=(7, 0), sticky="ew")
        card.columnconfigure(0, weight=1)
        self.controls += [entry, browse, combo]

    def browse(self):
        selected = filedialog.askdirectory(title="Select output folder", parent=self,
                                           initialdir=self.folder.get() or None)
        if selected:
            self.folder.set(selected)

    def collision_policy(self):
        return {"Add a number": "number", "Skip": "skip", "Stop and review": "error"}[self.collision.get()]

    def footer(self, action_text):
        title_row = ttk.Frame(self)
        title_row.pack(fill="x", pady=(10, 5))
        ttk.Label(title_row, text="OUTPUT PREVIEW", style="Eyebrow.TLabel").pack(side="left")
        self.preview_button = ttk.Button(title_row, text="Preview outputs", command=self.preview)
        self.preview_button.pack(side="right")
        self.controls.append(self.preview_button)
        frame, self.preview_tree = make_tree(self, [("source", "Source", 230), ("output", "Output filename", 260), ("status", "Status", 210)], height=2)
        frame.pack(fill="both", expand=True)
        self.preview_tree.bind("<<TreeviewSelect>>", self.show_destination)
        self.destination_label = ttk.Label(self, text="Your original files stay in place.", style="Muted.TLabel", anchor="w")
        self.destination_label.pack(fill="x", pady=(5, 0))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(8, 0))
        self.run_button = ttk.Button(bar, text=action_text, style="Accent.TButton", command=self.run, state="disabled")
        self.run_button.pack(side="left")
        self.cancel_button = ttk.Button(bar, text="Cancel", command=self.app.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Open output folder", command=lambda: open_folder(self.folder.get(), self)).pack(side="right")
        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 4))
        ttk.Label(self, textvariable=self.status, style="Muted.TLabel").pack(fill="x")
        self.details_button = ttk.Button(self, text="View run details", command=self.show_details, style="Small.TButton")
        self.details_button.pack(anchor="w", pady=(5, 0))

    def show_destination(self, event=None):
        selected = self.preview_tree.selection()
        if selected and self.plan:
            self.destination_label.configure(text=str(self.plan[int(selected[0])].destination))

    def build_plan(self):
        raise NotImplementedError

    def preview(self):
        if self.app.busy:
            return
        self.invalidate()
        try:
            plan = self.build_plan()
        except (OSError, ValueError) as error:
            messagebox.showwarning("Check your inputs", str(error), parent=self)
            return
        self.plan = plan
        self.preview_tree.delete(*self.preview_tree.get_children())
        for index, operation in enumerate(plan):
            self.preview_tree.insert("", "end", iid=str(index),
                                     values=(operation.source.name, operation.destination.name, operation.note),
                                     tags=("muted",) if operation.skip else ())
        ready = sum(not operation.skip for operation in plan)
        self.status.set(f"{ready} file(s) ready · {len(plan) - ready} skipped · Review the names, then run.")
        self.run_button.configure(state="normal" if ready else "disabled")
        self.progress.configure(value=0, maximum=max(len(plan), 1))

    def run(self):
        if not self.plan or self.app.busy:
            return
        self.app.start(self, list(self.plan), self.run_options())

    def run_options(self):
        return {}

    def set_locked(self, locked):
        for file_list in self.file_lists:
            file_list.set_locked(locked)
        for control in self.controls:
            if locked:
                control.configure(state="disabled")
            else:
                control.configure(state="readonly" if isinstance(control, ttk.Combobox) else "normal")
        self.run_button.configure(state="disabled" if locked or not self.plan else "normal")

    def on_progress(self, index, operation, status):
        if self.preview_tree.exists(str(index)):
            self.preview_tree.set(str(index), "status", status)
            self.preview_tree.item(str(index), tags=("saved",) if status == "Saved" else ("error",) if status.startswith("Error") else ())
            self.preview_tree.see(str(index))
        self.progress.configure(value=index if status == "Working" else index + 1)
        self.status.set(f"{index + 1} / {len(self.plan)} · {operation.source.name} · {status}")

    def on_finished(self, result):
        self.last_result = result
        label = "Cancelled" if result.cancelled else "Finished"
        self.status.set(f"{label} · {len(result.completed)} saved · {len(result.skipped)} skipped · {len(result.errors)} failed"
                        + (f" · {len(result.warnings)} warning(s)" if result.warnings else ""))
        self.cancel_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        # Every run needs a new preview; existing numbered outputs must be re-planned.
        for item in self.preview_tree.get_children():
            if self.preview_tree.set(item, "status") in {"Ready", "Working"}:
                self.preview_tree.set(item, "status", "Not processed")
        self.plan = []
        if result.errors:
            messagebox.showwarning("Some files could not be processed", f"{len(result.errors)} file(s) failed. "
                                   "Other files continued. Select ‘View run details’ for the reasons.", parent=self)

    def show_details(self):
        result = self.last_result
        if result is None:
            messagebox.showinfo("Run details", "No batch has been run yet.", parent=self)
            return
        window = tk.Toplevel(self)
        window.title("Run details — Translation Tools")
        window.geometry("760x460")
        window.configure(bg=BG)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, bg=FIELD, fg=FG, insertbackground=FG, wrap="word", relief="flat", font=(FONT, 10))
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        entries = ["CANCELLED" if result.cancelled else "FINISHED", "",
                   *[f"SAVED  {path}" for path in result.completed],
                   *[f"SKIPPED  {path}" for path in result.skipped],
                   *[f"FAILED  {path}\n  {error}" for path, error in result.errors],
                   *[f"WARNING  {warning}" for warning in result.warnings]]
        text.insert("1.0", "\n".join(entries))
        text.configure(state="disabled")
        ttk.Button(window, text="Close", command=window.destroy).pack(pady=(0, 12))


class RenamerTab(ToolTab):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        ttk.Label(self, text="File Copier & Renamer", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Borrow filenames from one set of files and apply them to copies of another.", style="Muted.TLabel").pack(anchor="w", pady=(3, 12))
        columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure((0, 1), weight=1, uniform="files")
        columns.rowconfigure(0, weight=1)
        self.names = FileList(columns, "01  Names to use", "Reference files are read for their names only.", self.invalidate)
        self.names.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.sources = FileList(columns, "02  Files to copy", "Use one source for all names, or match the counts.", self.invalidate)
        self.sources.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.file_lists = [self.names, self.sources]
        ttk.Label(self, text="Files pair from top to bottom. Use the arrows or natural sort to set the order.", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self.keep_extension = tk.BooleanVar(value=True)
        keep = ttk.Checkbutton(self, text="Keep the source extension (for example: video.mkv → video.srt)", variable=self.keep_extension, command=self.invalidate)
        keep.pack(anchor="w", pady=(8, 0))
        self.controls.append(keep)
        self.output_controls()
        self.footer("Copy & rename")

    def build_plan(self):
        if not self.folder.get().strip():
            raise ValidationError("Choose an output folder.")
        return plan_copies(self.names.files, self.sources.files, self.folder.get(),
                           keep_extension=self.keep_extension.get(), collision=self.collision_policy())


class TimestampTab(ToolTab):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        ttk.Label(self, text="Subtitle Timestamp Mover", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Shift SRT and ASS subtitles earlier or later, including whole batches.", style="Muted.TLabel").pack(anchor="w", pady=(3, 12))
        top = ttk.Frame(self)
        top.pack(fill="both", expand=True)
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)
        top.rowconfigure(0, weight=1)
        self.sources = FileList(top, "01  Subtitle files", "SRT / ASS · Originals stay in place.", self.invalidate, subtitles=True)
        self.sources.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.file_lists = [self.sources]
        settings = ttk.Frame(top, style="Card.TFrame", padding=10)
        settings.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        settings.columnconfigure(0, weight=1)
        ttk.Label(settings, text="02  Timing adjustment", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(settings, text="Positive = later  ·  Negative = earlier", style="CardMuted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 9))
        self.offset = tk.StringVar(value="-90")
        offset = ttk.Entry(settings, textvariable=self.offset, font=(FONT, 20), width=10)
        offset.grid(row=2, column=0, sticky="ew")
        ttk.Label(settings, text="seconds", style="CardMuted.TLabel").grid(row=2, column=1, padx=(8, 0))
        self.offset.trace_add("write", lambda *args: self.invalidate())
        self.suffix = tk.StringVar(value="_shifted")
        ttk.Label(settings, text="Output suffix", style="CardMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 4))
        suffix = ttk.Entry(settings, textvariable=self.suffix)
        suffix.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.suffix.trace_add("write", lambda *args: self.invalidate())
        self.encoding = tk.StringVar(value="Auto (Unicode)")
        ttk.Label(settings, text="Text encoding", style="CardMuted.TLabel").grid(row=5, column=0, sticky="w", pady=(10, 4))
        encoding = ttk.Combobox(settings, state="readonly", textvariable=self.encoding,
                                values=["Auto (Unicode)", "UTF-8", "Windows-1256 (Arabic)", "Windows-1252", "UTF-16"])
        encoding.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.encoding.trace_add("write", lambda *args: self.invalidate())
        self.comments = tk.BooleanVar(value=True)
        comments = ttk.Checkbutton(settings, text="Shift ASS comment events too", variable=self.comments, command=self.invalidate, style="Card.TCheckbutton")
        comments.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.timing_button = ttk.Button(settings, text="Preview cue times…", command=self.preview_times)
        self.timing_button.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.controls += [offset, suffix, encoding, comments, self.timing_button]
        self.output_controls()
        self.footer("Shift subtitles")

    def build_plan(self):
        parse_shift(self.offset.get())
        if not self.folder.get().strip():
            raise ValidationError("Choose an output folder.")
        return plan_subtitles(self.sources.files, self.folder.get(), suffix=self.suffix.get(), collision=self.collision_policy())

    def run_options(self):
        return {"shift_seconds": self.offset.get(),
                "encoding": {"Auto (Unicode)": "auto", "UTF-8": "utf-8", "Windows-1256 (Arabic)": "cp1256",
                             "Windows-1252": "cp1252", "UTF-16": "utf-16"}[self.encoding.get()],
                "include_comments": self.comments.get()}

    def preview_times(self):
        if not self.sources.files or self.app.busy:
            messagebox.showinfo("Add subtitles", "Add subtitle files, then select a file to preview its timing.", parent=self)
            return
        selected = self.sources.tree.selection()
        source = self.sources.files[int(selected[0])] if selected else self.sources.files[0]
        try:
            options = self.run_options()
            parse_shift(options["shift_seconds"])
        except ValueError as error:
            messagebox.showwarning("Check the offset", str(error), parent=self)
            return
        self.app.start_preview(self, source, options)

    def show_times(self, source, result):
        window = tk.Toplevel(self)
        window.title(f"Timing preview — {source.name}")
        window.configure(bg=BG)
        window.geometry("850x450")
        window.minsize(650, 300)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=source.name, style="CardTitle.TLabel", background=BG).pack(anchor="w")
        ttk.Label(frame, text=f"{result.cues} cues · {result.clamped} clamped at zero · Showing the first {len(result.preview)}", style="Muted.TLabel").pack(anchor="w", pady=(5, 12))
        tree_frame, tree = make_tree(frame, [("start", "Original start", 160), ("end", "Original end", 160),
                                            ("new_start", "Shifted start", 160), ("new_end", "Shifted end", 160)], height=10)
        tree_frame.pack(fill="both", expand=True)
        for row in result.preview:
            tree.insert("", "end", values=row)
        ttk.Button(frame, text="Close", command=window.destroy).pack(anchor="e", pady=(12, 0))


class ScrollablePanel(ttk.Frame):
    """Keep controls reachable on small displays and at larger Windows text sizes."""
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, borderwidth=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.content = None
        self.window = None
        self.canvas.bind("<Configure>", self.resize)

    def attach(self, content):
        self.content = content
        self.window = self.canvas.create_window(0, 0, window=content, anchor="nw")
        content.bind("<Configure>", self.resize)

    def resize(self, event=None):
        if self.content is not None:
            self.canvas.itemconfigure(self.window, width=self.canvas.winfo_width(),
                                      height=max(self.content.winfo_reqheight(), self.canvas.winfo_height()))
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))


class TranslationToolsApp(tk.Tk):
    def __init__(self, initial_tab="renamer"):
        super().__init__()
        self.title("Translation Tools")
        icon = Path(__file__).resolve().parent / "assets" / "Darknyte_Nightglass.ico"
        if sys.platform == "win32" and icon.is_file():
            self.iconbitmap(default=str(icon))
            self.iconbitmap(str(icon))
        self.geometry(f"{min(1160, self.winfo_screenwidth() - 60)}x{min(930, self.winfo_screenheight() - 100)}")
        self.minsize(960, min(700, self.winfo_screenheight() - 100))
        self.configure(bg=BG)
        self.busy = False
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self.closing = False
        self.active_tab = None
        self.setup_style()
        header = ttk.Frame(self, padding=(24, 10))
        header.pack(fill="x")
        ttk.Label(header, text="TRANSLATION TOOLS", style="Brand.TLabel").pack(side="left")
        ttk.Label(header, text="FILE & SUBTITLE UTILITIES", style="Eyebrow.TLabel").pack(side="right")
        ttk.Separator(self).pack(fill="x")
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=(8, 4))
        self.renamer_panel = ScrollablePanel(self.notebook)
        self.timestamps_panel = ScrollablePanel(self.notebook)
        self.renamer = RenamerTab(self.renamer_panel.canvas, self)
        self.timestamps = TimestampTab(self.timestamps_panel.canvas, self)
        self.renamer_panel.attach(self.renamer)
        self.timestamps_panel.attach(self.timestamps)
        self.tabs = [self.renamer, self.timestamps]
        self.notebook.add(self.renamer_panel, text="  File Copier & Renamer  ")
        self.notebook.add(self.timestamps_panel, text="  Timestamp Mover  ")
        self.select_tab(initial_tab)
        self.bind("<MouseWheel>", self.scroll_content)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(60, self.poll)

    def setup_style(self):
        self.option_add("*Font", (FONT, 10))
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=(FONT, 10), bordercolor=LINE,
                         lightcolor=LINE, darkcolor=LINE, focuscolor=ACCENT)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED, font=(FONT, 9))
        style.configure("CardTitle.TLabel", background=PANEL, font=(FONT, 11, "bold"))
        style.configure("Title.TLabel", font=(FONT, 20, "bold"))
        style.configure("Brand.TLabel", foreground=ACCENT, font=(FONT, 13, "bold"))
        style.configure("Eyebrow.TLabel", foreground=MUTED, font=(FONT, 9, "bold"))
        style.configure("TButton", background=LINE, foreground=FG, borderwidth=0, padding=(12, 8))
        style.map("TButton", background=[("active", "#40566a"), ("disabled", "#222d38")], foreground=[("disabled", "#65788a")])
        style.configure("Small.TButton", padding=(7, 4), font=(FONT, 9))
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, font=(FONT, 11, "bold"), padding=(20, 8))
        style.map("Accent.TButton", background=[("disabled", LINE), ("active", "#a3ecdc")], foreground=[("disabled", MUTED), ("!disabled", BG)])
        style.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG, padding=6)
        style.configure("TCombobox", fieldbackground=FIELD, foreground=FG, arrowcolor=FG, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("disabled", "#65788a"), ("readonly", FG)])
        style.configure("TCheckbutton", background=BG, foreground=FG, padding=3)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Card.TCheckbutton", background=PANEL)
        style.map("Card.TCheckbutton", background=[("active", PANEL)])
        style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=FG, rowheight=27, borderwidth=0, font=(FONT, 10))
        style.configure("Treeview.Heading", background=PANEL, foreground=MUTED, relief="flat", padding=(8, 7), font=(FONT, 9, "bold"))
        style.map("Treeview", background=[("selected", ACCENT_DARK)], foreground=[("selected", "#ffffff")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 8), font=(FONT, 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT)])
        style.configure("Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT, borderwidth=0, thickness=5)

    def select_tab(self, name):
        self.notebook.select(self.timestamps_panel if name == "timestamps" else self.renamer_panel)

    def scroll_content(self, event):
        if event.widget.winfo_class() in {"Treeview", "Text", "Listbox", "TCombobox"}:
            return
        panel = self.timestamps_panel if self.notebook.select() == str(self.timestamps_panel) else self.renamer_panel
        if panel.canvas.yview() != (0.0, 1.0):
            panel.canvas.yview_scroll(-int(event.delta / 120), "units")

    def lock(self, active_tab):
        self.busy = True
        self.active_tab = active_tab
        self.cancel_event = threading.Event()
        for tab in self.tabs:
            tab.set_locked(True)
        active_tab.cancel_button.configure(state="normal")

    def unlock(self):
        self.busy = False
        for tab in self.tabs:
            tab.set_locked(False)
        if self.active_tab:
            self.active_tab.cancel_button.configure(state="disabled")

    def start(self, tab, plan, options):
        self.lock(tab)
        tab.status.set("Processing files…")
        cancel_event = self.cancel_event

        def worker():
            try:
                result = run_batch(plan, cancel=cancel_event,
                                   progress=lambda *event: self.events.put(("progress", tab, event)), **options)
                self.events.put(("finished", tab, result))
            except Exception as error:
                self.events.put(("failed", tab, str(error)))
        threading.Thread(target=worker, name="file-operations", daemon=True).start()

    def start_preview(self, tab, source, options):
        self.lock(tab)
        tab.status.set(f"Reading {source.name} for timing preview…")
        cancel_event = self.cancel_event

        def worker():
            try:
                text, codec = read_subtitle(source, options.pop("encoding"))
                result = shift_subtitles(text, source.suffix, cancel=cancel_event, **options)
                self.events.put(("timing", tab, (source, result)))
            except Cancelled:
                self.events.put(("preview_cancelled", tab, None))
            except Exception as error:
                self.events.put(("preview_failed", tab, str(error) or "Preview cancelled."))
        threading.Thread(target=worker, name="subtitle-preview", daemon=True).start()

    def cancel(self):
        if self.busy:
            self.cancel_event.set()
            self.active_tab.status.set("Cancelling… Completed outputs will remain; an unfinished output will be removed.")
            self.active_tab.cancel_button.configure(state="disabled")

    def poll(self):
        try:
            # Limit work per tick so very large batches cannot starve the GUI.
            for _ in range(100):
                kind, tab, payload = self.events.get_nowait()
                if kind == "progress":
                    tab.on_progress(*payload)
                else:
                    self.unlock()
                    if self.closing:
                        self.destroy()
                        return
                    if kind == "finished":
                        tab.on_finished(payload)
                    elif kind == "timing":
                        tab.status.set("Timing preview ready. Preview the output filenames before saving.")
                        tab.show_times(*payload)
                    elif kind == "preview_cancelled":
                        tab.status.set("Timing preview cancelled.")
                    else:
                        tab.status.set(payload)
                        messagebox.showerror("Could not process files", payload, parent=tab)
                        if kind == "failed":
                            tab.invalidate()
        except queue.Empty:
            pass
        self.after(60, self.poll)

    def close(self):
        if self.busy:
            self.closing = True
            self.cancel()
        else:
            self.destroy()


def main(initial_tab="renamer"):
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Darknyte.TranslationTools")
        except (AttributeError, OSError):
            pass
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    app = TranslationToolsApp(initial_tab)
    app.mainloop()
