#!/usr/bin/env python3
"""A keyboard-driven tmux manager for ordinary terminals and SSH sessions."""

from __future__ import annotations

import curses
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


@dataclass
class Host:
    label: str
    target: str


@dataclass
class Session:
    name: str
    attached: int
    windows: int
    host: Optional[Host] = None


@dataclass
class Window:
    index: int
    name: str
    active: bool
    panes: int


@dataclass
class Pane:
    index: int
    active: bool
    command: str


class HostConfig:
    path = Path(__file__).with_name(".env")
    target_pattern = re.compile(r"^[A-Za-z0-9_.@:\[\]-]+$")

    @staticmethod
    def key(label: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_").upper()

    @classmethod
    def valid_target(cls, target: str) -> bool:
        return bool(cls.target_pattern.fullmatch(target))

    def load(self) -> List[Host]:
        hosts = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return hosts
        except OSError:
            return hosts
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, target = stripped.split("=", 1)
            prefix = "TMUX_HOST_"
            key = key.strip()
            target = target.strip().strip('"').strip("'")
            if not key.startswith(prefix) or not self.valid_target(target):
                continue
            label = key[len(prefix):]
            if re.fullmatch(r"[A-Z0-9_]+", label):
                hosts.append(Host(label, target))
        return hosts

    def save(self, hosts: List[Host]) -> None:
        lines = [
            "# SSH targets managed in tmux-menu. Add hosts as TMUX_HOST_<LABEL>=<SSH_TARGET>.",
            "# SSH aliases from ~/.ssh/config and user@host targets are both supported.",
        ]
        for host in sorted(hosts, key=lambda item: item.label.casefold()):
            lines.append("TMUX_HOST_{}={}".format(self.key(host.label), host.target))
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class Tmux:
    def __init__(self, host: Optional[Host] = None) -> None:
        self.host = host
        self.connection_error = ""
        self.last_error = ""

    def call(self, *args: str) -> Tuple[int, str, str]:
        self.connection_error = ""
        self.last_error = ""
        command = ["tmux", *args]
        if self.host:
            command = [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=3",
                "-o", "BatchMode=yes",
                self.host.target,
                shlex.join(["tmux", *args]),
            ]
        try:
            result = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=8,
            )
        except subprocess.TimeoutExpired:
            message = "SSH timed out" if self.host else "tmux timed out"
            self.connection_error = message if self.host else ""
            return 124, "", message
        except OSError as exc:
            self.last_error = str(exc)
            if self.host:
                self.connection_error = self.last_error
            return 127, "", str(exc)
        if self.host and result.returncode == 255:
            self.connection_error = result.stderr.strip() or "SSH connection failed"
        if result.returncode:
            self.last_error = result.stderr.strip()
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def interactive_args(self, *args: str) -> List[str]:
        if self.host:
            return [
                "ssh",
                "-tt",
                "-o", "ConnectTimeout=3",
                self.host.target,
                shlex.join(["tmux", *args]),
            ]
        return ["tmux", *args]

    def sessions(self) -> List[Session]:
        code, output, _ = self.call(
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_attached}\t#{session_windows}",
        )
        if code:
            if self.host and not self.connection_error:
                expected_no_server = "no server running" in self.last_error.lower()
                if not expected_no_server:
                    self.connection_error = self.last_error or "Could not query tmux on SSH host"
            return []
        sessions = []
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) != 3:
                continue
            try:
                sessions.append(
                    Session(fields[0], int(fields[1]), int(fields[2]), self.host)
                )
            except ValueError:
                continue
        return sessions

    def windows(self, session: str) -> List[Window]:
        code, output, _ = self.call(
            "list-windows",
            "-t",
            session,
            "-F",
            "#{window_index}\t#{window_name}\t#{window_active}\t#{window_panes}",
        )
        if code:
            return []
        windows = []
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) != 4:
                continue
            try:
                windows.append(
                    Window(int(fields[0]), fields[1], fields[2] == "1", int(fields[3]))
                )
            except ValueError:
                continue
        return windows

    def panes(self, target: str) -> List[Pane]:
        code, output, _ = self.call(
            "list-panes",
            "-t",
            target,
            "-F",
            "#{pane_index}\t#{pane_active}\t#{pane_current_command}",
        )
        if code:
            return []
        panes = []
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) != 3:
                continue
            try:
                panes.append(Pane(int(fields[0]), fields[1] == "1", fields[2]))
            except ValueError:
                continue
        return panes


class TmuxUI:
    def __init__(self, screen: "curses._CursesWindow") -> None:
        self.screen = screen
        self.local_tmux = Tmux()
        self.tmux = self.local_tmux
        self.host_config = HostConfig()
        self.current_host = socket.gethostname().split(".")[0]
        self.message = ""
        self.message_error = False
        self.colors = False
        self._init_colors()

    def _init_colors(self) -> None:
        if not curses.has_colors():
            return
        try:
            curses.start_color()
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(2, curses.COLOR_CYAN, background)
            curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(4, curses.COLOR_GREEN, background)
            curses.init_pair(5, curses.COLOR_YELLOW, background)
            curses.init_pair(6, curses.COLOR_RED, background)
            self.colors = True
        except curses.error:
            self.colors = False

    def _style(self, pair: int = 0, extra: int = 0) -> int:
        if self.colors and pair:
            return curses.color_pair(pair) | extra
        if pair == 3:
            return curses.A_REVERSE | extra
        if pair in (1, 2, 4, 5, 6):
            return curses.A_BOLD | extra
        return extra

    def _write(self, y: int, x: int, value: str, limit: int, attr: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        available = min(limit, width - x)
        if y < 0 or y >= height or x < 0 or available <= 0:
            return
        try:
            self.screen.addnstr(y, x, str(value), available, attr)
        except curses.error:
            pass

    def say(self, message: str, error: bool = False) -> None:
        self.message = message
        self.message_error = error

    def draw(
        self,
        title: str,
        subtitle: str,
        rows: Iterable[str],
        selected: int = -1,
        offset: int = 0,
    ) -> int:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 12 or width < 38:
            self._write(0, 0, "TMUX MENU", max(1, width - 1), self._style(2, curses.A_BOLD))
            self._write(2, 0, "Terminal is too small for the dashboard.", max(1, width - 1))
            self._write(3, 0, "Use at least 38 columns x 12 rows.", max(1, width - 1))
            self.screen.refresh()
            return 1

        # A compact control-room header keeps the active host visible on local
        # terminals and over SSH, while the rest of the UI stays ASCII-safe.
        host = self.current_host
        brand = " TMUX / CONTROL "
        self._write(0, 0, " " * width, width, self._style(1))
        self._write(0, 1, brand, width - 2, self._style(1, curses.A_BOLD))
        host_label = "HOST  {}".format(host.upper())
        self._write(0, max(1, width - len(host_label) - 2), host_label, len(host_label), self._style(1))
        self._write(1, 0, "+" + "-" * (width - 2) + "+", width, self._style(2))
        self._write(2, 2, title.upper(), width - 4, self._style(2, curses.A_BOLD))
        self._write(3, 2, subtitle, width - 4, self._style(0))

        items = list(rows)
        box_left = 1
        box_width = width - 2
        box_top = 5
        footer_top = height - 3
        box_bottom = footer_top - 1
        row_start = box_top + 1
        visible_count = max(1, box_bottom - row_start)
        border_attr = self._style(2)
        self._write(box_top, box_left, "+" + "-" * (box_width - 2) + "+", box_width, border_attr)
        self._write(box_bottom, box_left, "+" + "-" * (box_width - 2) + "+", box_width, border_attr)
        end = min(len(items), offset + visible_count)
        for index in range(offset, end):
            y = row_start + index - offset
            is_selected = index == selected
            attr = self._style(3, curses.A_BOLD) if is_selected else curses.A_NORMAL
            self._write(y, box_left, "|", 1, border_attr)
            if is_selected:
                self._write(y, box_left + 1, " " * (box_width - 2), box_width - 2, attr)
            marker = "> " if is_selected else "  "
            self._write(y, box_left + 2, marker + items[index], box_width - 4, attr)
            self._write(y, width - 2, "|", 1, border_attr)
        for y in range(row_start + max(0, end - offset), box_bottom):
            self._write(y, box_left, "|", 1, border_attr)
            self._write(y, width - 2, "|", 1, border_attr)

        self._write(footer_top, 0, "+" + "-" * (width - 2) + "+", width, border_attr)
        if self.message:
            attr = self._style(6, curses.A_BOLD) if self.message_error else self._style(4)
            self._write(height - 2, 1, self.message, width - 2, attr)
        count = "{:>2}/{}".format(min(selected + 1, len(items)), len(items)) if items else " 0/0"
        scroll_hint = "UP/DOWN MOVE   ENTER SELECT   ESC/q BACK   1-9 JUMP"
        if len(items) > visible_count:
            scroll_hint += "   PGUP/PGDN SCROLL"
        self._write(height - 1, 1, scroll_hint, width - len(count) - 3, self._style(5))
        self._write(height - 1, width - len(count) - 2, count, len(count), self._style(2, curses.A_BOLD))
        self.screen.refresh()
        return visible_count

    def choose(self, title: str, subtitle: str, options: List[str]) -> Optional[int]:
        if not options:
            self.draw(title, subtitle, ["No items found."])
            self.screen.getch()
            return None

        selected = 0
        offset = 0
        while True:
            old_offset = offset
            visible_count = self.draw(title, subtitle, options, selected, offset)
            if selected < offset:
                offset = selected
            elif selected >= offset + visible_count:
                offset = selected - visible_count + 1

            # Redraw after adjusting scroll position.
            if offset != old_offset:
                self.draw(title, subtitle, options, selected, offset)
            key = self.screen.getch()
            if key in (curses.KEY_UP, ord("k")):
                selected = (selected - 1) % len(options)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = (selected + 1) % len(options)
            elif key in (curses.KEY_PPAGE,):
                selected = max(0, selected - visible_count)
            elif key in (curses.KEY_NPAGE,):
                selected = min(len(options) - 1, selected + visible_count)
            elif key == curses.KEY_HOME:
                selected = 0
                offset = 0
            elif key == curses.KEY_END:
                selected = len(options) - 1
            elif key in (curses.KEY_ENTER, 10, 13):
                return selected
            elif key in (27, curses.KEY_BACKSPACE, 127, 8, ord("q")):
                return None
            elif ord("1") <= key <= ord("9"):
                index = offset + key - ord("1")
                if index < min(len(options), offset + visible_count):
                    return index
            elif key == curses.KEY_RESIZE:
                continue

    def ask(self, prompt: str, initial: str = "") -> Optional[str]:
        height, width = self.screen.getmaxyx()
        if height < 12 or width < 38:
            return None
        text = list(initial)
        cursor = len(text)
        input_y = max(6, height // 2)
        while True:
            self.screen.erase()
            host = self.current_host.upper()
            self._write(0, 0, " " * width, width, self._style(1))
            self._write(0, 1, " TMUX / CONTROL ", width - 2, self._style(1, curses.A_BOLD))
            self._write(0, max(1, width - len(host) - 7), "HOST  " + host, len(host) + 6, self._style(1))
            box_left, box_width = 2, width - 4
            self._write(3, box_left, "+" + "-" * (box_width - 2) + "+", box_width, self._style(2))
            self._write(4, box_left, "|", 1, self._style(2))
            self._write(4, box_left + 2, prompt, box_width - 4, self._style(2, curses.A_BOLD))
            self._write(4, width - box_left - 1, "|", 1, self._style(2))
            self._write(input_y - 1, box_left, "+" + "-" * (box_width - 2) + "+", box_width, self._style(2))
            self._write(input_y, box_left, "|", 1, self._style(2))
            self._write(input_y, width - box_left - 1, "|", 1, self._style(2))
            self._write(input_y + 1, box_left, "+" + "-" * (box_width - 2) + "+", box_width, self._style(2))
            field_width = max(1, box_width - 4)
            value = "".join(text)
            start = max(0, cursor - field_width + 1)
            visible = value[start : start + field_width]
            self._write(input_y, box_left + 2, visible, field_width, self._style(3))
            self._write(height - 2, 1, "ENTER SAVE   ESC CANCEL   CTRL-U CLEAR", width - 2, self._style(5))
            try:
                curses.curs_set(1)
            except curses.error:
                pass
            self.screen.move(input_y, box_left + 2 + min(field_width - 1, cursor - start))
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in ("\n", "\r", curses.KEY_ENTER):
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
                result = "".join(text).strip()
                return result or None
            if key == "\x1b":
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
                return None
            if key in ("\x15",):  # Ctrl-U
                text, cursor = [], 0
            elif key in ("\x7f", "\b", curses.KEY_BACKSPACE):
                if cursor > 0:
                    del text[cursor - 1]
                    cursor -= 1
            elif key == curses.KEY_DC:
                if cursor < len(text):
                    del text[cursor]
            elif key == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif key == curses.KEY_RIGHT:
                cursor = min(len(text), cursor + 1)
            elif key == curses.KEY_HOME:
                cursor = 0
            elif key == curses.KEY_END:
                cursor = len(text)
            elif isinstance(key, str) and key.isprintable() and len(text) < 160:
                text.insert(cursor, key)
                cursor += 1

    def confirm(self, prompt: str) -> bool:
        return self.choose("Confirm", prompt, ["No, go back", "Yes, continue"]) == 1

    def run_visible(self, args: List[str]) -> Tuple[int, str]:
        """Temporarily give the terminal to an attached tmux client."""
        curses.def_prog_mode()
        curses.endwin()
        try:
            result = subprocess.run(args, check=False)
            code = result.returncode
            message = "" if code == 0 else "tmux exited with status {}".format(code)
        except OSError as exc:
            code, message = 127, str(exc)
        curses.reset_prog_mode()
        self.screen.clear()
        self.screen.refresh()
        return code, message

    def enter_session(self, name: str) -> None:
        if self.tmux.host is None and os.environ.get("TMUX"):
            code, _, message = self.tmux.call("switch-client", "-t", name)
        else:
            command = self.tmux.interactive_args("attach-session", "-t", name)
            code, message = self.run_visible(command)
        self.say(
            message or ("Session opened. Detach with Ctrl-b then d." if code == 0 else "Could not open session."),
            code != 0,
        )

    def create_session(self, host: Optional[Host] = None) -> None:
        previous_tmux, previous_host = self.tmux, self.current_host
        self.tmux = Tmux(host)
        self.current_host = host.label if host else socket.gethostname().split(".")[0]
        try:
            name = self.ask("Name for the new session:")
            if not name:
                return
            code, _, message = self.tmux.call("new-session", "-d", "-s", name)
            if code:
                self.say(message or "Could not create session.", True)
                return
            self.enter_session(name)
        finally:
            self.tmux, self.current_host = previous_tmux, previous_host

    def configure_hosts(self) -> None:
        while True:
            hosts = self.host_config.load()
            rows = ["[{}]  {}".format(host.label, host.target) for host in hosts]
            rows.extend(["+  Add SSH host", "Back"])
            selected = self.choose(
                "SSH hosts",
                "Edit destinations in {}. New hosts need SSH access and tmux.".format(self.host_config.path.name),
                rows,
            )
            if selected is None or selected == len(rows) - 1:
                return
            if selected == len(hosts):
                self.edit_host()
            else:
                self.host_actions(hosts[selected])

    def host_actions(self, host: Host) -> None:
        selected = self.choose(
            "Host: {}".format(host.label),
            "SSH destination: {}".format(host.target),
            ["Edit host", "Remove host", "Back"],
        )
        if selected == 0:
            self.edit_host(host)
        elif selected == 1 and self.confirm("Remove host '{}' from the menu?".format(host.label)):
            hosts = [item for item in self.host_config.load() if item.label != host.label]
            self._save_hosts(hosts)

    def edit_host(self, existing: Optional[Host] = None) -> None:
        initial_label = existing.label if existing else ""
        label = self.ask("Host label (letters, digits, spaces, or _):", initial_label)
        if not label:
            return
        key = self.host_config.key(label)
        if not key or not re.fullmatch(r"[A-Z0-9_]+", key) or not re.search(r"[A-Z0-9]", key):
            self.say("Use a host label containing letters, digits, spaces, or underscores.", True)
            return
        initial_target = existing.target if existing else ""
        target = self.ask("SSH target or alias:", initial_target)
        if not target:
            return
        if not self.host_config.valid_target(target):
            self.say("Use an SSH alias, hostname, IP, or user@host target.", True)
            return
        hosts = self.host_config.load()
        if any(item.label == key and (existing is None or item.label != existing.label) for item in hosts):
            self.say("That host label is already in use.", True)
            return
        if existing is not None:
            # Editing may change the label, so remove the original entry by its
            # old label before writing the updated host.
            hosts = [item for item in hosts if item.label != existing.label]
        else:
            hosts = [item for item in hosts if item.label != key]
        hosts.append(Host(key, target))
        self._save_hosts(hosts)

    def _save_hosts(self, hosts: List[Host]) -> None:
        try:
            self.host_config.save(hosts)
        except OSError as exc:
            self.say("Could not save .env: {}".format(exc), True)
        else:
            self.say("SSH hosts saved to .env.")

    def create_window(self, session: str) -> None:
        name = self.ask("Name for the new window (optional):")
        args = ["new-window", "-t", session]
        if name:
            args.extend(["-n", name])
        code, _, message = self.tmux.call(*args)
        self.say(message or ("Window created." if code == 0 else "Could not create window."), code != 0)

    def session_menu(self, session: Session) -> None:
        while True:
            selected = self.choose(
                "Session: {}".format(session.name),
                "{} window(s), {} attached client(s)".format(session.windows, session.attached),
                ["Open session", "Browse windows", "Rename session", "Close session", "Back"],
            )
            if selected is None or selected == 4:
                return
            if selected == 0:
                self.enter_session(session.name)
            elif selected == 1:
                self.window_menu(session.name)
            elif selected == 2:
                name = self.ask("New session name:", session.name)
                if name and name != session.name:
                    code, _, message = self.tmux.call("rename-session", "-t", session.name, name)
                    self.say(message or ("Session renamed." if code == 0 else "Could not rename session."), code != 0)
                    if code == 0:
                        session.name = name
            elif selected == 3 and self.confirm(
                "Close session '{}' and all its windows?".format(session.name)
            ):
                code, _, message = self.tmux.call("kill-session", "-t", session.name)
                self.say(message or ("Session closed." if code == 0 else "Could not close session."), code != 0)
                return

    def window_menu(self, session: str) -> None:
        while True:
            windows = self.tmux.windows(session)
            labels = [
                "{} {}: {}  ({} pane(s))".format(
                    "*" if window.active else " ", window.index, window.name, window.panes
                )
                for window in windows
            ]
            labels.extend(["+  Create a window", "Back"])
            selected = self.choose("Windows in {}".format(session), "* marks the active window", labels)
            if selected is None or selected == len(labels) - 1:
                return
            if selected == len(windows):
                self.create_window(session)
                continue

            window = windows[selected]
            target = "{}:{}".format(session, window.index)
            action = self.choose(
                "Window: {}".format(window.name),
                "Session {}, window {}".format(session, window.index),
                ["Open this window", "Browse panes", "Rename window", "Close window", "Back"],
            )
            if action is None or action == 4:
                continue
            if action == 0:
                code, _, message = self.tmux.call("select-window", "-t", target)
                if code:
                    self.say(message or "Could not select window.", True)
                else:
                    self.enter_session(session)
            elif action == 1:
                self.pane_menu(session, window)
            elif action == 2:
                name = self.ask("New window name:", window.name)
                if name and name != window.name:
                    code, _, message = self.tmux.call("rename-window", "-t", target, name)
                    self.say(message or ("Window renamed." if code == 0 else "Could not rename window."), code != 0)
            elif action == 3 and self.confirm("Close window '{}'?".format(window.name)):
                code, _, message = self.tmux.call("kill-window", "-t", target)
                self.say(message or ("Window closed." if code == 0 else "Could not close window."), code != 0)

    def pane_menu(self, session: str, window: Window) -> None:
        window_target = "{}:{}".format(session, window.index)
        while True:
            panes = self.tmux.panes(window_target)
            labels = [
                "{} Pane {}: {}".format("*" if pane.active else " ", pane.index, pane.command)
                for pane in panes
            ]
            labels.extend(["+  Split side-by-side", "+  Split top/bottom", "Back"])
            selected = self.choose(
                "Panes in {}:{}".format(session, window.index),
                "* marks the active pane",
                labels,
            )
            if selected is None or selected == len(labels) - 1:
                return
            if selected == len(panes):
                self.split_pane(window_target, "-h", session)
                continue
            if selected == len(panes) + 1:
                self.split_pane(window_target, "-v", session)
                continue

            pane = panes[selected]
            target = "{}.{}".format(window_target, pane.index)
            action = self.choose(
                "Pane {}".format(pane.index),
                "Running: {}".format(pane.command),
                ["Focus pane", "Split side-by-side", "Split top/bottom", "Close pane", "Back"],
            )
            if action is None or action == 4:
                continue
            if action == 0:
                code, _, message = self.tmux.call("select-pane", "-t", target)
                if code:
                    self.say(message or "Could not select pane.", True)
                else:
                    self.enter_session(session)
            elif action == 1:
                self.split_pane(target, "-h", session)
            elif action == 2:
                self.split_pane(target, "-v", session)
            elif action == 3 and self.confirm("Close pane {}?".format(pane.index)):
                code, _, message = self.tmux.call("kill-pane", "-t", target)
                self.say(message or ("Pane closed." if code == 0 else "Could not close pane."), code != 0)

    def split_pane(self, target: str, direction: str, session: str) -> None:
        code, _, message = self.tmux.call("split-window", direction, "-t", target)
        if code:
            self.say(message or "Could not split pane.", True)
        else:
            self.enter_session(session)

    def help(self) -> None:
        self.draw(
            "Quick guide",
            "Navigate tmux with simple menus.",
            [
                "Use Up/Down or j/k to move, then Enter to choose.",
                "Use 1-9 to choose a visible item; PgUp/PgDn scroll long lists.",
                "Local sessions are untagged; remote sessions show their host label.",
                "Edit SSH hosts from the home screen; targets are stored in .env.",
                "Open a session to work in it. Press Ctrl-b, then d to return.",
                "Closing a session, window, or pane ends the processes inside it.",
                "",
                "Press any key to return.",
            ],
        )
        self.screen.getch()

    def run(self, hosts_only: bool = False) -> None:
        if hosts_only:
            self.configure_hosts()
        while True:
            hosts = self.host_config.load()
            sessions = self.local_tmux.sessions()
            remote_sessions = []
            offline_hosts = []
            for host in hosts:
                backend = Tmux(host)
                remote_sessions.extend(backend.sessions())
                if backend.connection_error:
                    offline_hosts.append(host.label)
            sessions.extend(remote_sessions)

            if offline_hosts:
                self.say("SSH unavailable: {}".format(", ".join(offline_hosts)), True)
            elif self.message.startswith("SSH unavailable:"):
                self.say("")

            labels = []
            local_count = len(sessions) - len(remote_sessions)
            for session in sessions:
                host_tag = "[{}] ".format(session.host.label) if session.host else ""
                labels.append(
                    "{:<34}  {:>2} windows   {:>2} attached".format(
                        (host_tag + session.name)[:34], session.windows, session.attached
                    )
                )
            local_create = len(labels)
            labels.append("+  Create local session")
            remote_create_start = len(labels)
            labels.extend("+  Create session on [{}]".format(host.label) for host in hosts)
            host_config_index = len(labels)
            labels.extend(["[SSH]  Configure hosts", "?  Help", "Quit"])

            if not sessions:
                subtitle = "No active sessions. Create one locally or add an SSH host."
            else:
                subtitle = "{} local and {} remote session(s). Remote sessions are tagged by host.".format(
                    local_count, len(remote_sessions)
                )
            selected = self.choose("All sessions", subtitle, labels)
            if selected is None or selected == len(labels) - 1:
                return
            if selected < len(sessions):
                session = sessions[selected]
                self.tmux = Tmux(session.host)
                self.current_host = session.host.label if session.host else socket.gethostname().split(".")[0]
                self.session_menu(session)
                self.tmux = self.local_tmux
                self.current_host = socket.gethostname().split(".")[0]
            elif selected == local_create:
                self.create_session()
            elif remote_create_start <= selected < host_config_index:
                self.create_session(hosts[selected - remote_create_start])
            elif selected == host_config_index:
                self.configure_hosts()
            elif selected == host_config_index + 1:
                self.help()


def main(screen: "curses._CursesWindow") -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    try:
        curses.set_escdelay(25)
    except AttributeError:
        pass

    if not shutil.which("tmux"):
        screen.addstr(0, 0, "tmux is not installed or is not on PATH.")
        screen.addstr(2, 0, "Install tmux on this machine, then run this program again.")
        screen.addstr(4, 0, "Press any key to exit.")
        screen.refresh()
        screen.getch()
        return

    TmuxUI(screen).run("--hosts" in sys.argv[1:])


if __name__ == "__main__":
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print("Usage: tmux-menu [--hosts] [--help]")
        print("The dashboard combines local sessions and SSH hosts from .env.")
        sys.exit(0)
    unknown = [arg for arg in sys.argv[1:] if arg != "--hosts"]
    if unknown:
        print("Unknown option: {}. Remote sessions are listed automatically.".format(unknown[0]), file=sys.stderr)
        sys.exit(2)
    try:
        curses.wrapper(main)
    except curses.error as exc:
        print("Could not start the terminal interface: {}".format(exc), file=sys.stderr)
        print("Run this from a terminal session (for example, after SSH login).", file=sys.stderr)
        sys.exit(1)

