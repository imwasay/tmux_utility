# Terminal UI design

## Overview

The interface is a compact control dashboard for tmux. It should feel clear at
a glance in a local terminal and remain legible when viewed over SSH. It uses
the terminal's own background and typography, with a restrained cyan accent
and a framed list that keeps the current host, task, selection, and key hints
in view.

The interface is built with Python's standard `curses` module. It has no
third-party runtime dependencies, image assets, or Unicode drawing
requirements.

## Color and state

- **Accent:** cyan for the application header, headings, and panel outlines.
- **Selection:** white on blue, with reverse video in monochrome terminals.
- **Success:** green for positive status messages.
- **Prompt:** yellow for keyboard guidance and neutral messages.
- **Error:** red for failed actions.
- Use the terminal's default background. Do not assume a dark or light theme.

When color is unavailable, preserve hierarchy with bold and reverse video.
Never encode an action or status through color alone.

## Layout

- Keep the current control machine visible in the top bar.
- Leave local session names unprefixed; prefix remote sessions with `[LABEL]`.
- Put SSH host editing in the menu and persist targets in the project `.env`.
- Use a title and one-line description above a single framed menu area.
- Put navigation hints and the current item count in the bottom status area.
- Keep the minimum usable size at 38 columns by 12 rows; truncate long labels
  safely and scroll long lists.
- Use ASCII borders and labels for compatibility with common SSH terminals.

## Interaction

- Up/Down or `j`/`k` moves selection; Enter activates it.
- `1` through `9` selects a visible row; Page Up/Down scrolls long lists.
- Esc or `q` returns to the previous menu. Destructive actions require an
  explicit confirmation.
- Input fields support cursor movement, Home/End, Delete/Backspace, Enter, and
  Escape to cancel.

## Maintenance rules

- Keep operations functional without color or mouse support.
- Query remote tmux servers over SSH from the local Python process; remote hosts
  need SSH and tmux, not an app copy or Python installation.
- Preserve the current host indicator, keyboard controls, confirmation before
  closing sessions/windows/panes, and terminal restoration on exit.
- If adding color pairs, update the monochrome fallback at the same time.
- If changing the minimum terminal size or keys, update `README.md` and
  `handover.md` in the same change.
