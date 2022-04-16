import os
import subprocess
import sys
import curses
from time import sleep
from curses import wrapper
from math import floor


class AppGUIMixin:

    frame_extra_lenght = 4
    frame_extra_height = 3
    arrow = 0

    def _frame(self, str, width):
        # return "█ " + str.ljust(width - 4) + " █"
        return str

    def _draw(self, stdscr, maps):
        # Clear screen
        stdscr.clear()

        needed_lines = max(len(maps) + 2 + self.frame_extra_height, 10)
        needed_width = max(len(self.path), 50) + self.frame_extra_lenght
        available_lines, available_width = stdscr.getmaxyx()

        if needed_lines < available_lines:
            pad_top = floor((available_lines - needed_lines) / 2)
        else:
            pad_top = 0

        if needed_width < available_width:
            pad_left = floor((available_width - needed_width) / 2)
        else:
            pad_left = 1

        c = pad_top

        # stdscr.addstr(c, pad_left, "█" * needed_width)
        # c += 1

        stdscr.addstr(c, pad_left, self._frame(f"  {self.path}", needed_width))
        c += 1

        stdscr.addstr(c, pad_left, self._frame("", needed_width))
        c += 1

        for index, (keycombo, func) in enumerate(maps.items()):
            if index == self.arrow:
                a = "> "
            else:
                a = "  "
            stdscr.addstr(
                c,
                pad_left,
                self._frame(a + f"{func.__doc__} [{keycombo}]", needed_width),
            )
            c += 1

        stdscr.addstr(c, pad_left, self._frame("", needed_width))
        c += 1

        # stdscr.addstr(c, pad_left, "█" * needed_width)
        # c += 1

        curses.curs_set(0)

        stdscr.refresh()
        return stdscr.getkey()

    def draw(self, *args, **kwargs):
        return wrapper(self._draw, *args, **kwargs)

    def _flicker(self, stdscr):
        stdscr.clear()
        rows, cols = stdscr.getmaxyx()
        for row in range(rows):
            stdscr.addstr(row, 0, "?" * (cols - 1))
        stdscr.refresh()
        sleep(0.05)

    def flicker(self, *args, **kwargs):
        return wrapper(self._flicker, *args, **kwargs)

    def getactivemaps(self):
        activemaps = {}
        for (keycombo, (func, when)) in self.maps.items():
            if when(self):
                activemaps[keycombo] = func
        return activemaps

    def _main(self):
        while True:

            activemaps = self.getactivemaps()
            print(activemaps)
            activemaps = dict(
                sorted(activemaps.items(), key=lambda i: i[1].__doc__ or str(i[1]))
            )
            key = self.draw(activemaps)

            if key in ("j", "KEY_DOWN"):
                self.arrow = min(self.arrow + 1, len(activemaps) - 1)
                continue
            elif key in ("k", "KEY_UP"):
                self.arrow = max(self.arrow - 1, 0)
                continue
            elif key == "\n":
                func = list(activemaps.values())[self.arrow]
                try:
                    func(self)
                except subprocess.CalledProcessError as exc:
                    print(exc)

            keyfound = False
            for (keycombo, func) in activemaps.items():
                if keycombo == key:
                    keyfound = True
                    try:
                        func(self)
                    except subprocess.CalledProcessError as exc:
                        print(exc)
            if not keyfound:
                self.flicker()

    def main(self):
        try:
            self._main()
        except KeyboardInterrupt:
            print("^C", file=sys.stderr)
            sys.exit(130)


class App(AppGUIMixin):
    def __init__(self):
        self.maps = {}
        self.hist = []
        self.path = None

    def go(self, path, savehist=True):
        if self.path and savehist:
            self.hist.append(self.path)

        if self.path:
            path = os.path.join(self.path, path)

        self.path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(self.path):
            self.dir = self.path
        else:
            self.dir = os.path.dirname(self.path)
        try:
            self.git = self.output(
                "git rev-parse --show-toplevel 2> /dev/null", shell=True
            )
        except subprocess.CalledProcessError:
            self.git = None

    def map(self, keycombo, when=lambda _: True):
        def decorator(func):
            self.maps[keycombo] = (func, when)
            return func

        return decorator

    def output(self, *args, **kwargs):
        kwargs.setdefault("cwd", self.dir)
        resp = subprocess.check_output(*args, **kwargs)
        return resp.decode().strip("\n")

    def run(self, *args, **kwargs):
        kwargs.setdefault("cwd", self.dir)
        subprocess.Popen(*args, **kwargs).wait()

    def outputgo(self, *args, **kwargs):
        kwargs.setdefault("cwd", self.dir)
        path = self.output(*args, **kwargs)
        self.go(path)


def whengit(ctx):
    return app.git


def whengitroot(ctx):
    return app.git and app.git == ctx.path


def whenfile(ctx):
    return ctx.dir != ctx.path


def whendir(ctx):
    return ctx.dir == ctx.path


app = App()


class FindGitFileVerb(Verb):
    help = 'Find git files'
    map = 'f'
    when = whengitroot
    def __call__(self, app):
        app.outputgo("git ls-files | fzf --preview 'cat -n {}'",
                shell=True, cwd=ctx.git)


class FindFilesVerb(Verb):
    help = 'Find files'
    map = 'G'
    when = whendir
    def __call__(self, app):
        ctx.outputgo("find . -type f | fzf --preview 'cat -n {}'", shell=True)

class ListDirsVerb(Verb):
    help = 'List dir'
    map = 'l'
    when = whendir
    def __call__(self, app):
        ctx.outputgo("ls | fzf", shell=True)


class ParentDirVerb(Verb):
    help = "Goto parent dir"
    map = 'u'
    when = whendir
    def __call__(self, app):
        newpath = os.path.dirname(ctx.path)
        ctx.go(newpath)


class GotoGitRootVerb(Verb):
    help = "Goto git root"
    map = 'p'

    def when(ctx):
        return ctx.git and not ctx.path == ctx.git

    def __call__(self, app):
        newpath = os.path.dirname(ctx.path)
        ctx.go(newpath)


class ProjectsVerb(Verb):
    help = "Find git projects"
    map = 'P'

    def when(ctx):
        not whengit(ctx)

    def __call__(self, app):
        match = ctx.output(
            """find -name .git -maxdepth 4 2>/dev/null |
                    xargs realpath | xargs dirname | fzf""",
            shell=True,
        )
        ctx.go(match)


class BackVerb(Verb):
    help = "Go back"
    map = 'b'

    def when(ctx):
        return ctx.hist

    def __call__(self, app):
    path = ctx.hist.pop(-1)
    ctx.go(path, savehist=False)


class ProjectsVerb(Verb):
    help = "Quit"
    map = 'q'
    def __call__(self, app):
        sys.exit(0)

class RunLazygitVerb(CommandVerb):
    map = 'g'
    when = whengitroot
    command = 'lazygit'

class RunLessVerb(CommandVerb):
    map = 'x'
    when = whendir
    command = 'less {}'

class RunBashVerb(CommandVerb):
    map = 's'
    when = whendir
    command = 'bash'

class RunEditVerb(CommandVerb):
    map = 'e'
    command = "nvr +FloatermHide {}"

class RunBlackVerb(CommandVerb):
    map = 'B'
    def when(ctx):
        return whenfile(ctx) and ctx.path.endswith(".py")
    command = "black {}"


app.go("~/byrd/warehouse/requirements.txt")
app.main()
