import os
import subprocess
import sys
import curses
import shlex
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

    def _draw(self, stdscr, verbs):
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

        for index, verbs in enumerate(verb.items()):
            help = verb.get_help(self)
            if index == self.arrow:
                a = "> "
            else:
                a = "  "
            stdscr.addstr(
                c, pad_left, self._frame(a + f"{help} [{verb.map}]", needed_width),
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

    def _main(self):
        while True:

            verbs = []
            for verb in Verb.__subclasses__():
                print(verb)
                verb_obj = verb()
                if not getattr(verb, 'meta', False) and verb_obj.show(self):
                    verbs.append(verb_obj)

            key = self.draw(verbs)

            if key in ("j", "KEY_DOWN"):
                self.arrow = min(self.arrow + 1, len(verbs) - 1)
                continue
            elif key in ("k", "KEY_UP"):
                self.arrow = max(self.arrow - 1, 0)
                continue
            elif key == "\n":
                func = list(verbs.values())[self.arrow]
                try:
                    func(self)
                except subprocess.CalledProcessError as exc:
                    print(exc)

            keyfound = False
            for verb in verbs.items():
                if verb.amp == key:
                    keyfound = True
                    try:
                        verb(self)
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



class ShowIfGitMixin:
    def show(self, app):
        return app.git


class ShowIfFileMixin:
    def show(self, app):
        return ctx.dir != ctx.path

class ShowIfDirMixin:
    def show(self, ctx):
        return ctx.dir != ctx.path


class Verb:
    def get_help(self, app):
        return getattr(self, "help", self.__class__.__name__)


class CommandVerb(Verb):

    meta = True

    def show(self, app):
        return True

    def __call__(self, app):
        def __call__(self, app):
            run = shlex.quote(app.path)
            app.run(self.command.format(run))


class FindGitFileVerb(Verb, ShowIfGitMixin):
    help = "Find git files"
    map = "f"

    def __call__(self, app):
        app.outputgo(
            "git ls-files | fzf --preview 'cat -n {}'", shell=True, cwd=ctx.git
        )


class FindFilesVerb(Verb, ShowIfDirMixin):
    help = "Find files"
    map = "G"

    def __call__(self, app):
        ctx.outputgo("find . -type f | fzf --preview 'cat -n {}'", shell=True)


class ListDirsVerb(Verb, ShowIfDirMixin):
    help = "List dir"
    map = "l"

    def __call__(self, app):
        ctx.outputgo("ls | fzf", shell=True)


class ParentDirVerb(Verb, ShowIfDirMixin):
    help = "Goto parent dir"
    map = "u"

    def __call__(self, app):
        newpath = os.path.dirname(ctx.path)
        ctx.go(newpath)


class GotoGitRootVerb(Verb):
    help = "Goto git root"
    map = "p"

    def show(self, ctx):
        return ctx.git and not ctx.path == ctx.git

    def __call__(self, app):
        newpath = os.path.dirname(ctx.path)
        ctx.go(newpath)


class ProjectsVerb(Verb, ShowIfGitMixin):
    help = "Find git projects"
    map = "P"

    def __call__(self, app):
        match = ctx.output(
            """find -name .git -maxdepth 4 2>/dev/null |
                    xargs realpath | xargs dirname | fzf""",
            shell=True,
        )
        ctx.go(match)


class BackVerb(Verb):
    help = "Go back"
    map = "b"

    def show(self, ctx):
        return ctx.hist

    def __call__(self, app):
        path = ctx.hist.pop(-1)
        ctx.go(path, savehist=False)


class ProjectsVerb(Verb):
    help = "Quit"
    map = "q"

    def __call__(self, app):
        sys.exit(0)


class RunLazygitVerb(CommandVerb, ShowIfGitMixin):
    map = "g"
    command = "lazygit"


class RunLessVerb(CommandVerb, ShowIfDirMixin):
    map = "x"
    command = "less {}"


class RunBashVerb(CommandVerb, ShowIfDirMixin):
    map = "s"
    command = "bash"


class RunEditVerb(CommandVerb):
    map = "e"
    command = "nvr +FloatermHide {}"


class RunBlackVerb(CommandVerb):
    map = "B"

    def show(self, ctx):
        return whenfile(ctx) and ctx.path.endswith(".py")

    command = "black {}"


if __name__ == "__main__":
    app = App()
    app.go("~/byrd/warehouse/requirements.txt")
    app.main()