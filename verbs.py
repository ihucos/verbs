import os
import subprocess
import sys
import curses
import shlex
from time import sleep
from curses import wrapper
from math import floor

# https://stackoverflow.com/questions/5881873/python-find-all-classes-which-inherit-from-this-one
def inheritors(klass):
    subclasses = set()
    work = [klass]
    while work:
        parent = work.pop()
        for child in parent.__subclasses__():
            if child not in subclasses:
                subclasses.add(child)
                work.append(child)
    return subclasses


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

        needed_lines = max(len(verbs) + 2 + self.frame_extra_height, 10)
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

        stdscr.addstr(c, pad_left, self._frame(f"{self.path}", needed_width))
        c += 1

        stdscr.addstr(c, pad_left, self._frame("", needed_width))
        c += 1

        last_section = None
        for index, verb in enumerate(verbs):

            section = verb.get_section(self)
            if section != last_section:
                stdscr.addstr(c, pad_left, self._frame("", needed_width))
                c += 1
                stdscr.addstr(
                    c,
                    pad_left,
                    self._frame(f"{section.capitalize():}", needed_width),
                )
                c += 1

            if index == self.arrow:
                a = "  *"
            else:
                a = f"   "
            help = verb.get_help(self)
            stdscr.addstr(
                c, pad_left, self._frame(a + f"[{verb.map}] {help}", needed_width),
            )
            c += 1

            last_section = section

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
            for verb in inheritors(Verb):
                verb_obj = verb()
                show = verb_obj.show(self)
                if getattr(verb, "map", False) and show:
                    verbs.append(verb_obj)
            # assert 0, verbs
            verbs.sort(key=lambda v: (v.get_section(self), v.get_help(self)))

            key = self.draw(verbs)

            if key in ("j", "KEY_DOWN"):
                self.arrow = min(self.arrow + 1, len(verbs) - 1)
            elif key in ("k", "KEY_UP"):
                self.arrow = max(self.arrow - 1, 0)
            elif key == "\n":
                verb = list(verbs)[self.arrow]
                try:
                    verb(self)
                except subprocess.CalledProcessError as exc:
                    print(exc)
            else:
                keyfound = False
                for verb in verbs:
                    if verb.map == key:
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

        path = os.path.expanduser(path)

        if self.path and savehist:
            self.hist.append(self.path)

        if self.path:
            path = os.path.join(self.path, path)

        self.path = os.path.abspath(path)
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


def and_(*show_mixins):
    class Tmp:
        def show(self, app):
            return all(i().show(app) for i in show_mixins)

    return Tmp


def not_(mixin):
    class Tmp:
        def show(self, app):
            return not mixin().show(app)

    return Tmp


class ShowIfGitMixin:
    section = "git project"

    def show(self, app):
        return app.git


class ShowIfFileMixin:

    def get_section(self, app):
        return f'File {app.path}'

    def show(self, app):
        return os.path.isfile(app.path)


class ShowIfDirMixin:
    section = "directory"

    def show(self, app):
        return os.path.isdir(app.path)


class Verb:
    section = "other"

    def show(self, app):
        return True

    def get_help(self, app):
        return getattr(self, "help", self.__class__.__name__)

    def get_section(self, app):
        return self.section


class CommandVerb(Verb):
    def get_help(self, app):
        return f"Run `{self.command}`"

    def __call__(self, app):
        run = shlex.quote(app.path)
        app.run(self.command.format(run), shell=True)


class FindGitFileVerb(ShowIfGitMixin, Verb):
    help = "Find files"
    map = "f"

    def __call__(self, app):
        app.outputgo(
            "git ls-files | fzf --preview 'cat -n {}'", shell=True, cwd=app.git
        )


class FindFilesVerb(ShowIfDirMixin, Verb):
    help = "Find files"
    map = "G"

    def __call__(self, app):
        app.outputgo("find . -type f | fzf --preview 'cat -n {}'", shell=True)


class ListDirsVerb(ShowIfDirMixin, Verb):
    help = "ls"
    map = "l"
    section = "navigation"

    def __call__(self, app):
        app.outputgo("ls | fzf", shell=True)


class ParentDirVerb(Verb):
    help = "Up"
    map = "u"
    section = "navigation"

    def show(self, app):
        return app.path != "/"

    def __call__(self, app):
        newpath = os.path.dirname(app.path)
        app.go(newpath)


class ListProjectsVerb(and_(not_(ShowIfGitMixin), ShowIfDirMixin), Verb):
    help = "Find projects"
    map = "P"

    def __call__(self, app):
        match = app.output(
            """find -name .git -maxdepth 4 2>/dev/null |
                    xargs realpath | xargs dirname | fzf""",
            shell=True,
        )
        app.go(match)


class BackVerb(Verb):
    help = "Back"
    map = "b"
    section = "navigation"

    def show(self, app):
        return app.hist

    def __call__(self, app):
        path = app.hist.pop(-1)
        app.go(path, savehist=False)


class QuitVerb(Verb):
    help = "Quit"
    map = "q"

    def __call__(self, app):
        sys.exit(0)


class CdHomeVerb(Verb):
    help = "Goto home"
    map = "h"
    section = "navigation"
    help = "Home"

    # def get_help(self, app):
    #    home =  os.path.expanduser('~')
    #    return f'{home}'

    def __call__(self, app):
        app.go("~")


class CdGitRootVerb(Verb):
    help = "Git root"
    map = "p"
    section = "navigation"

    def show(self, app):
        return app.git and not app.path == app.git

    def __call__(self, app):
        app.go(app.git)


class RunLazygitVerb(ShowIfGitMixin, CommandVerb):
    map = "g"
    command = "lazygit"


class RunLessVerb(ShowIfFileMixin, CommandVerb):
    map = "x"
    command = "less {}"
    help = "View"


class RunBashVerb(ShowIfDirMixin, CommandVerb):
    map = "s"
    command = "bash"
    # help = 'Open shell here'


class RunEditVerb(ShowIfFileMixin, CommandVerb):
    map = "e"
    command = "nvr +FloatermHide {}"
    help = "Edit"


class RunBlackVerb(CommandVerb):
    map = "B"

    def show(self, app):
        return ShowIfDirMixin().show(app) and app.path.endswith(".py")

    command = "black {}"


if __name__ == "__main__":
    app = App()
    app.go("~/byrd/warehouse/requirements.txt")
    app.main()
