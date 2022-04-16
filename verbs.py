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


@app.map("f", when=lambda ctx: whengitroot(ctx))
def findgitfile(ctx):
    "Find git files"
    ctx.outputgo("git ls-files | fzf --preview 'cat -n {}'", shell=True, cwd=ctx.git)


@app.map("F", when=whendir)
def findgitfile(ctx):
    "Find files"
    ctx.outputgo("find . -type f | fzf --preview 'cat -n {}'", shell=True)


@app.map("l", when=whendir)
def findls(ctx):
    "List dir"
    ctx.outputgo("ls | fzf", shell=True)


@app.map("g", when=whengitroot)
def lazygit(ctx):
    "Run `lazygit`"
    ctx.run("lazygit")


@app.map("s", when=whendir)
def shell(ctx):
    "Run `bash`"
    ctx.run("bash")


@app.map("x", when=whenfile)
def less(ctx):
    "Run `less`"
    ctx.run(["less", ctx.path])


@app.map("u", when=lambda ctx: ctx.path != "/")
def up(ctx):
    "Goto parent dir"
    newpath = os.path.dirname(ctx.path)
    ctx.go(newpath)


@app.map("e", when=whenfile)
def edit(ctx):
    "Run `vim`"
    line = 0
    ctx.run(["nvr", "+FloatermHide", f"+e {ctx.path}", f"+{line}"])


@app.map("p", when=lambda ctx: ctx.git and not ctx.path == ctx.git)
def project(ctx):
    "Goto git root"
    ctx.go(ctx.git)


@app.map("P", when=lambda ctx: not whengit(ctx))
def projects(ctx):
    "Find git projects"
    match = ctx.output(
        """find -name .git -maxdepth 4 2>/dev/null |
                xargs realpath | xargs dirname | fzf""",
        shell=True,
    )
    ctx.go(match)


@app.map("b", when=lambda ctx: ctx.hist)
def back(ctx):
    "Go back"
    path = ctx.hist.pop(-1)
    ctx.go(path, savehist=False)


@app.map("B", when=lambda ctx: whenfile(ctx) and ctx.path.endswith(".py"))
def black(ctx):
    ctx.run(["black", ctx.path])


@app.map("q")
def black(ctx):
    "Quit"
    sys.exit(0)


app.go("~/byrd/warehouse/requirements.txt")
app.main()
