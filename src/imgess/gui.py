import tkinter as tk
import json
import os
from pathlib import Path
from tkinter import messagebox, ttk

import lionscliapp as app
from PIL import Image, ImageGrab, ImageTk, UnidentifiedImageError

from imgess.clustering import compare_query_to_index
from imgess.fingerprints import compute_fingerprints
from imgess.io_helpers import write_json_file


g = {
    "root": None,
    "window": None,
    "index": None,
    "index_path": None,
    "selected_cluster_id": "",
    "selected_sha256": "",
    "context_sha256": "",
    "display_mode": "cluster",
    "photo_refs": [],
    "thumbnail_cards": {},
}

widgets = {}


def run_gui(index, index_path):
    g["index"] = index
    g["index_path"] = Path(index_path)
    g["root"] = tk.Tk()
    g["root"].withdraw()
    g["root"].option_add("*tearOff", False)
    app.attach_tk(g["root"], handle_runtime_message)
    realize_main_window()
    app.publish_instance_metadata({"window_title": "Image Essentializer"})
    project_cluster_list()
    g["root"].mainloop()


def realize_main_window():
    window = tk.Toplevel(g["root"])
    g["window"] = window
    window.title("Image Essentializer")
    window.geometry("1180x760")
    window.protocol("WM_DELETE_WINDOW", handle_close_requested)
    window.columnconfigure(0, weight=0)
    window.columnconfigure(1, weight=1)
    window.rowconfigure(0, weight=0)
    window.rowconfigure(1, weight=1)
    window.rowconfigure(2, weight=0)
    bind_keyboard_shortcuts(window)
    build_summary_bar(window)
    build_cluster_panel(window)
    build_detail_panel(window)
    build_status_bar(window)


def bind_keyboard_shortcuts(window):
    window.bind("<KeyPress>", handle_key_pressed)


def build_summary_bar(window):
    frame = ttk.Frame(window, padding=(8, 6))
    frame.grid(row=0, column=0, columnspan=2, sticky="ew")
    frame.columnconfigure(0, weight=1)
    widgets["summary_var"] = tk.StringVar(value=dataset_summary_text())
    label = ttk.Label(frame, textvariable=widgets["summary_var"], anchor="w")
    label.grid(row=0, column=0, sticky="ew")


def build_cluster_panel(window):
    frame = ttk.Frame(window, padding=8)
    frame.grid(row=1, column=0, sticky="nsew")
    frame.rowconfigure(1, weight=1)
    ttk.Label(frame, text="Clusters", font=("", 14, "bold")).grid(row=0, column=0, sticky="w")
    tree = ttk.Treeview(frame, columns=("count", "confidence", "status"), show="tree headings", height=24)
    tree.heading("#0", text="Cluster")
    tree.heading("count", text="Images")
    tree.heading("confidence", text="Conf.")
    tree.heading("status", text="Status")
    tree.column("#0", width=160)
    tree.column("count", width=58, anchor="e")
    tree.column("confidence", width=58, anchor="e")
    tree.column("status", width=110)
    tree.grid(row=1, column=0, sticky="nsew")
    tree.bind("<<TreeviewSelect>>", handle_cluster_selected)
    widgets["cluster_tree"] = tree


def build_detail_panel(window):
    frame = ttk.Frame(window, padding=8)
    frame.grid(row=1, column=1, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(4, weight=1)
    widgets["title"] = ttk.Label(frame, text="Select a cluster", font=("", 16, "bold"))
    widgets["title"].grid(row=0, column=0, sticky="ew")
    build_buttons(frame)
    build_notes(frame)
    build_decision_meanings(frame)
    build_thumbnail_area(frame)


def build_buttons(frame):
    buttons = ttk.Frame(frame)
    buttons.grid(row=1, column=0, sticky="ew", pady=(8, 8))
    for i in range(8):
        buttons.columnconfigure(i, weight=0)
    make_button(buttons, "Same Design", "confirmed-same-design", 0)
    make_button(buttons, "Same Design, Variant", "same-design-variant", 1)
    make_button(buttons, "Related, Not Same", "nearby-sibling-design", 2)
    make_button(buttons, "Needs Split", "needs-split", 3)
    make_button(buttons, "Reject Cluster", "rejected", 4)
    remove_button = ttk.Button(buttons, text="Remove Selected Image From Cluster", command=handle_remove_selected_image)
    remove_button.grid(row=0, column=5, padx=(12, 4))
    widgets["remove_image_button"] = remove_button
    ttk.Button(buttons, text="Save", command=handle_save_requested).grid(row=0, column=6, padx=4)
    ttk.Button(buttons, text="Locate Image From Clipboard", command=handle_locate_clipboard_image).grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 0))


def make_button(parent, text, status, column):
    button = ttk.Button(parent, text=text, command=lambda: set_selected_cluster_status(status))
    button.grid(row=0, column=column, padx=4)
    widgets.setdefault("decision_buttons", []).append(button)


def build_notes(frame):
    notes = ttk.Frame(frame)
    notes.grid(row=2, column=0, sticky="ew")
    notes.columnconfigure(1, weight=1)
    ttk.Label(notes, text="Tags").grid(row=0, column=0, sticky="w", padx=(0, 6))
    widgets["tags_var"] = tk.StringVar()
    tags_entry = ttk.Entry(notes, textvariable=widgets["tags_var"])
    tags_entry.grid(row=0, column=1, sticky="ew")
    tags_entry.bind("<FocusOut>", handle_notes_changed)
    ttk.Label(notes, text="Notes").grid(row=1, column=0, sticky="nw", padx=(0, 6), pady=(6, 0))
    text = tk.Text(notes, height=3, wrap="word")
    text.grid(row=1, column=1, sticky="ew", pady=(6, 0))
    text.bind("<FocusOut>", handle_notes_changed)
    widgets["notes_text"] = text


def build_decision_meanings(frame):
    box = ttk.LabelFrame(frame, text="Decision Meanings", padding=8)
    box.grid(row=3, column=0, sticky="ew", pady=(8, 0))
    box.columnconfigure(0, weight=1)
    explanation = (
        "Keyboard shortcuts while reviewing: A = Same Design, S = Same Design Variant, D = Related Not Same, F = Needs Split, G = Reject Cluster.\n"
        "Same Design: these images represent the same sticker design, even if one is rounded, cropped, resized, JPEG/PNG, or missing edge/corner detail.\n"
        "Same Design, Variant: these belong together as one design family, but at least one meaningful variant is present, such as hanko/no-hanko, kanji/no-kanji, color correction, or small intentional decoration differences.\n"
        "Related, Not Same: these are nearby evidence, such as same character/franchise/style, but should not be treated as the same design.\n"
        "Needs Split: this computed cluster contains images that should be separated and reviewed as different designs or different design families.\n"
        "Reject Cluster: this proposed cluster is not useful as a grouping. It does not delete image records or files.\n"
        "Remove Selected Image From Cluster: removes only the clicked thumbnail from this cluster in the index; it does not delete the source file.\n"
        "Tags and Notes apply to this cluster. Save writes the reviewed JSON index file, not the original images."
    )
    text = tk.Text(box, height=10, wrap="word", relief="flat", borderwidth=0, takefocus=0)
    text.grid(row=0, column=0, sticky="ew")
    text.insert("1.0", explanation)
    text.configure(state="disabled")
    widgets["decision_meanings_text"] = text


def build_thumbnail_area(frame):
    canvas = tk.Canvas(frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas)
    inner.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
    scrollbar.grid(row=4, column=1, sticky="ns", pady=(8, 0))
    widgets["thumb_canvas"] = canvas
    widgets["thumb_frame"] = inner


def build_status_bar(window):
    widgets["status_var"] = tk.StringVar(value="Ready")
    label = ttk.Label(window, textvariable=widgets["status_var"], anchor="w", padding=(8, 4))
    label.grid(row=2, column=0, columnspan=2, sticky="ew")


def project_cluster_list():
    widgets["summary_var"].set(dataset_summary_text())
    tree = widgets["cluster_tree"]
    tree.delete(*tree.get_children())
    for cluster in g["index"].get("clusters", []):
        tree.insert(
            "",
            "end",
            iid=cluster["cluster_id"],
            text=cluster["title"],
            values=(len(cluster["image_sha256s"]), cluster["confidence"], cluster["status"]),
        )
    set_cluster_controls_enabled(False)


def handle_cluster_selected(event=None):
    selection = widgets["cluster_tree"].selection()
    if not selection:
        return
    g["selected_cluster_id"] = selection[0]
    g["selected_sha256"] = ""
    g["display_mode"] = "cluster"
    project_selected_cluster()


def project_selected_cluster():
    cluster = get_selected_cluster()
    if cluster is None:
        return
    g["display_mode"] = "cluster"
    set_cluster_controls_enabled(True)
    widgets["title"].configure(
        text=f"{cluster['title']}  |  {len(cluster['image_sha256s'])} images  |  {cluster['status']}"
    )
    widgets["tags_var"].set(", ".join(cluster.get("variant_tags", [])))
    widgets["notes_text"].delete("1.0", "end")
    widgets["notes_text"].insert("1.0", cluster.get("human_notes", ""))
    project_thumbnails(cluster)
    widgets["status_var"].set("Showing " + cluster["cluster_id"])


def project_thumbnails(cluster):
    frame = widgets["thumb_frame"]
    for child in frame.winfo_children():
        child.destroy()
    g["photo_refs"] = []
    g["thumbnail_cards"] = {}
    row = 0
    column = 0
    for sha256 in cluster["image_sha256s"]:
        card = tk.Frame(
            frame,
            padx=6,
            pady=6,
            relief="ridge",
            borderwidth=1,
            highlightthickness=2,
            highlightbackground="#b8b8b8",
            highlightcolor="#1f6feb",
        )
        card.grid(row=row, column=column, sticky="n", padx=5, pady=5)
        g["thumbnail_cards"][sha256] = card
        build_thumbnail_card(card, sha256)
        column += 1
        if column >= 4:
            column = 0
            row += 1
    refresh_thumbnail_selection()


def project_singleton_image(sha256, score):
    g["display_mode"] = "singleton"
    g["selected_cluster_id"] = ""
    g["selected_sha256"] = sha256
    tree = widgets["cluster_tree"]
    tree.selection_remove(tree.selection())
    set_cluster_controls_enabled(False)
    widgets["title"].configure(
        text=f"Unclustered Image  |  match score {score:.4f}  |  no cluster selected"
    )
    widgets["tags_var"].set("")
    widgets["notes_text"].delete("1.0", "end")
    frame = widgets["thumb_frame"]
    for child in frame.winfo_children():
        child.destroy()
    g["photo_refs"] = []
    g["thumbnail_cards"] = {}
    card = tk.Frame(
        frame,
        padx=6,
        pady=6,
        relief="solid",
        borderwidth=3,
        highlightthickness=2,
        highlightbackground="#1f6feb",
        highlightcolor="#1f6feb",
    )
    card.grid(row=0, column=0, sticky="n", padx=5, pady=5)
    g["thumbnail_cards"][sha256] = card
    build_thumbnail_card(card, sha256)
    refresh_thumbnail_selection()


def set_cluster_controls_enabled(enabled):
    state = "normal" if enabled else "disabled"
    for button in widgets.get("decision_buttons", []):
        button.configure(state=state)
    if "remove_image_button" in widgets:
        widgets["remove_image_button"].configure(state=state)


def build_thumbnail_card(card, sha256):
    path = first_path_for_sha(sha256)
    image_label = tk.Label(card, background="white")
    image_label.grid(row=0, column=0)
    photo = load_thumbnail(path)
    if photo is None:
        image_label.configure(text="Cannot load")
    else:
        image_label.configure(image=photo)
        g["photo_refs"].append(photo)
    text = sha256[:12] + "\n" + Path(path).name
    label = tk.Label(card, text=text, justify="center", background="white")
    label.grid(row=1, column=0, pady=(4, 0))
    for widget in (card, image_label, label):
        widget.bind("<Button-1>", lambda event, value=sha256: select_thumbnail(value))
        widget.bind("<Button-3>", lambda event, value=sha256: show_image_context_menu(event, value))


def load_thumbnail(path):
    try:
        with Image.open(path) as image:
            image.thumbnail((160, 260), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image.copy())
    except (OSError, UnidentifiedImageError):
        return None


def select_thumbnail(sha256):
    g["selected_sha256"] = sha256
    refresh_thumbnail_selection()
    widgets["status_var"].set("Selected image " + sha256[:16])


def show_image_context_menu(event, sha256):
    select_thumbnail(sha256)
    g["context_sha256"] = sha256
    menu = tk.Menu(g["window"], tearoff=False)
    menu.add_command(label="Open Image", command=open_context_image)
    menu.add_command(label="Copy Full Path", command=copy_context_full_path)
    menu.add_command(label="Copy All Paths", command=copy_context_all_paths)
    menu.add_command(label="Open Containing Folder", command=open_context_containing_folder)
    menu.tk_popup(event.x_root, event.y_root)
    menu.grab_release()


def open_context_image():
    path = first_path_for_sha(g["context_sha256"])
    os.startfile(path)
    widgets["status_var"].set("Opened image " + path)


def copy_context_full_path():
    path = first_path_for_sha(g["context_sha256"])
    copy_text(path)
    widgets["status_var"].set("Copied path " + path)


def copy_context_all_paths():
    paths = all_paths_for_sha(g["context_sha256"])
    copy_text(json.dumps(paths, indent=2))
    widgets["status_var"].set(f"Copied {len(paths)} path(s) as JSON")


def open_context_containing_folder():
    path = Path(first_path_for_sha(g["context_sha256"]))
    os.startfile(str(path.parent))
    widgets["status_var"].set("Opened folder " + str(path.parent))


def copy_text(text):
    g["root"].clipboard_clear()
    g["root"].clipboard_append(text)
    g["root"].update()


def handle_locate_clipboard_image():
    image = load_clipboard_image()
    if image is None:
        messagebox.showinfo(
            "Image Essentializer",
            "The clipboard does not contain image data or a readable image file path.",
        )
        return
    widgets["status_var"].set("Fingerprinting clipboard image...")
    g["window"].update_idletasks()
    query_record = {
        "analysis": {
            "fingerprints": compute_fingerprints(image),
        }
    }
    results = compare_query_to_index(query_record, g["index"], 25)
    if not results:
        messagebox.showinfo("Image Essentializer", "No indexed images are available to compare.")
        return
    best = results[0]
    if not best["cluster_ids"]:
        project_singleton_image(best["sha256"], best["score"])
        widgets["status_var"].set(
            f"Closest image is unclustered: {best['score']:.4f}  {best['sha256'][:16]}"
        )
        return
    best_cluster_result = best
    cluster_id = best_cluster_result["cluster_ids"][0]
    select_cluster(cluster_id)
    select_thumbnail(best_cluster_result["sha256"])
    widgets["status_var"].set(
        f"Clipboard image best cluster: {cluster_id}  score {best_cluster_result['score']:.4f}"
    )


def load_clipboard_image():
    data = ImageGrab.grabclipboard()
    if isinstance(data, Image.Image):
        return data.copy()
    if isinstance(data, list):
        return load_first_clipboard_file(data)
    path = clipboard_text_as_path()
    if path is not None:
        return load_image_file(path)
    return None


def load_first_clipboard_file(paths):
    for path_text in paths:
        image = load_image_file(Path(path_text))
        if image is not None:
            return image
    return None


def clipboard_text_as_path():
    try:
        text = g["root"].clipboard_get()
    except tk.TclError:
        return None
    text = text.strip().strip('"')
    if not text:
        return None
    path = Path(text)
    if path.exists():
        return path
    return None


def load_image_file(path):
    try:
        with Image.open(path) as image:
            image.load()
            return image.copy()
    except (OSError, UnidentifiedImageError):
        return None


def select_cluster(cluster_id):
    tree = widgets["cluster_tree"]
    if not tree.exists(cluster_id):
        return
    g["selected_cluster_id"] = cluster_id
    tree.selection_set(cluster_id)
    tree.see(cluster_id)
    project_selected_cluster()


def refresh_thumbnail_selection():
    for sha256, card in g["thumbnail_cards"].items():
        if sha256 == g["selected_sha256"]:
            card.configure(highlightbackground="#1f6feb", borderwidth=3, relief="solid")
        else:
            card.configure(highlightbackground="#b8b8b8", borderwidth=1, relief="ridge")


def set_selected_cluster_status(status):
    if g["display_mode"] != "cluster":
        return
    cluster = get_selected_cluster()
    if cluster is None:
        return
    sync_notes_to_cluster(cluster)
    cluster["status"] = status
    project_cluster_row(cluster)
    widgets["title"].configure(
        text=f"{cluster['title']}  |  {len(cluster['image_sha256s'])} images  |  {cluster['status']}"
    )
    widgets["summary_var"].set(dataset_summary_text())
    widgets["status_var"].set("Marked " + cluster["cluster_id"] + " as " + status)


def project_cluster_row(cluster):
    tree = widgets["cluster_tree"]
    values = (len(cluster["image_sha256s"]), cluster["confidence"], cluster["status"])
    if tree.exists(cluster["cluster_id"]):
        tree.item(cluster["cluster_id"], text=cluster["title"], values=values)
    else:
        tree.insert("", "end", iid=cluster["cluster_id"], text=cluster["title"], values=values)
    tree.selection_set(cluster["cluster_id"])


def handle_key_pressed(event):
    if should_ignore_review_shortcut(event):
        return
    if g["display_mode"] != "cluster":
        return
    key = event.keysym.lower()
    shortcuts = {
        "a": "confirmed-same-design",
        "s": "same-design-variant",
        "d": "nearby-sibling-design",
        "f": "needs-split",
        "g": "rejected",
    }
    if key not in shortcuts:
        return
    set_selected_cluster_status(shortcuts[key])
    return "break"


def should_ignore_review_shortcut(event):
    widget = event.widget
    widget_class = widget.winfo_class()
    return widget_class in {"Entry", "TEntry", "Text"}


def handle_remove_selected_image():
    if g["display_mode"] != "cluster":
        messagebox.showinfo("Image Essentializer", "Select a cluster before removing an image from it.")
        return
    cluster = get_selected_cluster()
    sha256 = g["selected_sha256"]
    if cluster is None or not sha256:
        messagebox.showinfo("Image Essentializer", "Select an image thumbnail first.")
        return
    if len(cluster["image_sha256s"]) <= 1:
        messagebox.showinfo("Image Essentializer", "A cluster must keep at least one image.")
        return
    cluster["image_sha256s"] = [item for item in cluster["image_sha256s"] if item != sha256]
    cluster["status"] = "edited-needs-review"
    g["selected_sha256"] = ""
    project_cluster_list()
    widgets["cluster_tree"].selection_set(cluster["cluster_id"])
    project_selected_cluster()


def dataset_summary_text():
    images = g["index"].get("images", {})
    clusters = g["index"].get("clusters", [])
    unique_images = len(images)
    filesystem_paths = 0
    for record in images.values():
        filesystem_paths += len(record.get("found_on_filesystem_at", {}))
    clustered_sha256s = set()
    for cluster in clusters:
        clustered_sha256s.update(cluster.get("image_sha256s", []))
    clustered_images = len(clustered_sha256s)
    singleton_images = unique_images - clustered_images
    scan_runs = len(g["index"].get("scan_runs", []))
    if scan_runs == 0 and "scan_run" in g["index"]:
        scan_runs = 1
    reviewed = sum(1 for cluster in clusters if cluster.get("status") != "computed")
    return (
        f"Dataset: {unique_images} unique images | {filesystem_paths} filesystem paths | "
        f"{len(clusters)} visible clusters | {clustered_images} clustered images | "
        f"{singleton_images} singleton/unclustered images | {reviewed} reviewed clusters | "
        f"{scan_runs} scan runs"
    )


def handle_notes_changed(event=None):
    cluster = get_selected_cluster()
    if cluster is not None:
        sync_notes_to_cluster(cluster)


def sync_notes_to_cluster(cluster):
    if g["display_mode"] != "cluster":
        return
    tags = widgets["tags_var"].get().replace(";", ",").split(",")
    cluster["variant_tags"] = [tag.strip() for tag in tags if tag.strip()]
    cluster["human_notes"] = widgets["notes_text"].get("1.0", "end").strip()


def handle_save_requested():
    cluster = get_selected_cluster()
    if cluster is not None:
        sync_notes_to_cluster(cluster)
    write_json_file(g["index_path"], g["index"])
    widgets["status_var"].set("Saved " + str(g["index_path"]))


def handle_close_requested():
    if messagebox.askyesno("Image Essentializer", "Save index before closing?"):
        handle_save_requested()
    g["root"].destroy()


def handle_runtime_message(message):
    if message.get("type") == "summon":
        app.bring_window_to_front(g["window"])
        widgets["status_var"].set("Summoned existing Image Essentializer window")


def get_selected_cluster():
    cluster_id = g["selected_cluster_id"]
    for cluster in g["index"].get("clusters", []):
        if cluster["cluster_id"] == cluster_id:
            return cluster
    return None


def first_path_for_sha(sha256):
    return all_paths_for_sha(sha256)[0]


def all_paths_for_sha(sha256):
    record = g["index"]["images"][sha256]
    return sorted(record["found_on_filesystem_at"])
