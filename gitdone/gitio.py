"""Every call out of the engine: git on a named repository, `gh` for pull requests, `glab` for GitLab merge requests."""
import json
import os
import shutil
import subprocess

# What `git rev-parse --local-env-vars` lists. A git hook inherits these from the commit that runs it,
# and left in place they would point every `git -C other-repo` back at the committing repository.
LOCAL_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
    "GIT_DIR", "GIT_GRAFT_FILE", "GIT_IMPLICIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS",
    "GIT_OBJECT_DIRECTORY", "GIT_PREFIX", "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE", "GIT_WORK_TREE",
)
PR_LIMIT = 1000
PR_FIELDS = "number,state,baseRefName,title,mergedAt,mergeCommit,url"
GH_TIMEOUT = 20


class Done:
    def __init__(self, code, out, err, partial=""):
        self.code = code
        self.out = out
        self.err = err
        self.partial = partial  # what a process out of time had said by then


# A plan names the repository, and a plan can come from a clone. A bare repository committed inside a project brings its own
# config, which can name a command, so git must refuse to discover one. `-c` outranks anything that config says.
SAFE_CONFIG = ("-c", "safe.bareRepository=explicit", "-c", "protocol.ext.allow=never", "-c", "core.fsmonitor=false",
               "-c", "core.quotePath=false", "-c", "log.date=iso", "-c", "i18n.logOutputEncoding=UTF-8", "-c", "log.showSignature=false",
               "-c", "diff.relative=false")


def clean_env():
    env = {k: v for k, v in os.environ.items() if k not in LOCAL_VARS}
    env["GIT_OPTIONAL_LOCKS"] = "0"  # a command that only reads must not rewrite .git/index
    env["GIT_NO_REPLACE_OBJECTS"] = "1"  # `git replace` must not rewrite what a commit's history says
    return env


def _run(args, cwd=None, env=None, timeout=30, stdin_text=None):
    try:
        done = subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL if stdin_text is None else None,
                              input=stdin_text, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        return Done(127, "", f"{args[0]} is not installed")
    except subprocess.TimeoutExpired as err:
        said = err.stdout or ""  # bytes on most systems, whatever the process was asked for
        return Done(124, "", f"{args[0]} did not answer in {timeout}s", partial=said.decode("utf-8", "replace") if isinstance(said, bytes) else said)
    except OSError as err:
        return Done(126, "", str(err))
    return Done(done.returncode, done.stdout, done.stderr)


MOST_BYTES_OF_HISTORY = 64 * 1024 * 1024  # of a table's old versions, read for a signal: about eight hundred versions of a table of a thousand rows


def git(repo, *args, stdin_text=None, timeout=30):
    """git in a named repository, whatever repository the caller happens to be inside."""
    return _run(["git", *SAFE_CONFIG, "-C", str(repo), *args], env=clean_env(), stdin_text=stdin_text, timeout=timeout)


def objects(repo, specs):
    """(name, bytes) of each of these `commit:path` objects, in order, with None for one that is missing. None in place of the list if git cannot say."""
    if not specs:
        return []
    done = git(repo, "cat-file", "--batch-check=%(objectname) %(objectsize)", stdin_text="\n".join(specs) + "\n", timeout=60)
    lines = done.out.splitlines() if not done.code else []
    if len(lines) != len(specs):
        return None
    fields = [line.split() for line in lines]
    return [(said[0], int(said[1])) if len(said) == 2 and said[1].isdigit() else None for said in fields]


def fitting(repo, specs, most_bytes):
    """How many of these `commit:path` objects, from the first, fit in a number of bytes. What a history holds is not what its pack weighs, so a stranger's few bytes can be a lot of text.
    If git cannot say, whoever reads the text next will find out and say so.
    """
    total, count, found_all = 0, 0, objects(repo, specs)
    if found_all is None:
        return len(specs)
    for found in found_all:
        total += found[1] if found else 0
        if total > most_bytes:
            break
        count += 1
    return count


def blobs(repo, specs, failed=None):
    """The text of many `commit:path` objects from one process, in order. None for one that is missing. `failed` is called if git could not answer."""
    if not specs:
        return []
    try:
        done = subprocess.run(["git", *SAFE_CONFIG, "-C", str(repo), "cat-file", "--batch"], input="\n".join(specs).encode("utf-8") + b"\n",
                              capture_output=True, env=clean_env(), timeout=120)
        if done.returncode and failed:
            failed(done.stderr.decode("utf-8", "replace"))
    except (OSError, subprocess.TimeoutExpired) as err:
        if failed:
            failed(str(err))
        return [None] * len(specs)
    out, at = [], 0
    data = done.stdout
    for _ in specs:
        end = data.find(b"\n", at)
        if end < 0:
            out.append(None)
            continue
        parts = data[at:end].split(b" ")
        at = end + 1
        if parts[-1] == b"missing" or len(parts) < 3:
            out.append(None)
            continue
        size = int(parts[-1])
        out.append(data[at:at + size].decode("utf-8", "replace"))
        at += size + 1
    return out


def git_here(*args):
    """git as the calling hook sees it: its repository, its index, its environment."""
    return _run(["git", *SAFE_CONFIG, *args])


def staged_bytes(path):
    """(exit code, the bytes the index holds for a path), for a hook: a real replacement character in a file must stay readable as itself."""
    try:
        done = subprocess.run(["git", *SAFE_CONFIG, "show", ":" + path], capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return 124, b""
    return done.returncode, done.stdout


def branch_refs(repo, name):
    """A branch's refs in a repository: the local one, and any remote's."""
    done = git(repo, "for-each-ref", "--format=%(refname)", f"refs/heads/{name}", f"refs/remotes/*/{name}")
    found = []
    for ref in done.out.split():
        # for-each-ref also matches below a pattern, and its * crosses slashes: keep only this exact branch.
        if ref == f"refs/heads/{name}" or (ref.startswith("refs/remotes/") and ref.split("/", 3)[3:] == [name]):
            found.append(ref)
    return found


def gh_status():
    """None when `gh` can answer for this machine, or words saying why not."""
    if shutil.which("gh") is None:
        return "gh is not installed"
    env = clean_env()
    env["GH_PROMPT_DISABLED"] = "1"
    done = _run(["gh", "auth", "status"], env=env, timeout=GH_TIMEOUT)
    return None if done.code == 0 else "gh is not logged in"


def issues(directory, label=None):
    """The repository's issues as a list, newest fields first; or a string saying why not."""
    if shutil.which("gh") is None:
        return "gh is not installed"
    env = clean_env()
    env["GH_PROMPT_DISABLED"] = "1"
    base = ["gh", "issue", "list", "--state", "all", "--limit", "1000"]
    if label:
        base += ["--label", label]
    # Older versions of gh do not know the last field.
    for fields in ("number,title,state,stateReason,milestone,closedByPullRequestsReferences", "number,title,state,stateReason,milestone"):
        done = _run([*base, "--json", fields], cwd=str(directory), env=env, timeout=GH_TIMEOUT)
        if done.code == 0:
            break
    if done.code:
        first = (done.err.strip().splitlines() or ["no output"])[0]
        return f"gh could not answer: {first}"
    try:
        return json.loads(done.out)
    except ValueError:
        return "gh gave an answer the engine cannot read"


def pull_requests(repo):
    """{number: {state, baseRefName}} for the repository's remote; or a string saying why not."""
    if shutil.which("gh") is None:
        return "gh is not installed"
    env = clean_env()
    env["GH_PROMPT_DISABLED"] = "1"
    done = _run(["gh", "pr", "list", "--state", "all", "--limit", str(PR_LIMIT), "--json", PR_FIELDS],
                cwd=str(repo), env=env, timeout=GH_TIMEOUT)
    if done.code:
        first = (done.err.strip().splitlines() or ["no output"])[0]
        return f"gh could not answer: {first}"
    try:
        items = json.loads(done.out)
        return {int(p["number"]): p for p in items}
    except (ValueError, KeyError, TypeError):
        return "gh gave an answer the engine cannot read"


def pull_request(repo, number):
    """One pull request by number, for a repository with more than `pull_requests` reads. A dict, or None."""
    if shutil.which("gh") is None:
        return None
    env = clean_env()
    env["GH_PROMPT_DISABLED"] = "1"
    done = _run(["gh", "pr", "view", str(number), "--json", PR_FIELDS], cwd=str(repo), env=env, timeout=GH_TIMEOUT)
    if done.code:
        return None
    try:
        found = json.loads(done.out)
    except ValueError:
        return None
    return found if isinstance(found, dict) and "number" in found else None


def merge_request(repo, number):
    """A GitLab merge request through `glab`: a dict, or a string saying why not."""
    if shutil.which("glab") is None:
        return "glab is not installed"
    env = clean_env()
    env["NO_PROMPT"] = "1"
    done = _run(["glab", "mr", "view", str(number), "-F", "json"], cwd=str(repo), env=env, timeout=GH_TIMEOUT)
    if done.code:
        first = (done.err.strip().splitlines() or ["no output"])[0]
        return f"glab could not answer: {first}"
    try:
        found = json.loads(done.out)
    except ValueError:
        return "glab gave an answer the engine cannot read"
    return found if isinstance(found, dict) else "glab gave an answer the engine cannot read"
