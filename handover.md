# Handover

## Purpose

`tmux-menu` is a terminal dashboard that combines sessions from the machine
where it runs with sessions on SSH hosts configured in `.env`. Local rows have
no prefix. Remote rows use `[LABEL]`, so same-named sessions remain distinct.
The local Python process sends tmux commands over SSH; a remote host needs SSH
and tmux, but no copy of this application or Python.

## Usage

- `tmux-menu` opens the combined session list.
- `tmux-menu --hosts` opens the SSH host editor.
- `tmux-menu --help` prints command usage.
- The main menu can create local sessions and sessions on each configured host.
- Selecting a remote session opens its windows and panes through SSH. Opening
  it hands the terminal to `ssh -tt ... tmux attach-session`.

The host editor reads and writes the project-root `.env` file. Each host uses
one line in this format:

```dotenv
TMUX_HOST_SYSTEMB=user@10.0.0.5
```

The suffix is the display label. The value is an SSH destination, including
SSH config aliases and `user@host`. `.env` is machine-specific and ignored by
Git. Do not copy the control machine's `.env` to a target where its entries
would refer back to itself.

## Files

- `tmux-ui.py` contains the curses interface and local/SSH tmux backend.
- `tmux-menu` launches the Python UI from the project directory.
- `.env` contains local SSH host targets; edit it in the GUI.
- `.env.example` is a sample host file; `LICENSE` is MIT.
- `.gitignore` keeps `.env` out of version control.
- `README.md` is the user guide.
- `DESIGN.md` records terminal UI rules.
- `handover.md` is this maintainer guide.

The Python program uses only the standard library plus local `tmux`. SSH
connections use `BatchMode=yes` and a short connection timeout so an offline
host does not block the menu waiting for a password prompt. Set up key-based
SSH access (or an SSH config alias backed by a key) for each target.

## Host management and errors

The home screen queries the local tmux server and each configured SSH host.
Connection failures appear in the status line; an unreachable host does not
hide sessions from other hosts. Hosts can be added, renamed, retargeted, and
removed in **Configure hosts**. Labels are normalized to uppercase letters,
digits, and underscores for `.env` keys.

The manager reloads `.env` each time it returns to the home screen. When adding
a host, use an SSH target that works from the machine running `tmux-menu`.
Remote commands are shell-quoted before being passed to SSH.

## Install paths and synchronization

Symlink the launcher onto your `PATH`, for example
`~/.local/bin/tmux-menu` to the project's launcher; interactive
Bash supplies command completion and adds `.local/bin` to `PATH`.

A copy of the project may be kept on remote hosts for convenience, but the combined manager does not rely on files being installed on remote
hosts. When syncing project files, copy the Python UI, launcher, docs, and
`.gitignore`; keep `.env` local to the machine that runs the combined manager.

## Behavior to preserve

- Keep local sessions unprefixed and remote sessions labeled by host.
- Keep the **Configure hosts** screen able to edit `.env` without a shell editor.
- Preserve local and remote session, window, and pane operations.
- Keep confirmations before closing sessions, windows, or panes.
- Keep ASCII-safe borders, keyboard controls, color fallback, and terminal
  restoration through `curses.wrapper`.
