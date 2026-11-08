
import os
import sys
import json
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox
from threading import Thread
from pathlib import Path
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

image_history = []
current_index = -1

# Stores original prompts for images
image_prompts = {}

# Continuous generation checkbox variable
continuous_generation = None


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
    """Scan the images folder and sort images chronologically."""

    global image_history
    global current_index

    image_history = sorted(
        [
            str(path)
            for path in IMAGE_DIR.iterdir()
            if path.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]
        ],
        key=lambda path: os.path.getmtime(path)
    )

    if current_image_path in image_history:
        current_index = image_history.index(current_image_path)

    else:
        current_index = -1

    update_navigation_buttons()


# --------------------------------------------------
# PROMPT LOOKUP
# --------------------------------------------------

def get_image_prompt(path):
    """Retrieve the original prompt for an image."""

    if path in image_prompts:
        return image_prompts[path]

    # Fallback for images created before this version
    filename = Path(path).stem

    if " #" in filename:
        return filename.rsplit(" #", 1)[0]

    return filename


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

    image_label.bind(
        "<Button-1>",
        open_image_file
    )

    image_prompts[path] = prompt

    save_state()
    update_navigation_buttons()

    status_label.config(
        text=f"Saved to {os.path.relpath(path, APP_DIR)}"
    )

    generate_button.config(state="normal")
    regenerate_button.config(state="normal")


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

    try:
        image = Image.open(path).convert("RGB")
        prompt = get_image_prompt(path)

        current_index = index

        show_image(image, path, prompt)

    except Exception as error:
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

def show_error(error):

    generate_button.config(state="normal")
    regenerate_button.config(state="normal")

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

    generate_button.config(state="disabled")
    regenerate_button.config(state="disabled")

    previous_button.config(state="disabled")
    next_button.config(state="disabled")

    status_label.config(
        text="Generating locally with MFLUX..."
    )

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
                    result.stderr
                    or result.stdout
                    or "MFLUX failed without an error message."
                )

            if not os.path.exists(saved_path):

                raise RuntimeError(
                    "MFLUX finished but did not create the image."
                )

            image = Image.open(saved_path).convert("RGB")

            def finish_generation():

                image_prompts[saved_path] = prompt

                refresh_image_history()

                show_image(
                    image,
                    saved_path,
                    prompt
                )

                # Generate another image if continuous mode is enabled.
                # The current generation finishes before the next begins.
                if continuous_generation.get():
                    root.after(
                        500,
                        lambda: generate_image(prompt)
                    )

            root.after(0, finish_generation)

        except Exception as error:

            error_message = str(error)

            if os.path.exists(saved_path):
                try:
                    os.remove(saved_path)
                except OSError:
                    pass

            root.after(
                0,
                lambda msg=error_message:
                    show_error(msg)
            )

    Thread(
        target=work,
        daemon=True
    ).start()


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
    bg="#303030",
    cursor="hand2"
)

image_label.pack(
    fill="both",
    expand=True
)


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

status_label = tk.Label(
    root,
    text="Ready",
    font=("Helvetica", 10),
    fg="#aaaaaa",
    bg="#202020"
)

status_label.pack(
    pady=(5, 10)
)


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
# CONTINUOUS GENERATION CHECKBOX
# --------------------------------------------------

continuous_generation = tk.BooleanVar(value=False)

continuous_checkbox = tk.Checkbutton(
    input_frame,
    text="Keep generating",
    variable=continuous_generation,
    font=("Helvetica", 11),
    fg="white",
    bg="#202020",
    activeforeground="white",
    activebackground="#202020",
    selectcolor="#333333"
)

continuous_checkbox.pack(
    side="right",
    padx=(0, 12)
)


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

# Restore the previous session
load_state()

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
