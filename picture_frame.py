
import os
import sys
import json
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox
from threading import Thread
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageTk


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
IMAGE_DIR = APP_DIR / "images"
STATE_FILE = APP_DIR / "app_state.json"

MODEL = "flux2-klein-4b"
QUANTIZATION = "4"
STEPS = "4"
IMAGE_WIDTH = "512"
IMAGE_HEIGHT = "512"

IMAGE_DIR.mkdir(exist_ok=True)

current_prompt = ""
current_image_path = None
displayed_photo = None
fullscreen_window = None
fullscreen_photo = None
fullscreen_original = None

image_history = []
current_index = -1

# Stores original prompts for images
image_prompts = {}

# Continuous generation checkbox variable
continuous_generation = None

# Prevent overlapping MFLUX processes.
is_generating = False


# --------------------------------------------------
# SAVE / LOAD APPLICATION STATE
# --------------------------------------------------

def save_state():
    """Save the currently displayed image and prompt."""

    data = {
        "current_image": current_image_path,
        "current_prompt": current_prompt,
        "image_prompts": image_prompts
    }

    try:
        with open(STATE_FILE, "w") as file:
            json.dump(data, file, indent=4)

    except Exception as error:
        print("Could not save application state:", error)


def load_state():
    """Restore the last displayed image and prompt."""

    global current_image_path
    global current_prompt
    global image_prompts

    if not STATE_FILE.exists():
        return

    try:
        with open(STATE_FILE, "r") as file:
            data = json.load(file)

        current_image_path = data.get("current_image")
        current_prompt = data.get("current_prompt", "")
        image_prompts = data.get("image_prompts", {})

    except Exception as error:
        print("Could not load application state:", error)


# --------------------------------------------------
# FIND MFLUX EXECUTABLE
# --------------------------------------------------

def find_mflux():

    executable = shutil.which("mflux-generate-flux2")

    if executable:
        return executable

    python_dir = Path(sys.executable).parent

    possible_paths = [
        python_dir / "mflux-generate-flux2",
        python_dir / "bin" / "mflux-generate-flux2"
    ]

    for path in possible_paths:
        if path.exists():
            return str(path)

    return None


# --------------------------------------------------
# IMAGE FILE NAMING
# --------------------------------------------------

def next_image_path(prompt):

    safe_prompt = "".join(
        c for c in prompt
        if c.isalnum() or c in " -_"
    ).strip()

    safe_prompt = safe_prompt[:100]

    if not safe_prompt:
        safe_prompt = "Generated image"

    number = 1

    while True:

        filename = f"{safe_prompt} #{number}.png"
        path = IMAGE_DIR / filename

        if not path.exists():
            return str(path)

        number += 1


# --------------------------------------------------
# LOAD IMAGE HISTORY
# --------------------------------------------------

def refresh_image_history():
    """Rescan the image folder, automatically excluding deleted files."""

    global image_history
    global current_index

    image_history = sorted(
        [
            str(path)
            for path in IMAGE_DIR.iterdir()
            if path.is_file()
            and path.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]
        ],
        key=lambda path: os.path.getmtime(path)
    )

    # Remove stale prompt entries for images that no longer exist.
    existing_paths = set(image_history)
    for old_path in list(image_prompts):
        if old_path not in existing_paths:
            image_prompts.pop(old_path, None)

    if current_image_path in image_history:
        current_index = image_history.index(current_image_path)
    else:
        current_index = -1

    update_navigation_buttons()


# --------------------------------------------------
# PROMPT LOOKUP
# --------------------------------------------------

def metadata_path(image_path):
    """Return the JSON sidecar path associated with an image."""
    return Path(image_path).with_suffix(".json")


def save_image_metadata(image_path, prompt):
    """Save the prompt and generation settings beside the generated image."""
    metadata = {
        "prompt": prompt,
        "model": MODEL,
        "quantization": int(QUANTIZATION),
        "steps": int(STEPS),
        "width": int(IMAGE_WIDTH),
        "height": int(IMAGE_HEIGHT),
        "compute_precision": "float16",
        "created_at": datetime.now().astimezone().isoformat(),
        "seed": None,
        "output_file": Path(image_path).name
    }

    sidecar = metadata_path(image_path)
    temporary_path = sidecar.with_suffix(sidecar.suffix + ".tmp")

    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=4, ensure_ascii=False)
        temporary_path.replace(sidecar)
    except Exception as error:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        print(f"Could not save metadata for {image_path}: {error}")


def load_image_metadata(image_path):
    """Load an image's sidecar metadata, if it exists and is valid."""
    sidecar = metadata_path(image_path)
    if not sidecar.is_file():
        return None

    try:
        with sidecar.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read metadata {sidecar}: {error}")
        return None


def get_image_prompt(path):
    """Retrieve the prompt from memory, sidecar metadata, or legacy filename."""
    metadata = load_image_metadata(path)
    if metadata and isinstance(metadata.get("prompt"), str):
        prompt = metadata["prompt"]
        image_prompts[path] = prompt
        return prompt

    # Compatibility with images generated before sidecar metadata existed.
    if path in image_prompts:
        return image_prompts[path]

    # Fallback for images generated before sidecar metadata was introduced.
    filename = Path(path).stem
    if " #" in filename:
        return filename.rsplit(" #", 1)[0]
    return filename


def show_generation_details():
    """Display the selected image's saved generation settings."""
    if not current_image_path or not os.path.isfile(current_image_path):
        messagebox.showinfo("Generation Details", "No image is currently selected.")
        return

    metadata = load_image_metadata(current_image_path)
    if not metadata:
        messagebox.showinfo(
            "Generation Details",
            "No metadata file exists for this image. It may have been generated\n"
            "before metadata tracking was added."
        )
        return

    details = [
        f"{key.replace('_', ' ').title()}: {value}"
        for key, value in metadata.items()
    ]
    messagebox.showinfo("Generation Details", "\n".join(details))


# --------------------------------------------------
# UPDATE NAVIGATION BUTTONS
# --------------------------------------------------

def update_navigation_buttons():

    if not image_history:
        previous_button.config(state="disabled")
        next_button.config(state="disabled")
        image_counter.config(text="0 / 0")
        return

    previous_button.config(state="normal")
    next_button.config(state="normal")

    image_counter.config(
        text=f"{current_index + 1} / {len(image_history)}"
    )


# --------------------------------------------------
# DISPLAY IMAGE
# --------------------------------------------------

def show_image(image, path, prompt):

    global displayed_photo
    global current_image_path
    global current_prompt
    global current_index

    current_image_path = path
    current_prompt = prompt

    if path not in image_history:
        refresh_image_history()

    if path in image_history:
        current_index = image_history.index(path)

    prompt_label.config(text=prompt)

    # Resize for display without changing the saved original
    image = image.copy()
    image.thumbnail((850, 600), Image.Resampling.LANCZOS)

    displayed_photo = ImageTk.PhotoImage(image)

    image_label.config(
        image=displayed_photo,
        text=""
    )

    image_prompts[path] = prompt

    save_state()
    update_navigation_buttons()

    # Keep the separate fullscreen window synchronized with the selection.
    if fullscreen_window is not None and fullscreen_window.winfo_exists():
        update_fullscreen_image()

    status_label.config(
        text=f"Saved to {os.path.relpath(path, APP_DIR)}"
    )

    open_image_button.config(state="normal")
    details_button.config(state="normal")
    update_generation_controls()


# --------------------------------------------------
# FULLSCREEN IMAGE WINDOW
# --------------------------------------------------

def open_fullscreen_image(event=None):
    """Open the selected image in a separate, fullscreen Tk window."""
    global fullscreen_window, fullscreen_photo, fullscreen_original

    if not current_image_path or not os.path.isfile(current_image_path):
        return

    # Reuse the existing fullscreen window if it is already open.
    if fullscreen_window is not None and fullscreen_window.winfo_exists():
        update_fullscreen_image()
        fullscreen_window.lift()
        return

    try:
        fullscreen_original = Image.open(current_image_path).convert("RGB")
    except Exception as error:
        messagebox.showerror("Image Error", f"Could not open image:\n\n{error}")
        return

    fullscreen_window = tk.Toplevel(root)
    fullscreen_window.title(Path(current_image_path).name)
    fullscreen_window.configure(bg="black")
    fullscreen_window.attributes("-fullscreen", True)

    fullscreen_label = tk.Label(fullscreen_window, bg="black", cursor="hand2")
    fullscreen_label.pack(fill="both", expand=True)
    fullscreen_window.image_label = fullscreen_label

    fullscreen_window.bind("<Escape>", close_fullscreen_image)
    fullscreen_window.bind("<F11>", toggle_fullscreen)
    fullscreen_window.bind("<Left>", handle_left_arrow)
    fullscreen_window.bind("<Right>", handle_right_arrow)
    fullscreen_window.bind("<Configure>", on_fullscreen_resize)
    fullscreen_window.protocol("WM_DELETE_WINDOW", close_fullscreen_image)

    render_fullscreen_image()
    fullscreen_window.focus_force()


def update_fullscreen_image():
    """Reload the image currently selected in the main application."""
    global fullscreen_original

    if fullscreen_window is None or not fullscreen_window.winfo_exists():
        return

    if not current_image_path or not os.path.isfile(current_image_path):
        return

    try:
        with Image.open(current_image_path) as source:
            fullscreen_original = source.convert("RGB")
        fullscreen_window.title(Path(current_image_path).name)
        render_fullscreen_image()
    except Exception as error:
        print(f"Could not update fullscreen image: {error}")


def render_fullscreen_image():
    """Fit the original image inside the fullscreen window without cropping."""
    global fullscreen_photo

    if fullscreen_window is None or not fullscreen_window.winfo_exists():
        return

    width = fullscreen_window.winfo_width()
    height = fullscreen_window.winfo_height()
    if width <= 1 or height <= 1 or fullscreen_original is None:
        return

    image = fullscreen_original.copy()
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    fullscreen_photo = ImageTk.PhotoImage(image)
    fullscreen_window.image_label.configure(image=fullscreen_photo)


def on_fullscreen_resize(event):
    if event.widget is fullscreen_window:
        render_fullscreen_image()


def toggle_fullscreen(event=None):
    if fullscreen_window is not None and fullscreen_window.winfo_exists():
        is_fullscreen = bool(fullscreen_window.attributes("-fullscreen"))
        fullscreen_window.attributes("-fullscreen", not is_fullscreen)
        if not is_fullscreen:
            fullscreen_window.geometry("1100x800")
        render_fullscreen_image()
    return "break"


def close_fullscreen_image(event=None):
    """Close the separate image window and return to the main application."""
    global fullscreen_window, fullscreen_photo, fullscreen_original

    if fullscreen_window is not None and fullscreen_window.winfo_exists():
        fullscreen_window.destroy()

    fullscreen_window = None
    fullscreen_photo = None
    fullscreen_original = None
    return "break"


# --------------------------------------------------
# DISPLAY IMAGE BY HISTORY INDEX
# --------------------------------------------------

def display_history_image(index):
    """Display an image from the history collection."""

    global current_index

    if not image_history:
        return

    if index < 0 or index >= len(image_history):
        return

    path = image_history[index]

    if not os.path.isfile(path):
        refresh_image_history()
        status_label.config(text="An image was deleted; history has been refreshed.")
        return

    try:
        image = Image.open(path).convert("RGB")
        prompt = get_image_prompt(path)
        current_index = index
        show_image(image, path, prompt)

    except Exception as error:
        refresh_image_history()
        messagebox.showerror(
            "Image Error",
            f"Could not display image:\n\n{error}"
        )


# --------------------------------------------------
# NAVIGATION
# --------------------------------------------------

def previous_image():
    """Navigate to the previous image."""

    if not image_history:
        return

    new_index = (current_index - 1) % len(image_history)

    display_history_image(new_index)


def next_image():
    """Navigate to the next image."""

    if not image_history:
        return

    new_index = (current_index + 1) % len(image_history)

    display_history_image(new_index)


# --------------------------------------------------
# OPEN ORIGINAL IMAGE
# --------------------------------------------------

def open_image_file(event=None):

    if not current_image_path:
        return

    path = os.path.abspath(current_image_path)

    try:

        if sys.platform == "darwin":
            subprocess.Popen(["open", path])

        elif os.name == "nt":
            os.startfile(path)

        else:
            subprocess.Popen(["xdg-open", path])

    except Exception as error:

        messagebox.showerror(
            "Unable to Open Image",
            str(error)
        )


# --------------------------------------------------
# ERROR HANDLING
# --------------------------------------------------

def update_generation_controls():
    """Disable only generation actions while MFLUX is running."""
    state = "disabled" if is_generating else "normal"
    generate_button.config(state=state)
    regenerate_button.config(state=state if current_prompt else "disabled")


def show_error(error):

    global is_generating
    is_generating = False
    update_generation_controls()

    status_label.config(text="Generation failed.")

    messagebox.showerror(
        "MFLUX Generation Error",
        str(error)
    )


# --------------------------------------------------
# IMAGE GENERATION
# --------------------------------------------------

def generate_image(prompt=None):
    global current_prompt
    global is_generating

    if is_generating:
        return

    if prompt is None:
        prompt = prompt_entry.get().strip()
    if not prompt:
        return

    current_prompt = prompt
    prompt_entry.delete(0, tk.END)

    mflux_command = find_mflux()
    if not mflux_command:
        messagebox.showerror(
            "MFLUX Not Found",
            "Could not find mflux-generate-flux2.\n\n"
            "Make sure MFLUX is installed in the Python "
            "environment used to run this application."
        )
        return

    # Preserve the user's current selection while generation runs.
    selected_path_when_started = current_image_path
    is_generating = True
    update_generation_controls()
    status_label.config(text="Generating locally with MFLUX...")

    saved_path = next_image_path(prompt)

    def work():
        try:
            command = [
                mflux_command,
                "--model", MODEL,
                "--quantize", QUANTIZATION,
                "--compute-precision", "float16",
                "--prompt", prompt,
                "--steps", STEPS,
                "--width", IMAGE_WIDTH,
                "--height", IMAGE_HEIGHT,
                "--output", saved_path
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=900
            )

            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr or result.stdout
                    or "MFLUX failed without an error message."
                )
            if not os.path.exists(saved_path):
                raise RuntimeError("MFLUX finished but did not create the image.")

            # Save metadata only after MFLUX has successfully created the image.
            save_image_metadata(saved_path, prompt)
            image = Image.open(saved_path).convert("RGB")

            def finish_generation():
                global is_generating
                is_generating = False
                image_prompts[saved_path] = prompt
                refresh_image_history()

                # Do not pull the user away from an image they selected mid-run.
                if current_image_path == selected_path_when_started:
                    show_image(image, saved_path, prompt)
                else:
                    update_generation_controls()
                    status_label.config(
                        text=f"Generated {Path(saved_path).name} (added to history)"
                    )
                    save_state()

                # In continuous mode, use the prompt belonging to the image
                # currently selected when this next run begins.
                if continuous_generation.get():
                    root.after(500, continue_generation)

            root.after(0, finish_generation)

        except Exception as error:
            error_message = str(error)
            if os.path.exists(saved_path):
                try:
                    os.remove(saved_path)
                except OSError:
                    pass
            # Avoid leaving behind a sidecar if generation failed.
            sidecar = metadata_path(saved_path)
            try:
                sidecar.unlink(missing_ok=True)
            except OSError:
                pass
            root.after(0, lambda msg=error_message: show_error(msg))

    Thread(target=work, daemon=True).start()


def continue_generation():
    """Start the next continuous run using the currently selected image prompt."""
    if continuous_generation.get() and current_prompt and not is_generating:
        generate_image(current_prompt)


# --------------------------------------------------
# REGENERATE
# --------------------------------------------------

def regenerate_image():

    if current_prompt:
        generate_image(current_prompt)


# --------------------------------------------------
# KEYBOARD NAVIGATION
# --------------------------------------------------

def handle_left_arrow(event):
    previous_image()


def handle_right_arrow(event):
    next_image()


# --------------------------------------------------
# TKINTER INTERFACE
# --------------------------------------------------

root = tk.Tk()

root.title("Local AI Picture Generator")
root.geometry("1000x900")
root.minsize(600, 600)

root.configure(bg="#202020")


# --------------------------------------------------
# HEADER: PROMPT + REGENERATE
# --------------------------------------------------

header_frame = tk.Frame(
    root,
    bg="#202020"
)

header_frame.pack(
    fill="x",
    padx=25,
    pady=(25, 10)
)

prompt_label = tk.Label(
    header_frame,
    text="Your generated image will appear here",
    font=("Helvetica", 22, "bold"),
    fg="white",
    bg="#202020",
    wraplength=800,
    justify="left",
    anchor="w"
)

prompt_label.pack(
    side="left",
    fill="x",
    expand=True
)

regenerate_button = tk.Button(
    header_frame,
    text="Regenerate",
    font=("Helvetica", 13),
    command=regenerate_image,
    state="disabled",
    padx=15,
    pady=8
)

regenerate_button.pack(
    side="right",
    padx=(15, 0)
)

continuous_generation = tk.BooleanVar(value=False)

continuous_checkbox = tk.Checkbutton(
    header_frame,
    text="Keep generating",
    variable=continuous_generation,
    font=("Helvetica", 11),
    fg="white",
    bg="#202020",
    activeforeground="white",
    activebackground="#202020",
    selectcolor="#333333"
)
continuous_checkbox.pack(side="right", padx=(0, 12))


# --------------------------------------------------
# IMAGE DISPLAY
# --------------------------------------------------

image_frame = tk.Frame(
    root,
    bg="#202020"
)

image_frame.pack(
    fill="both",
    expand=True,
    padx=25,
    pady=10
)

image_label = tk.Label(
    image_frame,
    text="Enter a prompt to generate an image",
    font=("Helvetica", 16),
    fg="#999999",
    bg="#303030"
)

image_label.pack(
    fill="both",
    expand=True
)

# Click the displayed image to view it in a separate fullscreen window.
image_label.bind("<Button-1>", open_fullscreen_image)
image_label.configure(cursor="hand2")


# --------------------------------------------------
# IMAGE NAVIGATION
# --------------------------------------------------

navigation_frame = tk.Frame(
    root,
    bg="#202020"
)

navigation_frame.pack(
    fill="x",
    padx=25,
    pady=(5, 10)
)

previous_button = tk.Button(
    navigation_frame,
    text="← Previous",
    font=("Helvetica", 13),
    command=previous_image,
    state="disabled",
    padx=20,
    pady=8
)

previous_button.pack(
    side="left",
    expand=True
)

image_counter = tk.Label(
    navigation_frame,
    text="0 / 0",
    font=("Helvetica", 12),
    fg="white",
    bg="#202020"
)

image_counter.pack(
    side="left",
    padx=20
)

next_button = tk.Button(
    navigation_frame,
    text="Next →",
    font=("Helvetica", 13),
    command=next_image,
    state="disabled",
    padx=20,
    pady=8
)

next_button.pack(
    side="right",
    expand=True
)


# --------------------------------------------------
# STATUS
# --------------------------------------------------

status_frame = tk.Frame(root, bg="#202020")
status_frame.pack(fill="x", padx=25, pady=(5, 10))

status_label = tk.Label(
    status_frame,
    text="Ready",
    font=("Helvetica", 10),
    fg="#aaaaaa",
    bg="#202020",
    anchor="w"
)
status_label.pack(side="left", fill="x", expand=True)

open_image_button = tk.Button(
    status_frame,
    text="Open Image",
    command=open_image_file,
    state="disabled"
)
open_image_button.pack(side="right", padx=(8, 0))

details_button = tk.Button(
    status_frame,
    text="Generation Details",
    command=show_generation_details,
    state="disabled"
)
details_button.pack(side="right")


# --------------------------------------------------
# PROMPT INPUT
# --------------------------------------------------

input_frame = tk.Frame(
    root,
    bg="#202020"
)

input_frame.pack(
    fill="x",
    padx=25,
    pady=(5, 25)
)

prompt_entry = tk.Entry(
    input_frame,
    font=("Helvetica", 16),
    bg="#333333",
    fg="white",
    insertbackground="white",
    relief="flat"
)

prompt_entry.pack(
    side="left",
    fill="x",
    expand=True,
    ipady=12,
    padx=(0, 10)
)

prompt_entry.bind(
    "<Return>",
    lambda event: generate_image()
)

generate_button = tk.Button(
    input_frame,
    text="Generate",
    font=("Helvetica", 14, "bold"),
    command=generate_image,
    padx=25,
    pady=10
)

generate_button.pack(
    side="right"
)


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

# Restore the previous session
load_state()

# A saved current-image path may have been deleted outside the application.
if current_image_path and not os.path.isfile(current_image_path):
    current_image_path = None
    current_prompt = ""

# Scan all saved images
refresh_image_history()

# Restore the last displayed image, or show the newest
if image_history:

    if current_image_path in image_history:
        display_history_image(
            image_history.index(current_image_path)
        )

    else:
        display_history_image(
            len(image_history) - 1
        )

prompt_entry.focus()

# Keyboard navigation
root.bind("<Left>", handle_left_arrow)
root.bind("<Right>", handle_right_arrow)

root.mainloop()