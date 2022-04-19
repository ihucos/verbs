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

    arrow = 0
    query = None

    def _draw(self, stdscr, verbs):
        # Clear screen
        stdscr.clear()

        pad_top = 1
        pad_left = 1

        c = pad_top

        stdscr.addstr(c, 1, "Scope")
        c += 1

        stdscr.addstr(c, 1, "  " + app.path_repr() + " ")
        c += 1

        stdscr.addstr(c, pad_left, "")
        c += 1

        if self.query:
            stdscr.addstr(c, 1, "Query")
            c += 1

            stdscr.addstr(c, 1, "  " + self.query + " ")
            c += 1

            stdscr.addstr(c, pad_left, "")
            c += 1

            stdscr.addstr(c, pad_left, "Commands")
            c += 1

        for index, verb in enumerate(verbs):
            if index == self.arrow:
                a = "*"
            else:
                a = " "
            stdscr.addstr(c, pad_left, f"{a} {verb.map} - {verb.help}")
            c += 1

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
                verb_obj = verb(self)
                show = verb_obj.show()
                if getattr(verb, "map", False) and show:
                    verbs.append(verb_obj)
            # assert 0, verbs
            verbs.sort(key=lambda v: v.help)

            key = self.draw(verbs)

            if key in ("j", "KEY_DOWN"):
                self.arrow = min(self.arrow + 1, len(verbs) - 1)
            elif key in ("k", "KEY_UP"):
                self.arrow = max(self.arrow - 1, 0)
            elif key == "\n":
                verb = list(verbs)[self.arrow]
                try:
                    verb()
                except subprocess.CalledProcessError as exc:
                    print(exc)
            else:
                keyfound = False
                for verb in verbs:
                    if verb.map == key:
                        keyfound = True
                        try:
                            verb()
                        except subprocess.CalledProcessError as exc:
                            print(exc)
                if not keyfound:
                    if key != " ":  # hack for my vim setup
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

    def go(self, path, line=None, savehist=True):

        self.line = line

        path = os.path.expanduser(path)

        if self.path and savehist:
            self.hist.append((self.path, self.line))

        if self.path:
            path = os.path.join(self.dir, path)

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

    def run(self, *args, anykey=False, **kwargs):
        kwargs.setdefault("cwd", self.dir)
        subprocess.Popen(*args, **kwargs).wait()
        if anykey:
            self.run(
                [
                    "/bin/bash",
                    "-c",
                    "read -rsp $'Press any key to continue...\n' -n1 key",
                ]
            )

    def outputgo(self, *args, **kwargs):
        kwargs.setdefault("cwd", self.dir)
        path = self.output(*args, **kwargs)
        self.go(path)

    def path_repr(self):
        if self.line is None:
            return self.path
        else:
            return f"{self.path} line {self.line}"


class ShowIfGitMixin:
    def show(self):
        return self.app.git


class ShowIfFileMixin:
    def show(self):
        return os.path.isfile(self.app.path)


class ShowIfDirMixin:
    def show(self):
        return True
        # return os.path.isdir(self.app.path)


class Verb:
    def __init__(self, app):
        self.app = app

    def show(self):
        return True

    @property
    def help(self):
        return getattr(self, "help", self.__class__.__name__)


class CommandVerb(Verb):
    anykey = False

    @property
    def help(self):
        return f"Run `{self.command}`"

    def __call__(self):
        path = shlex.quote(self.app.path)
        dir = shlex.quote(self.app.dir)
        line = shlex.quote(self.app.line or "0")
        self.app.run(
            self.command.format(path=path, line=line, dir=dir),
            shell=True,
            anykey=self.anykey,
        )


class ParentDirVerb(ShowIfDirMixin, Verb):
    help = "Go up"
    map = "u"

    def __call__(self):
        if self.app.line:
            self.app.go(app.path)
        else:
            newpath = os.path.dirname(self.app.path)
            self.app.go(newpath)


class ListProjectsVerb(Verb):
    help = "Find projects"
    map = "P"

    def show(self):
        return not ShowIfGitMixin.show(self) and ShowIfDirMixin.show(self)

    def __call__(self):
        match = self.app.output(
            """find -name .git -maxdepth 4 2>/dev/null |
                    xargs realpath | xargs dirname | fzf""",
            shell=True,
        )
        self.app.go(match)


class ListByrdProjectsVerb(Verb):
    help = "Find byrd projects"
    map = "y"

    def __call__(self):
        app.go("~/byrd")
        pv = ListProjectsVerb(self.app)
        pv()


class BackVerb(Verb):
    help = "Go back"
    map = "b"

    def show(self):
        return self.app.hist

    def __call__(self):
        path, line = self.app.hist.pop(-1)
        self.app.go(path, line, savehist=False)


class QuitVerb(Verb):
    help = "Quit"
    map = "q"

    def __call__(self):
        sys.exit(0)


class CdHomeVerb(Verb):
    map = "h"
    help = "Go home"

    def show(self):
        return self.app.path != os.path.expanduser("~")

    def __call__(self):
        self.app.go("~")


class CdVimVerb(Verb):
    map = "v"

    @property
    def _vimcwd(self):
        return self.app.output("nvr --remote-expr 'getcwd()'", shell=True)

    help = "Go vim cwd"

    def __call__(self):
        self.app.go(self._vimcwd)


class CdGitRootVerb(Verb):
    help = "Go project root"
    map = "p"

    def show(self):
        return self.app.git and not self.app.path == self.app.git

    def __call__(self):
        self.app.go(self.app.git)


class RunLazygitVerb(ShowIfGitMixin, CommandVerb):
    map = "g"
    command = "lazygit"


class RunLessVerb(ShowIfFileMixin, CommandVerb):
    map = "x"
    command = "less -N +{line} {path}"
    help = "Pager"


class RunBashVerb(ShowIfDirMixin, CommandVerb):
    map = "s"
    command = "bash"
    # help = 'Open shell here'


class RunEditVerb(ShowIfFileMixin, CommandVerb):
    map = "e"
    command = "nvr +FloatermHide; nvr {path} +{line}"
    help = "Edit"


class RunBlackVerb(CommandVerb):
    map = "B"
    anykey = True

    def show(self):
        return ShowIfFileMixin.show(self) and self.app.path.endswith(".py")

    command = "black {path}"


class SetVimVerb(ShowIfDirMixin, CommandVerb):
    map = "V"
    command = "nvr -c 'cd {dir}'"
    help = "Set vim cwd"


class FilterVerb(Verb):

    fill_query = True

    fzf = {}

    def parse(self, stri):
        return stri

    def __call__(self):
        fzf = ["fzf"]
        fzf_opts = self.fzf.copy()

        if self.fill_query and self.app.query:
            fzf_opts["query"] = self.app.query

        for key, val in fzf_opts.items():
            key = key.replace("_", "-")
            if val is True:
                fzf.append(f"--{key}")
            else:
                fzf.append(f"--{key}={val}")

        fzf_cmd = shlex.join(fzf)
        cmd = f"{self.files_command} | {self.command} | {fzf_cmd}"
        out = self.app.output(cmd, shell=True)
        self.handle(out)

    def handle(self, match):
        self.app.go(match)

    command = "xargs -L1"

    @property
    def files_command(self):
        if self.app.dir != self.app.path:
            return "echo {}".format(shlex.quote(self.app.path))

        if self.app.git == self.app.dir:
            return "git ls-files"

        if self.app.path == self.app.dir:
            return "find . -type f"


class FindLines(FilterVerb):
    help = "Filter lines"
    map = "l"
    fzf = dict(
        tac=True,
        exact=True,
        no_extended=True,
        delimiter=":",
        nth="3..",
        no_sort=True,
        preview="cat {1} --number | tail --lines=+{2}",
        preview_window="bottom:10",
    )

    command = "xargs -L1 grep --line-number --with-filename ."

    def handle(self, match):
        file, line, _ = match.split(":", 2)
        self.app.go(file, line)


class FilterFilesVerb(FilterVerb):
    fill_query = False
    help = "Filter files"
    map = "f"
    fzf = dict(preview="cat -n {}")


class FilterDirsVerb(ShowIfDirMixin, FilterVerb):
    fill_query = False
    help = "ls"
    map = "d"
    fzf = dict(ansi=True)
    files_command = "ls --color=always"


class FilterTagsVerb(FilterVerb, ShowIfGitMixin):
    map = "t"
    help = "Filter tags"
    fzf = dict(
        exact=True,
        delimiter="\t",
        with_nth=1,
        nth=1,
        preview='a={3}; printf {2}"\n"; cat -n {2} | tail --quiet -n +${a::-2}',
        preview_window="right:70%",
    )

    command = "xargs ctags --excmd=number -f - "

    def handle(self, match):
        i = match.split("\t")
        file = i[1]
        line = i[2]
        self.app.go(file, line.strip(';"'))


if __name__ == "__main__":
    app = App()
    try:
        file, line, query = sys.argv[1:]
        try:
            app.go(file, line)
        except FileNotFoundError:
            app.go("~")
            cwd = app.output("nvr --remote-expr 'getcwd()'", shell=True)
            app.go(cwd)
        app.query = query
    except ValueError:
        app.go("~")
    app.main()
