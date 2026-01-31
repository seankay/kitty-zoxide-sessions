# kitty-zoxide-sessions

`kitty-zoxide-sessions` is a small helper that lets you jump to kitty sessions from your zoxide
history with fzf. It builds a kitty session file on demand and opens it via
`kitten @ action goto_session`, or launches your editor so you can tweak the
session definition.

## Features

- Query recent directories from `zoxide`
- Pick a target with `fzf`
- Create a kitty session file per directory
- Jump straight to a kitty session or open it in `$EDITOR`
- Optional auto-close for the launcher window

## Requirements

- Python 3.10+
- `kitty` + `kitten` on your PATH
- `zoxide`
- `fzf`
- An editor (defaults to `nvim` if `$EDITOR` is unset)

## Usage

```bash
./kitty-zoxide-sessions.py
```

Options:

```text
-d, --debug       Enable debug logging
-e, --edit        Edit the session file instead of opening it
-c, --auto-close  Close the launcher window on selection
```

## Example Kitty config

In kitty.conf:

```
map ctrl+a>k launch --type=window --bias=25 --location=hsplit zsh -ic "/path/to/script/kitty-zoxide-sessions.py --auto-close; exec zsh"
```

## How it works

1. Read the zoxide directory list.
2. Let you pick a directory with fzf.
3. Create a kitty session file from `default.kitty-session` if needed.
4. Either open the session in kitty or open the file in `$EDITOR`.

## Files and paths

- Session directory: `${XDG_DATA_HOME:-~/.local/share}/kitty-sessions`
- Session file name: `<directory>.kitty-session`
- Template file: `default.kitty-session` (must live next to the script)
- Log file: `<session_dir>/kitty-zoxide-sessions.log`
