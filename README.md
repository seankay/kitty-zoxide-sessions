# kitty-zoxide-sessions

`kitty-zoxide-sessions` is a small helper that lets you jump to kitty sessions from your zoxide
history with fzf. It builds a kitty session file on demand and opens it via
`kitten @ action goto_session`. Use a custom keybind with this script to quickly navigate between kitty sessions.

## Preview

![gif](https://github.com/user-attachments/assets/6210d8ab-204c-4e4f-8779-65c116a59fda)

![screenshot](https://github.com/user-attachments/assets/21019fdd-3ef8-4ad4-b8f5-f989fbb2132e)

## Features

- Query recent directories from `zoxide`
- Pick a target with `fzf`
- Create a kitty session file per directory
- Jump straight to a kitty session or open it in `$EDITOR`
- Optional auto-close for the launcher window

## Requirements

- Python 3.10+
- `kitty`
- `zoxide`
- `fzf`

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/seankay/kitty-zoxide-sessions/main/install.sh | sh
```

The installer drops `kitty-zoxide-sessions.py` and `default.kitty-session` into
`~/.local/bin`. Set `BINDIR` to customize the destination.

## Usage

```bash
./kitty-zoxide-sessions.py
```

Options:

```text
-d, --debug       Enable debug logging
-e, --edit        Edit the session file instead of opening it
-c, --auto-close  Close the launcher window on selection
-t, --template    Path to a custom kitty session template
```

## Example Kitty config

In kitty.conf:

```
map ctrl+a>k launch --type=window --bias=25 --location=hsplit zsh -ic "/path/to/script/kitty-zoxide-sessions.py --auto-close; exec zsh"
```

Pressing `ctrl+a` followed by `k` will open the picker.

## How it works

1. Read the zoxide directory list.
2. Let you pick a directory with fzf.
3. Create a kitty session file from `default.kitty-session` if needed.
4. Either open the session in kitty or open the file in `$EDITOR`.

## Custom templates

Copy `default.kitty-session`, edit it as needed, and pass its path with
`--template`. If the custom file cannot be read, the script falls back to the
default template.

```bash
./kitty-zoxide-sessions.py --template ~/dotfiles/kitty/custom-session.kitty-session
```

## Files and paths

- Session directory: `${XDG_DATA_HOME:-~/.local/share}/kitty-sessions`
- Session file name: `<directory>.kitty-session`
- Template file: `default.kitty-session` (must live next to the script)
- Log file: `<session_dir>/kitty-zoxide-sessions.log`

## Credits

- https://github.com/joshmedeski/sesh
- https://github.com/LazyStability/kitty-sessionizer
- https://github.com/ThePrimeagen/tmux-sessionizer
