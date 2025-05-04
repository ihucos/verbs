import os
import subprocess
import sys
import curses
import shlex
from time import sleep
from curses import wrapper
from pathlib import Path
import json

CATEGORY_ORDER = [
    "file",
    "filter",
    "command",
    "go",
    "ai",
]


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


def nix(run):
    return shlex.join([
        "nix-shell",
        "--packages",
        "findutils",
        "universal-ctags",
        "--run",
        run,
    ])


class AppGUIMixin:
    arrow = 0
    query = None
    nothing_pressed_yet = True

    def _draw(self, stdscr, verbs):
        # Clear screen
        stdscr.clear()

        pad_top = 1
        pad_left = 1

        c = pad_top

        if self.query:
            query = f" - {self.query}"
        else:
            query = ""
        stdscr.addstr(c, 1, self.path_repr() + query)
        c += 1

        c += 1

        grouped_verbs = {}
        for verb in verbs:
            grouped_verbs.setdefault(verb.category, [])
            grouped_verbs[verb.category].append(verb)

        index = 0
        for category, verbs in sorted(
            grouped_verbs.items(), key=lambda i: CATEGORY_ORDER.index(i[0])
        ):
            stdscr.addstr(c, pad_left, category.upper())
            c += 1
            for verb in sorted(verbs, key=lambda i: i.help):
                if index == self.arrow:
                    a = "*"
                else:
                    a = " "
                stdscr.addstr(
                    c, pad_left, f"{a} [{verb.map}]  {verb.help.capitalize()}"
                )
                c += 1

                index += 1

            c += 1
            stdscr.addstr(c, pad_left, "")

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
            verbs.sort(key=lambda v: v.help)

            #
            # HACK: Enable a shortcut but hitting spaces two times
            #
            key = self.draw(verbs)
            if key == " " and self.nothing_pressed_yet:
                CdGitRootVerb(self)()
                self.nothing_pressed_yet = False
                continue
            self.nothing_pressed_yet = False

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
                    self.flicker()

    def main(self):
        try:
            self._main()
        except KeyboardInterrupt:
            print("^C", file=sys.stderr)
            self.close()

    def close(self):
        self.savehist()
        self.run("nvr +FloatClose", shell=True)


class App(AppGUIMixin):
    def __init__(self):
        self.maps = {}
        self.hist = []
        self.path = None
        self.dir = None

    def savehist(self):
        Path("~/.verbs_hist").expanduser().write_text(json.dumps(list((self.hist))))

    def loadhist(self):
        try:
            self.hist = json.loads(Path("~/.verbs_hist").expanduser().read_text())
        except FileNotFoundError:
            pass

    def go(self, path, line=None, savehist=True):
        self.line = line

        path = os.path.expanduser(path)

        if self.path and savehist and self.path != path:
            self.hist.append((self.path, self.line))

        if self.path and self.dir:
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
            self.run([
                "/bin/bash",
                "-c",
                "read -rsp $'Press any key to continue...\n' -n1 key",
            ])

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
        # return True
        return os.path.isdir(self.app.path)


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
    close = False
    category = "command"

    @property
    def help(self):
        return f"`{self.command}`"

    def __call__(self):
        path = shlex.quote(self.app.path)
        dir = shlex.quote(self.app.dir)
        if self.app.git:
            pdir = shlex.quote(os.path.basename(self.app.git))
        else:
            pdir = ""
        line = shlex.quote(self.app.line or "0")

        if self.app.git:
            relpath = shlex.quote(os.path.relpath(self.app.path, start=self.app.git))
        else:
            relpath = ""
        self.app.run(
            self.command.format(
                path=path, line=line, dir=dir, pdir=pdir, relpath=relpath
            ),
            shell=True,
            anykey=self.anykey,
        )
        if self.close:
            self.app.close()


class ParentDirVerb(Verb):
    help = "up"
    map = "u"
    category = "go"

    def show(self):
        return self.app.path != "/"

    def __call__(self):
        if self.app.line:
            self.app.go(self.app.path)
        else:
            newpath = os.path.dirname(self.app.path)
            self.app.go(newpath)


class BackVerb(Verb):
    map = "U"
    help = "back"
    category = "go"

    def show(self):
        return self.app.hist

    def __call__(self):
        path, line = self.app.hist.pop(-1)
        self.app.go(path, line, savehist=False)


class QuitVerb(Verb):
    help = "Quit"
    map = "q"
    category = "go"

    def __call__(self):
        self.app.close()


class CdHomeVerb(Verb):
    map = "h"
    help = "home"
    category = "go"

    def show(self):
        return self.app.path != os.path.expanduser("~")

    def __call__(self):
        self.app.go("~")


class CdVimVerb(Verb):
    map = "v"
    category = "go"

    @property
    def _vimcwd(self):
        return self.app.output("nvr --remote-expr 'getcwd()'", shell=True)

    help = "vim cwd"

    def __call__(self):
        self.app.go(self._vimcwd)


class CdGitRootVerb(Verb):
    help = "project root"
    map = "p"
    category = "go"

    def show(self):
        return self.app.git and not self.app.path == self.app.git

    def __call__(self):
        self.app.go(self.app.git)


class RunLazygitVerb(ShowIfGitMixin, CommandVerb):
    map = "g"
    command = "lazygit"


class RunLessVerb(ShowIfFileMixin, CommandVerb):
    map = "o"
    command = "less -N +{line} {path}"
    help = "Pager"


class RunSCommit(CommandVerb):
    map = "c"
    command = "lazygit status && s-commit && git push"
    help = "Commit staged changes with AI and push"
    category = "ai"
    anykey = True


class RunBashVerb(ShowIfDirMixin, CommandVerb):
    map = "s"
    command = "bash"
    # help = 'Open shell here'


class RunEditVerb(ShowIfFileMixin, CommandVerb):
    map = " "
    command = "nvr +'wincmd p | e {path} | {line}'"
    help = "Edit"
    close = True
    category = "file"


# class RunBlackVerb(CommandVerb):
#     map = "B"
#     anykey = True

#     def show(self):
#         return ShowIfFileMixin.show(self) and self.app.path.endswith(".py")

#     command = "black {path}"


class SetVimVerb(ShowIfDirMixin, CommandVerb):
    map = "V"
    command = "nvr -c 'cd {dir}'"
    help = "Set vim cwd"


class RunLastCommandVerb(CommandVerb):
    map = "x"
    anykey = True

    @property
    def command(self):
        return self.app.output(
            "cat ~/.bash_eternal_history  | tail -n 1", shell=True
        ).strip()

    @property
    def help(self):
        return f"Last (`{self.command}`)"


class FilterVerb(Verb):
    fill_query = True
    space_return = True
    cwd = None
    category = "filter"

    fzf = {}

    def parse(self, stri):
        return stri

    def __call__(self):
        fzf = ["fzf"]
        fzf_opts = self.fzf.copy()

        if self.space_return:
            fzf_opts.update({"expect": " "})

        if self.fill_query and self.app.query:
            fzf_opts["query"] = self.app.query

        for key, val in fzf_opts.items():
            key = key.replace("_", "-")
            if val is True:
                fzf.append(f"--{key}")
            else:
                fzf.append(f"--{key}={val}")

        fzf_cmd = shlex.join(fzf)
        if self.command:
            cmd = f"{self.files_command} | {self.command} | {fzf_cmd}"
        else:
            cmd = f"{self.files_command} | {fzf_cmd}"

        if self.cwd is None:
            out = self.app.output(cmd, shell=True)
        else:
            out = self.app.output(cmd, shell=True, cwd=self.cwd)
        self._handle(out)

    def _handle(self, match):
        select = match.split("\n")[-1]
        self.handle(select)

    def handle(self, match):
        self.app.go(match)

    command = None

    @property
    def files_command(self):
        if self.app.dir != self.app.path:
            return "echo {}".format(shlex.quote(self.app.path))

        if self.app.git == self.app.dir:
            return "git ls-files"

        if self.app.path == self.app.dir:
            return nix("find . -type f 2>/dev/null")


def cmd(c, *mixins):
    """
    Helper for CommandsVerb
    """

    class Tmp(*mixins, CommandVerb):
        command = c

    return Tmp


class ListProjectsVerb(FilterVerb):
    help = "Find projects"
    map = "P"
    command = nix(
        "find -name .git -maxdepth 4 2>/dev/null | xargs realpath | xargs dirname"
    )
    fill_query = False

    def show(self):
        return not ShowIfGitMixin.show(self) and ShowIfDirMixin.show(self)


class FindLines(FilterVerb):
    space_return = False
    help = "lines"
    map = "/"
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

    command = "xargs -L1 grep --line-number --with-filename . 2> /dev/null"

    def handle(self, match):
        file, line, _ = match.split(":", 2)
        self.app.go(file, line)


class FilterFilesVerb(FilterVerb):
    fill_query = False
    help = "files"
    map = " "
    fzf = dict(preview="cat -n {}")


# class FilterDirsVerb(ShowIfDirMixin, FilterVerb):
#     fill_query = False
#     help = "ls"
#     map = "l"
#     fzf = dict(ansi=True)
#     files_command = "ls --color=always -a"


class FilterVimBufferVerb(FilterVerb):
    fill_query = False
    help = "vim buffers"
    map = "b"
    fzf = dict(ansi=True)
    command = "grep -v '^term://'"
    files_command = "nvr --remote-expr {}".format(
        shlex.quote(
            """join(filter(map(range(1,bufnr('$')), 'bufname(v:val)'), 'buflisted(v:val)'), '\n')"""
        )
    )

    def handle(self, match):
        vimcur = self.app.output("nvr --remote-expr 'getcwd()'", shell=True)
        real = os.path.join(vimcur, match)
        self.app.go(real)


class FilterTagsVerb(FilterVerb):
    map = "t"
    help = "tags"
    fzf = dict(
        exact=True,
        delimiter="\t",
        with_nth=1,
        nth=1,
        preview='line="$(printf {3} | rev | cut -c3- | rev)"; printf {2}"\n"; cat -n {2} | tail --quiet -n +"$line"',
        preview_window="right:70%",
    )

    command = nix("xargs ctags --excmd=number -f - ")

    def handle(self, match):
        i = match.split("\t")
        file = i[1]
        line = i[2]
        self.app.query = i[0]
        self.app.go(file, line.strip(';"'))


class FilterRecentVerb(FilterVerb, ShowIfGitMixin):
    fill_query = False
    map = "r"
    help = "changed files"
    command = "sort | uniq"
    fzf = dict(preview="git diff main {}")
    files_command = """ {
		git diff --name-only $(git merge-base --fork-point main)..HEAD .
		git status -s --porcelain | xargs -L1 | cut -d' ' -f2
	}"""

    @property
    def cwd(self):
        return self.app.git

    def handle(self, match):
        self.app.go(os.path.join(self.app.git, match))


def main():
    app = App()
    app.loadhist()
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


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        try:
            input(">")
        except Exception:
            pass
