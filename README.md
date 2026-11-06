# tmux control

A colorful terminal dashboard for managing tmux sessions, windows, and panes
on this machine and configured SSH hosts. It uses Python's built-in `curses`
module and the `tmux` command line tool; remote machines need SSH access and
tmux, but do not need a copy of this application or Python.

## Install

Requires Python 3.8+ and tmux (plus `ssh` for remote hosts).

```sh
git clone https://github.com/imwasay/tmux_utility.git
cd tmux_utility
ln -s "$PWD/tmux-menu" ~/.local/bin/tmux-menu   # optional
cp .env.example .env                              # optional; or use Configure hosts
```

## Run it

```sh
tmux-menu
```

The home screen combines local and remote sessions. Local sessions appear
without a prefix; remote sessions show their configured label, such as
`[SYSTEMB]`. Select a session to inspect its windows and panes, then open it
or manage it from the menu.

SSH hosts are read from the local project `.env` file, one per line:

```dotenv
TMUX_HOST_SYSTEMB=user@10.0.0.5
```

Add, edit, and remove hosts inside the dashboard with **Configure hosts**.
Labels become the remote session prefix. Targets can be SSH config aliases,
hostnames, IP addresses, or `user@host` values. The SSH user needs working
key-based access and tmux on each target. `tmux-menu --hosts` opens the host
editor directly; `tmux-menu --help` shows command options.

A terminal of at least 38 columns by 12 rows is required. Color is used when
available; monochrome terminals and SSH sessions remain supported.

## Navigate

- **Up/Down** or **j/k** moves through a menu; **Enter** opens the selection.
- **1-9** chooses a visible item. **Page Up/Page Down** scroll long lists.
- **Esc** or **q** goes back. Select **Quit** on the first screen to exit.
- Detach from an opened tmux session with **Ctrl-b**, then **d**.
- Session, window, and pane close actions ask for confirmation first.

## License

[MIT](LICENSE)
