"""What a row's words claim, and what git and the forge say about the claim.

A claim is verified; unverified (nothing can answer right now: offline, or `gh` not there); unproven (nothing here could ever
settle it, or it holds in name only: no repository, no remote, merged into another branch, a commit that changes nothing, a commit
only on a local branch); absent (a commit the local clone does not have, when a remote might); or contradicted (proven wrong).

`--strict` asks that every claim be verified. The default mode fails only a row with nothing left but contradictions.
"""
import collections
import os
import re

from . import gitio
from .discover import POINTER
from .plan import PlanError

Claim = collections.namedtuple("Claim", "kind value")
# unanswerable: nothing here could ever ask, with no repository or no remote. Only such a claim is something a person may vouch for.
Result = collections.namedtuple("Result", "state detail unanswerable", defaults=(False,))

VERIFIED, UNVERIFIED, UNPROVEN, ABSENT, CONTRADICTED = "verified", "unverified", "unproven", "absent", "contradicted"

# 64 digits is a SHA-256 repository's id. 18 digits is the most a number here can have: past 4,300 Python's own answer depends on its version.
QUOTED_SHA = re.compile(r"`([0-9a-f]{7,64})`")
BARE_SHA = re.compile(r"(?<![\w/.-])([0-9a-f]{7,64})(?![\w/-])")
HEX_ID = re.compile(r"^[0-9a-f]{7,64}$")
COMMIT_URL = re.compile(r"/commits?/([0-9a-f]{7,64})\b")
PR_WORDS = re.compile(r"(?i)\b(?:PR|pull request)\s{0,4}#?\s{0,4}([0-9]{1,18})\b|\bpull/([0-9]{1,18})\b")
PR_LIST = re.compile(r"(?i)\bPRs\s{0,4}#?\s{0,4}([0-9]{1,18}(?:\s{0,4}(?:,|&|\+|and|or)\s{0,4}#?\s{0,4}[0-9]{1,18})*)(?![0-9])")
MR_WORDS = re.compile(r"\bMRs?\s{0,4}!?\s{0,4}([0-9]{1,18})\b|(?i:\bmerge request\s{0,4}!?\s{0,4}([0-9]{1,18})\b)|\bmerge_requests/([0-9]{1,18})\b")
TAG_WORDS = re.compile(r"(?i)\btag\s+`([\w][\w./+-]*)`|\btag\s+(v?\d[\w.+-]*)|\brelease\s+`?(v?\d+(?:\.\d+)+[\w.+-]*)`?")
# `git revert --reference` writes the id with its subject and date in parentheses, and a revert of a merge breaks its line after "reversing".
REVERT_COMMIT = re.compile(r"^[ \t]*This reverts commit ([0-9a-f]{7,64})(?: \([^\n]*?\))?"
                           r"(?:,\s+reversing\s+changes\s+made\s+to\s+([0-9a-f]{7,64})(?: \([^\n]*?\))?)?\.?[ \t]*$", re.M)
REVERT_PR = re.compile(r"^[ \t]*Reverts ([\w.-]+/[\w.-]+)?#([0-9]{1,18})[ \t]*$", re.M)
REVERT_MR = re.compile(r"^[ \t]*This reverts merge request ([\w./-]+)?!([0-9]{1,18})\.?[ \t]*$", re.M)
REVERT_SUBJECT = re.compile(r'^(Revert|Reapply) "(.+)"')
LANDED_SQUASH = re.compile(r"\(#([0-9]{1,18})\)$")
LANDED_MERGE = re.compile(r"^Merge pull request #([0-9]{1,18}) ")
LANDED_MR = re.compile(r"^See merge request \S*!([0-9]{1,18})$", re.M)
# A link into a repository's pull requests, commits or issues: with a scheme, from `//`, with a dotted host or a port, or a bare `owner/name/pull/12`.
LINK = re.compile(r"(?i)(?:(?:\bhttps?:)?//([^\s/]{1,200})/|(?<![\w./@:%~+-])(?:((?:[\w-]{1,63}\.){1,10}[a-z]{2,24}(?::[0-9]{1,5})?|[\w-]{1,63}:[0-9]{1,5})/)?)"
                  r"([\w.~%+/-]{1,300}?)/(?:-/)?(?:pulls?|pull-requests|pullrequest|commits?|merge[_-]requests|issues)/([0-9a-z]{1,64})[^\s)\]>|]{0,300}")
ABSOLUTE = re.compile(r"(?i)^(?:[a-z][a-z0-9+.-]*:|//|(?:[\w-]{1,63}\.){1,10}[a-z]{2,24}(?::[0-9]{1,5})?/|[\w-]{1,63}:[0-9]{1,5}/)")
URL_PARTS = re.compile(r"(?i)^(?:[a-z][a-z0-9+.-]*:)?(?://)?([^\s/]{1,200})/([^\s?#]*)")
FORGE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org")
REPOSITORY_PAGE = re.compile(r"(?i)^[^/]+/[^/]+/(?:-/)?(?:releases?|tags?|tree|blob|compare|actions)(?:/|$)")
MARKDOWN_LINK = re.compile(r"\[(?:[^\[\]\n]|\[[^\[\]\n]{0,300}\]){0,300}\]\(\s{0,8}<?([^)\s>]{1,600})>?(?:\s[^)\n]{0,300})?\)")
HTML_LINK = re.compile(r"""(?is)<a\s[^>]{0,300}href=["']?([^"'\s>]{1,600})[^>]{0,300}>.{0,300}?</a>""")
# https://host/owner/name.git, ssh://git@host:22/owner/name, git@host:owner/name.git, host:owner/name. A local path names no host.
REMOTE_URL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/\s]+@)?([^/\s]+)/|(?:[^@/\s]+@)?([\w.-]+):(?!/))(\S+?)(?:\.git)?/?$")
SLOW = 120  # seconds: reading a long history is worth waiting for, and an honest "could not read" comes after that
SAFE_REF = re.compile(r"^[\w][\w./+-]*$")
NOTE_BRANCH = re.compile(r"(?i)\bbranch\s+`([^`\s]+)`")
PARENTHESIS = re.compile(r"\(([^)]{0,500})\)")
ITEM_SPLIT = re.compile(r" ?[,+&] ?| (?:and|or) ")
RECORD = "\0\0"
OFFICIAL_REMOTES = ("origin", "upstream")  # with one of these, any other remote's branch is somebody else's, however it is named


def _bare_shas(text):
    """A bare token needs a digit and a letter, so numbers and English stay out of it."""
    found = []
    seen = set()
    for token in BARE_SHA.findall(text):
        if token not in seen and re.search(r"\d", token) and re.search(r"[a-f]", token):
            seen.add(token)
            found.append(token)
    return found


def _quoted_shas(text):
    return QUOTED_SHA.findall(text) + COMMIT_URL.findall(text)


def find_shas(text):
    """Commit ids in the words."""
    quoted = _quoted_shas(text)
    return quoted + [s for s in _bare_shas(text) if s not in quoted]


def find_prs(text):
    found = []
    for groups in PR_WORDS.findall(text):
        number = int(next(g for g in groups if g))
        if number not in found:
            found.append(number)
    for words in PR_LIST.findall(text):
        for digits in re.findall(r"\d+", words):
            if int(digits) not in found:
                found.append(int(digits))
    return found


def find_mrs(text):
    found = []
    for groups in MR_WORDS.findall(text):
        number = int(next(g for g in groups if g))
        if number not in found:
            found.append(number)
    return found


def find_tags(text):
    found = []
    for groups in TAG_WORDS.findall(text):
        tag = next(g for g in groups if g).rstrip(".")
        if tag not in found:
            found.append(tag)
    return found


def _bare_host(host):
    """A host as a link and a remote can both say it."""
    host = host.lower().rpartition("@")[2].partition(":")[0]
    for prefix in ("www.", "ssh."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def own_repositories(plan):
    """(host, path) of the plan's repository, in lower case, from its remotes. With origin or upstream there, any other remote is somebody else's:
    a vendor kept as a remote is not this repository. A local path has neither.
    """
    if getattr(plan, "_own_repositories", None) is None:
        found = set()
        if plan.repo is not None:
            lines = [line.split() for line in gitio.git(plan.repo, "remote", "-v").out.split("\n") if len(line.split()) > 1]
            official = [words for words in lines if words[0] in OFFICIAL_REMOTES]
            for words in official or lines:
                match = REMOTE_URL.match(words[1])
                if match:
                    found.add((_bare_host(match.group(1) or match.group(2)), match.group(3).lower()))
        plan._own_repositories = found
    return plan._own_repositories


def is_own(plan, path):
    """Whether a path like `owner/name` is one of the plan's repository's remotes, whatever its host."""
    return path.lower().strip("/") in {own_path for _, own_path in own_repositories(plan)}


def _on_our_host(host, own_host):
    """A remote's host without a dot is a name from someone's ssh config, so it says nothing about the link's."""
    return own_host == _bare_host(host) or "." not in own_host


def _link_is_own(plan, match):
    if not (match.group(1) or match.group(2)):
        return is_own(plan, match.group(3)) or not match.group(3).strip("./")  # ../../pull/12 stays in this repository
    path = match.group(3).lower()
    return any(own_path == path and _on_our_host(match.group(1) or match.group(2), own_host) for own_host, own_path in own_repositories(plan))


def _foreign(plan, url, foreign_ids):
    """Whether a link's target is another repository. A link to a project's own site, a CI run or a ticket is not, and a relative link stays here."""
    match = LINK.match(url)
    if match:
        if _link_is_own(plan, match):
            return False
        foreign_ids.add(match.group(4).lower())
        return True
    if not ABSOLUTE.match(url):
        return False
    parts = URL_PARTS.match(url)
    if not parts or any(_on_our_host(parts.group(1), own_host) and (parts.group(2).lower() + "/").startswith(own_path + "/")
                        for own_host, own_path in own_repositories(plan)):
        return False
    return _bare_host(parts.group(1)) in FORGE_HOSTS or bool(REPOSITORY_PAGE.match(parts.group(2)))


def _without_other_repositories(plan, text):
    """(the words, the ids that belong to another repository). A link to another repository's pull request or commit says nothing about this
    one, whatever its number. A link's words go with it, so `[PR #12](https://github.com/vendor/lib/pull/12)` is no claim here, and neither are the
    words beside one naming the same number. With no remote to compare with, no link can be called ours.
    """
    foreign_ids, own_ids = set(), set()
    if "/" not in text:
        return text, foreign_ids
    for links in (MARKDOWN_LINK, HTML_LINK):
        text = links.sub(lambda m: " " if _foreign(plan, m.group(1), foreign_ids) else m.group(0), text)

    def keep_own(match):
        if _link_is_own(plan, match):
            own_ids.add(match.group(4).lower())
            return match.group(0)
        foreign_ids.add(match.group(4).lower())
        return " "
    return LINK.sub(keep_own, text), foreign_ids - own_ids


def _reads_long_ids(plan):
    """Whether this repository's ids are SHA-256. Elsewhere, 64 hex digits are a checksum, and no commit could have that id."""
    if getattr(plan, "_long_ids", None) is None:
        plan._long_ids = plan.repo is not None and gitio.git(plan.repo, "rev-parse", "--show-object-format").out.strip() == "sha256"
    return plan._long_ids


def release_claims(plan, text):
    """What the words name as a release: commits, pull requests, merge requests, tags, and what the plan's own pattern finds.

    A commit id in backticks or a URL is a claim. A bare word that only looks like one is `bare`: it stands as a claim when it is
    all a row names, and beside a claim that holds, it is probably a word.
    """
    text, foreign_ids = _without_other_repositories(plan, text)

    def ours(sha):
        # An issue number under ten is no commit's prefix: only an id long enough to be one can be the same commit.
        return not any(len(other) >= 7 and (sha.startswith(other) or other.startswith(sha)) for other in foreign_ids) and (len(sha) <= 40 or _reads_long_ids(plan))
    quoted = [s for s in _quoted_shas(text) if ours(s)]
    claims = [Claim("sha", s) for s in quoted] + [Claim("bare", s) for s in _bare_shas(text) if s not in quoted and ours(s)]
    claims += [Claim("pr", n) for n in find_prs(text) if str(n) not in foreign_ids]
    claims += [Claim("mr", n) for n in find_mrs(text) if str(n) not in foreign_ids] + [Claim("tag", t) for t in find_tags(text)]
    if plan.evidence_pattern:
        try:
            pattern = re.compile(plan.evidence_pattern)
        except re.error as err:
            raise PlanError(f"evidence_pattern is not a regular expression: {err}")
        for match in pattern.finditer(text):
            ref = match.groupdict().get("ref")
            claims.append(Claim("ref", ref) if ref else Claim("named", match.group(0)))
    return claims


def branch_names(plan, row):
    """The branches a row names: ``branch `x` `` in its note, or else its status cell's parenthesis, through the aliases."""
    named = NOTE_BRANCH.findall(row.note)
    if named:
        return named
    inside = PARENTHESIS.search(row.status)
    names = []
    if inside:
        for item in ITEM_SPLIT.split(" ".join(inside.group(1).split())):
            item = item.strip().strip("`")
            if item:
                names.append(plan.branch_aliases.get(item, item))
    return names


class Verifier:
    def __init__(self, plan, offline=False):
        self.plan = plan
        self.repo = plan.repo
        self.no_repo = "the plan names no repo"
        if plan.data.get("repo") == "." and gitio.git(plan.repo, "rev-parse", "--git-dir").code:
            self.repo = None  # `init` wrote this before `git init` ran; evidence starts working the moment it does
            self.no_repo = "this folder is not a git repository yet"
        self.branch = plan.default_branch
        self.offline = offline
        self._tips = None
        self._prs = None
        self._reverts = None
        self._remote_names = None
        self._unpushed = None      # the remote that should hold the default branch, when it has none here
        self._refs = None          # every branch's refs, read once
        self._resolved = {}        # a reference's words -> its full commit id, or None
        self._not_on_default = None
        self._checked = set()      # the commits a bulk read covered
        self._changes = {}         # commit -> (its parents, the files it changes)
        self._subjects = None      # every commit by its subject, for a revert that names one in words
        self._merge_requests = None
        self._first_parents = {}   # tip -> its first-parent line, newest first
        self._parents = None       # commit -> its parents, for everything on the default branch
        self._children = None      # the same, the other way round
        self._lost_at = {}         # commit -> the merge that took none of its changes, or None; present once settled
        self._every_revert = set()
        self._ignores_case = False
        self._tracker = None

    # ------------------------------------------------------------------ the repository

    def problem(self):
        """Why the plan's repo cannot be used at all, or None."""
        if self.repo is None:
            return None
        place = gitio.git(self.repo, "rev-parse", "--git-dir", "--is-shallow-repository")
        if place.code:
            return f"the plan's repo {self.repo} is not a git repository"
        if place.out.split()[-1:] == ["true"]:
            return (f"the plan's repo {self.repo} is a shallow clone, so a commit or a revert could be missed; "
                    "fetch its whole history (actions/checkout: fetch-depth: 0)")
        if not self.tips() and not self._unborn():
            return f"the plan's repo {self.repo} has no branch {self.branch}; set default_branch in the plan if that is wrong"
        return None

    def _unborn(self):
        """A repository with no commit yet, on the default branch: its first commit must be able to add the tracker."""
        return (gitio.git(self.repo, "symbolic-ref", "--short", "HEAD").out.strip() == self.branch
                and gitio.git(self.repo, "rev-parse", "--verify", "--quiet", "HEAD").code != 0)

    def tips(self):
        """What the default branch is: the remote's, when there is one, since a commit only here has not shipped. With a remote that has
        no such branch here, it is the local one, and `_unpushed` says so: nothing has been pushed, so nothing has shipped.
        """
        if self._tips is None:
            remotes = self._remotes()
            home = self._home_remotes(remotes)
            local = f"refs/heads/{self.branch}"
            wanted = [f"refs/remotes/{r}/{self.branch}" for r in home]
            done = gitio.git(self.repo, "for-each-ref", "--format=%(refname)", local, *wanted)
            if done.code:
                self._stop(done, f"where {self.branch} is")
            found = done.out.split()
            official = [ref for ref in wanted if ref in found]
            self._tips = official or ([local] if local in found else [])
            self._every_tip = official + ([local] if local in found else [])
            if home and not official:
                self._unpushed = f"{home[0]}/{self.branch} does not exist here; push it, or fetch"
            elif remotes and not home:
                self._unpushed = f"nothing says which of {', '.join(remotes)} holds it; set one with `git branch --set-upstream-to`"
        return self._tips

    def _home_remotes(self, remotes):
        """The remotes the default branch answers to: origin and upstream, or the only remote there is, or the one git tracks it on."""
        official = [r for r in OFFICIAL_REMOTES if r in remotes]
        if official or len(remotes) < 2:
            return official or remotes
        for key in (f"branch.{self.branch}.remote", "remote.pushDefault"):
            said = gitio.git(self.repo, "config", "--get", key).out.strip()
            if said in remotes:
                return [said]
        return []

    def _remotes(self):
        if self._remote_names is None:
            done = gitio.git(self.repo, "remote")
            if done.code:
                self._stop(done, "which remotes there are")
            self._remote_names = done.out.split()
        return self._remote_names

    def _has_remote(self):
        return bool(self._remotes())

    def _stop(self, done, what):
        """git failing is not an answer: it must never read as proof, either way. Exit 2, could not run."""
        raise PlanError(f"git could not answer {what} in {self.repo.name}: {(done.err.strip().splitlines() or ['no output'])[0]}")

    def _is_ancestor(self, commit, tip):
        done = gitio.git(self.repo, "merge-base", "--is-ancestor", commit, tip, timeout=SLOW)
        if done.code not in (0, 1):
            self._stop(done, f"whether {commit[:7]} is on {self.branch}")
        return done.code == 0

    def _on_default(self, commit):
        if commit in self._checked:
            return commit not in self._not_on_default
        if self._parents is not None:  # the whole branch is already in hand
            return commit in self._parents
        return any(self._is_ancestor(commit, tip) for tip in self.tips())

    # ------------------------------------------------------------------ resolving

    def _resolve(self, ref):
        """A reference's full commit id, or None."""
        if ref not in self._resolved:
            done = gitio.git(self.repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
            if done.code not in (0, 1):
                self._stop(done, f"what {ref} is")
            self._resolved[ref] = done.out.strip() if done.code == 0 else None
        return self._resolved[ref]

    def _resolve_id(self, hex_id):
        """A commit id's full form. It resolves to objects, never to refs: a tag named like an id must not be taken for that
        commit. Two commits sharing a short id settle on the one on the default branch.
        """
        known = self._resolved.get(hex_id, False)
        if known is not False and (known is None or known.startswith(hex_id)):
            return known
        listed = gitio.git(self.repo, "rev-parse", f"--disambiguate={hex_id}")
        if listed.code:
            self._stop(listed, f"what {hex_id} is")
        candidates = listed.out.split()
        commits = []
        if candidates:
            kinds = gitio.git(self.repo, "cat-file", "--batch-check=%(objectname) %(objecttype)", stdin_text="\n".join(candidates) + "\n")
            if kinds.code:
                self._stop(kinds, f"what {hex_id} is")
            commits = [line.split()[0] for line in kinds.out.splitlines() if line.endswith(" commit")]
        if len(commits) > 1:
            on_default = [c for c in commits if self._on_default(c)]
            commits = on_default or commits
        self._resolved[hex_id] = commits[0] if commits else None
        return self._resolved[hex_id]

    def _batch_resolve(self, names):
        """Resolve many names in one process, with no ancestry question asked. A name left out is asked about on its own."""
        wanted = sorted({n for n in names if SAFE_REF.match(n) and n not in self._resolved})
        if not wanted:
            return
        done = gitio.git(self.repo, "cat-file", "--batch-check", stdin_text="".join(f"{n}^{{commit}}\n" for n in wanted))
        answers = done.out.splitlines()
        if done.code or len(answers) != len(wanted):
            return
        for name, answer in zip(wanted, answers):
            words = answer.split()
            if len(words) == 3 and words[1] == "commit":
                self._resolved[name] = words[0]
            elif words and words[-1] == "missing" and (not HEX_ID.match(name) or len(name) in (40, 64)):
                self._resolved[name] = None
            # A short id two commits share answers `missing` here too: left for `_resolve_id`, which can tell them apart.

    def preload(self, claims, branches=()):
        """Settle many claims in a few processes, so that a big table costs what a small one does. It only adds speed: a claim
        left out is asked about on its own, and an answer read here is the same answer.
        """
        if self.repo is None:
            return
        ids = [c.value for c in claims if c.kind in ("sha", "bare")]
        tags = [f"refs/tags/{c.value}" for c in claims if c.kind == "tag"]
        self._batch_resolve(ids + tags)
        commits = {self._resolved.get(name) for name in ids + tags}
        for branch in branches:
            for ref in self._branch_refs(branch):
                commits.add(self._branch_tip(ref))
        commits.discard(None)
        tips = self.tips()
        if not commits or not tips:
            return
        lines = "".join(f"{c}\n" for c in sorted(commits)) + "".join(f"^{t}\n" for t in tips)
        done = gitio.git(self.repo, "rev-list", "--stdin", stdin_text=lines, timeout=SLOW)
        if done.code == 0:
            self._not_on_default = (self._not_on_default or set()) | set(done.out.split())
            self._checked |= commits
        on_default = commits - (self._not_on_default or set())
        self._read_changes(on_default)
        sides = {self._changes[c][0][1] for c in on_default if len(self._changes.get(c, ([], []))[0]) > 1}  # what a cited merge brought in, read together
        self._read_changes(sides)
        self._settle_arrivals(on_default | sides)

    def _read_changes(self, commits):
        """What each commit changes, in one process."""
        wanted = [c for c in commits if c not in self._changes]
        if not wanted:
            return
        # A merge is held to what it changed against its first parent, and a merge that took nothing lists nothing. -z: git quotes an odd name otherwise.
        done = gitio.git(self.repo, "-c", "log.showroot=true", "log", "--no-walk", "--stdin", "-m", "--first-parent", "--no-renames", "-z",
                         "--format=%x01%x01%H %P%x01", "--name-only", stdin_text="\n".join(wanted) + "\n", timeout=SLOW)
        if done.code:
            self._stop(done, "what a commit changes")
        for entry in done.out.split("\x01\x01"):
            head, _, names = entry.partition("\x01")
            ids = head.split()
            if ids:
                self._changes[ids[0]] = (ids[1:], [name.strip("\n") for name in names.split("\0") if name.strip("\n")])

    def _all_refs(self):
        """{ref: commit} for every local and remote branch, read once."""
        if self._refs is None:
            done = gitio.git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/remotes")
            if done.code:
                self._stop(done, "which branches exist")
            self._refs = dict(line.split() for line in done.out.splitlines() if len(line.split()) == 2)
        return self._refs

    def _branch_refs(self, name):
        if name == "HEAD":  # refs/remotes/origin/HEAD is a pointer, and no branch of anyone's
            return []
        known = self._all_refs()
        return [ref for ref in (f"refs/heads/{name}", *[f"refs/remotes/{r}/{name}" for r in self._remotes()]) if ref in known]

    def _branch_tip(self, ref):
        return self._all_refs().get(ref)

    # ------------------------------------------------------------------ reverts

    def _revert_log(self):
        """({commit: the commit reverting it}, {pull request: the same}, {merge request: the same}), read once from the default branch,
        newest first, children before parents. A revert a later one undid does nothing, and the first revert that stands marks what it
        names, so a revert of a revert puts a commit back and no date can change the answer. A revert changes something: an empty commit
        with the words reverts nothing, either way, and neither does one a merge threw away. Reverting a merge reverts what it brought
        in, so each of those commits is named too. A revert only on this machine counts against a claim. A reapply only on this machine
        has not put anything back.
        """
        if self._reverts is None:
            commits, prs, mrs = {}, {}, {}
            self.tips()
            if self._every_tip:
                done = gitio.git(self.repo, "log", "--topo-order", "--format=%H%x00%T%x00%P%x00%B%x00%x00", "--extended-regexp",
                                 "--grep=^[[:space:]]*This reverts (commit|merge request) ", "--grep=^[[:space:]]*Reverts [^ ]*#[0-9]+",
                                 *self._every_tip, timeout=SLOW)
                if done.code:  # never read as "nothing was reverted"
                    self._stop(done, f"which commits were reverted on {self.branch}")
                entries = self._real_reverts(done.out)
                if entries:
                    self._all_parents()  # with the whole branch in hand, each question below costs no process
                self._batch_resolve([name for _, body in entries for pair in REVERT_COMMIT.findall(body) for name in pair if name])
                self._settle_arrivals([sha for sha, _ in entries])
                every_revert = self._every_revert = {sha for sha, _ in entries}
                for sha, body in entries:
                    if sha in commits or self._never_arrived(sha):
                        continue
                    here_only = sha not in self._parents

                    def mark(target):
                        if target != sha and not (here_only and target in every_revert and target in self._parents):
                            commits.setdefault(target, sha)  # a commit that names itself reverts nothing
                    named = REVERT_COMMIT.findall(body)
                    for first, base in named:
                        for target in self._revert_targets(sha, body, first, base, len(named) > 1):
                            mark(target)
                    for slug, number in REVERT_PR.findall(body):
                        if slug and own_repositories(self.plan) and not is_own(self.plan, slug):
                            continue  # another repository's pull request
                        prs.setdefault(int(number), sha)
                        # A rebase-merged commit keeps its own subject, the title of a one-commit pull request. Only then is the subject asked.
                        landed = self._landed_by_number(int(number)) or [self._by_subject(sha, body)]
                        for inside in landed:
                            if inside:
                                mark(inside)
                    for path, number in REVERT_MR.findall(body):
                        if path and own_repositories(self.plan) and not is_own(self.plan, path):
                            continue  # another project's merge request
                        mrs.setdefault(int(number), sha)
                        for inside in self._landed_by_merge_request(int(number)):
                            mark(inside)
            self._reverts = (commits, prs, mrs)
        return self._reverts

    def _revert_targets(self, revert, body, first, base, among_several):
        """The commits one `This reverts commit` line undoes. A squash can quote a revert and its reapply: the second names a commit that
        never reached this branch, and the first names one whose change is still there. Each line answers for itself, so a line naming
        nothing cannot cancel a real revert beside it.
        """
        full = self._resolve_id(first)
        if among_several:
            if not full or not self._on_default(full) or not self._really_undoes(revert, full):
                return []
        elif full is None or not self._on_default(full):
            full = self._by_subject(revert, body) or full  # a rebase gave the reverted commit a new id
        if full is None:
            return [first]
        mainline = self._resolve_id(base) if base else None
        return [full, *(self._commits_between(mainline, full) if mainline else [])]

    def _really_undoes(self, revert, target):
        """Whether a commit's own change is gone once a squash quoting its revert has landed. It is gone from a file that is back as it was
        before the commit, or that holds none of the lines the commit added and all it took away.
        """
        self._read_changes([target])
        files = [name for name in self._changes.get(target, ([], []))[1] if "\n" not in name]
        texts = gitio.blobs(self.repo, [f"{place}:{path}" for path in files for place in (f"{target}^", target, f"{revert}^", revert)],
                            failed=lambda why: self._stop(gitio.Done(1, "", why), f"what {target[:7]} changed"))

        def lines(text):
            return collections.Counter(line for line in (text or "").split("\n") if line.strip())
        taken = False
        for index in range(0, len(texts), 4):
            before, own, was, after = texts[index:index + 4]
            if after == was:  # the squash left this file alone. A submodule, with no text to read, lands here too
                if after == own:
                    return False
                continue
            if after == before:
                taken = True
                continue
            added, removed = lines(own) - lines(before), lines(before) - lines(own)
            left, had = lines(after), lines(was)
            there = [line for line in added if had[line] > 0]  # by count, against the squash's own parent: code repeats its lines
            if after == own or not (added or removed) or any(left[line] >= had[line] for line in there) or (removed and not set(removed) & set(left)):
                return False
            taken = taken or bool(there or removed)
        return taken

    def _real_reverts(self, text):
        """[(commit, message)] for the commits that changed something."""
        parsed = []
        for entry in text.split(RECORD):
            fields = entry.strip("\n").split("\0")
            if len(fields) >= 4:
                parsed.append((fields[0], fields[1], fields[2].split(), "\0".join(fields[3:])))
        parents = [p[2][0] for p in parsed if p[2]]
        trees = {}
        if parents:
            done = gitio.git(self.repo, "cat-file", "--batch-check", stdin_text="".join(f"{p}^{{tree}}\n" for p in parents))
            if done.code:
                self._stop(done, "what a revert changed")
            for parent, answer in zip(parents, done.out.split("\n")):
                trees[parent] = answer.split()[0] if answer.split() else None
        return [(sha, body) for sha, tree, ps, body in parsed if not ps or trees.get(ps[0]) != tree]

    def _commits_between(self, base, head):
        done = gitio.git(self.repo, "rev-list", f"{base}..{head}", timeout=SLOW)
        if done.code:
            self._stop(done, f"which commits {head[:7]} brought in")
        return done.out.split()

    def _read_subjects(self):
        """Every commit on the branch by its subject, read once, for the reverts that name a commit by its words. {subject: [(age, commit)]},
        {pull request: [(commit, its parents)]}, {commit: age}.
        """
        if self._subjects is None:
            done = gitio.git(self.repo, "log", "--topo-order", "--format=%H %P%x00%s", *self._every_tip, timeout=SLOW)
            if done.code:
                self._stop(done, f"the history of {self.branch}")
            by_subject, by_number, ages = {}, {}, {}
            for age, line in enumerate(done.out.split("\n")):  # not splitlines: a subject may hold a form feed
                ids, _, subject = line.partition("\0")
                words = ids.split()
                if not words:
                    continue
                ages[words[0]] = age
                by_subject.setdefault(subject, []).append((age, words[0]))
                number = LANDED_SQUASH.search(subject) or LANDED_MERGE.match(subject)
                if number:
                    by_number.setdefault(int(number.group(1)), []).append((words[0], words[1:]))
            self._subjects = (by_subject, by_number, ages)
        return self._subjects

    def _by_subject(self, revert, body):
        """The commit a revert means when the id it names is not on the branch: the nearest earlier commit with that subject. git's
        `Reapply "X"` is a revert of `Revert "X"`.
        """
        words = REVERT_SUBJECT.match(body.strip())
        if not words:
            return None
        subject = words.group(2) if words.group(1) == "Revert" else f'Revert "{words.group(2)}"'
        by_subject, _, ages = self._read_subjects()
        since = ages.get(revert, -1)
        return next((sha for age, sha in by_subject.get(subject, []) if age > since), None)

    def _with_what_it_brought_in(self, landings):
        found = []
        for sha, parents in landings:
            found.append(sha)
            if len(parents) > 1:  # a merge: its second parent's side came in with it
                found.extend(self._commits_between(parents[0], sha))
        return found

    def _landed_by_number(self, number):
        """The commits that landed a pull request, found by the subjects GitHub writes, and what a merge brought in with them."""
        return self._with_what_it_brought_in(self._read_subjects()[1].get(number, []))

    def _landed_by_merge_request(self, number):
        """The same for GitLab, whose trailer is in the message's body."""
        if self._merge_requests is None:
            done = gitio.git(self.repo, "log", "--format=%H %P%x00%B%x00%x00", "--extended-regexp", "--grep=^See merge request ", *self._every_tip, timeout=SLOW)
            if done.code:
                self._stop(done, "which commit landed a merge request")
            self._merge_requests = {}
            for entry in done.out.split(RECORD):
                ids, _, body = entry.strip("\n").partition("\0")
                words = ids.split()
                for said in (LANDED_MR.findall(body) if words else []):
                    self._merge_requests.setdefault(int(said), []).append((words[0], words[1:]))
        return self._with_what_it_brought_in(self._merge_requests.get(number, []))

    def undone_by(self, full):
        """The commit that reverted this one, if that revert still stands. A merge with nothing left of what it brought in is undone too: each commit
        in it was reverted, is itself a revert, or was thrown away.
        """
        commits = self._revert_log()[0]
        if full in commits or not commits:
            return commits.get(full)
        self._read_changes([full])
        parents = self._changes.get(full, ([], []))[0]
        if len(parents) < 2:
            return None
        self._read_changes([parents[1]])
        if parents[1] not in commits and parents[1] not in self._every_revert and len(self._parents.get(parents[1], [])) < 2 and not self._hollow_reason(parents[1], "it"):
            return None  # the side's last commit stands, so not all of it was reverted
        done = gitio.git(self.repo, "rev-list", "--no-merges", f"{parents[0]}..{full}", timeout=SLOW)
        if done.code:
            self._stop(done, f"which commits {full[:7]} brought in")
        inside = done.out.split()
        self._settle_arrivals(inside)
        taken_back = {commits[c] for c in inside if c in commits}  # a branch's revert of its own commit takes nothing else away, and leaves nothing
        if any(c not in commits and c not in taken_back and not self._hollow_reason(c, "it") for c in inside):
            return None
        return next((commits[c] for c in inside if c in commits and commits[c] not in inside), None)

    def _pr_undone_by(self, number):
        return self._revert_log()[1].get(number)

    # ------------------------------------------------------------------ what a commit is worth

    def _first_parent_line(self, tip):
        if tip not in self._first_parents:
            done = gitio.git(self.repo, "log", "--first-parent", "--format=%H", tip, timeout=SLOW)
            if done.code:
                self._stop(done, f"the history of {self.branch}")
            self._first_parents[tip] = {sha: age for age, sha in enumerate(done.out.split())}
        return self._first_parents[tip]

    def _all_parents(self):
        """{commit: its parents} for everything on the default branch, read once, and only when a commit came in from the side."""
        if self._parents is None:
            done = gitio.git(self.repo, "log", "--format=%H %P", *self.tips(), timeout=SLOW)
            if done.code:
                self._stop(done, f"the history of {self.branch}")
            self._parents = {}
            for line in done.out.split("\n"):
                ids = line.split()
                if ids:
                    self._parents[ids[0]] = ids[1:]
        return self._parents

    def _landing(self, commit, line):
        """The oldest commit of a first-parent line that holds this commit: the merge that landed it there."""
        if self._children is None:
            self._children = {}
            for child, parents in self._all_parents().items():
                for parent in parents:
                    self._children.setdefault(parent, []).append(child)
        landing, seen, waiting = None, {commit}, [commit]
        while waiting:
            for child in self._children.get(waiting.pop(), []):
                if child in line:
                    if landing is None or line[child] > line[landing]:
                        landing = child
                elif child not in seen:
                    seen.add(child)
                    waiting.append(child)
        return landing

    def _settle_arrivals(self, commits):
        """For each commit that came in from the side: whether the merge that landed it took any of its changes. It did not when none of
        the commit's files moved at that merge and they differ from the commit's own, as with `git merge -s ours`. A file already there
        with those very bytes arrived, whoever brought it, as with a hotfix cherry-picked and merged back. One tip that took it is enough.
        """
        pending = [c for c in commits if c not in self._lost_at]
        if not pending:
            return
        self._read_changes(pending)
        questions = []
        for commit in pending:
            self._lost_at[commit] = None
            files = [name for name in self._changes.get(commit, ([], []))[1] if "\n" not in name]
            for tip in self.tips():
                line = self._first_parent_line(tip)
                if commit in line:
                    questions = [q for q in questions if q[0] != commit]
                    break
                if not files or (len(self.tips()) > 1 and not self._is_ancestor(commit, tip)):
                    continue
                landing = self._landing(commit, line)
                parents = self._all_parents().get(landing, [])
                if landing and parents:
                    questions.append((commit, landing, parents[0], files))
        if questions:
            self._ask_about_landings(questions)

    def _ask_about_landings(self, questions):
        specs = [f"{place}:{path}" for commit, landing, before, files in questions for path in files for place in (landing, before, commit)]
        done = gitio.git(self.repo, "cat-file", "--batch-check", stdin_text="".join(f"{spec}\n" for spec in specs), timeout=SLOW)
        if done.code:
            self._stop(done, "what a merge took")
        answers = iter(line.split()[0] if line.split() and not line.endswith(" missing") else None for line in done.out.split("\n")[:len(specs)])
        verdicts = {}
        for commit, landing, _, files in questions:
            lost = True
            for _path in files:
                there, before, own = next(answers), next(answers), next(answers)
                lost = lost and there == before and there != own
            verdicts.setdefault(commit, []).append(landing if lost else None)
        for commit, landings in verdicts.items():  # one tip that took it is enough
            self._lost_at[commit] = landings[0] if all(landings) else None

    def _never_arrived(self, full):
        if full not in self._lost_at:
            self._settle_arrivals([full])
        return self._lost_at[full]

    def _tracker_paths(self):
        """The tracker's own files, as this repository names them, asked from each file's own folder: a plan in a linked worktree
        with an absolute `repo` lives under another top-level than the one `repo` answers for.
        """
        if self._tracker is None:
            self._tracker = set()
            done = gitio.git(self.repo, "rev-parse", "--git-common-dir")
            if done.code:
                self._stop(done, "where the repository keeps its files")
            own = os.path.realpath(os.path.join(str(self.repo), done.out.strip("\n")))
            self._ignores_case = gitio.git(self.repo, "config", "--bool", "core.ignorecase").out.strip() == "true"
            prefixes = {}
            for path in self.plan.tracked:
                real = os.path.realpath(path)
                folder = os.path.dirname(real)
                if folder not in prefixes:
                    prefixes[folder] = self._prefix_in(folder, own)
                if prefixes[folder] is not None:
                    self._tracker.add(self._as_git_compares(prefixes[folder] + os.path.basename(real)))
        return self._tracker

    def _prefix_in(self, folder, own):
        """A folder's path from the top of the repository, or None when that folder is in another repository, or in none."""
        done = gitio.git(folder, "rev-parse", "--git-common-dir", "--show-prefix")
        if done.code:
            return None
        common, _, prefix = done.out.partition("\n")
        return prefix.strip("\n") if os.path.realpath(os.path.join(folder, common)) == own else None

    def _as_git_compares(self, name):
        return name.lower() if self._ignores_case else name

    def _hollow_reason(self, full, label):
        """Why a commit on the branch is still no evidence, or None."""
        if full not in self._changes:
            self._read_changes([full])
        files = self._changes.get(full, ([], ["?"]))[1]
        if not files:
            return f"{label} changes no file"
        tracker = self._tracker_paths()
        if all(self._as_git_compares(name) in tracker or os.path.basename(name) == POINTER for name in files):
            return f"{label} only changes the tracker itself"
        merge = self._never_arrived(full)
        if merge:
            return f"{label} reached {self.branch} through {merge[:7]}, a merge that took none of its changes"
        return None

    def _unpushed_words(self, label):
        return f"{label} is on your local {self.branch}, and {self._unpushed}"

    def _off_the_branch(self, full, label, words):
        """A commit the default branch does not hold. On your local branch, that only means it has not been pushed yet."""
        self.tips()
        local = f"refs/heads/{self.branch}"
        if local in self._every_tip and local not in self._tips and self._is_ancestor(full, local):
            return Result(UNPROVEN, f"{label} is on your local {self.branch} and not on {self._tips[0].replace('refs/remotes/', '')}; push it")
        return Result(CONTRADICTED, words)

    def _held(self, full, label):
        """The rules every commit claim answers to, once it is known to exist."""
        if not self._on_default(full):
            return self._off_the_branch(full, label, f"{label} is not on {self.branch}")
        undone = self.undone_by(full)
        if undone:
            return Result(CONTRADICTED, f"{label} was reverted on {self.branch} by {undone[:7]}")
        hollow = self._hollow_reason(full, label)
        if hollow:
            return Result(UNPROVEN, hollow)
        if self._unpushed:
            return Result(UNPROVEN, self._unpushed_words(label))
        return Result(VERIFIED, f"{label} is on {self.branch}")

    # ------------------------------------------------------------------ claims

    def commit_id(self, hex_id, label=None):
        label = label or f"commit {hex_id}"
        if self.repo is None:
            return Result(UNPROVEN, f"{label}: {self.no_repo}", True)
        full = self._resolve_id(hex_id)
        if full is None:
            if self._has_remote():
                return Result(ABSENT, f"{label} is not in {self.repo.name}'s clone; fetch, or correct it")
            return Result(CONTRADICTED, f"{label} is not in the repository {self.repo.name}")
        return self._held(full, label)

    def tag(self, name):
        label = f"tag {name}"
        if self.repo is None:
            return Result(UNPROVEN, f"{label}: {self.no_repo}", True)
        if not SAFE_REF.match(name):
            return Result(CONTRADICTED, f"{label} cannot be a git reference")
        full = self._resolve(f"refs/tags/{name}")
        if full is None:
            if self._has_remote():
                return Result(ABSENT, f"{label} is not in {self.repo.name}'s clone; fetch --tags, or correct it")
            return Result(CONTRADICTED, f"{label} is not in the repository {self.repo.name}")
        return self._held(full, label)

    def named_ref(self, value):
        """A plan's `ref` group: a commit id, or a tag. Never a branch or HEAD, which name wherever they happen to point."""
        if self.repo is None:
            return Result(UNPROVEN, f"{value}: {self.no_repo}", True)
        if not SAFE_REF.match(str(value)):
            return Result(CONTRADICTED, f"{value} cannot be a git reference")
        if HEX_ID.match(value):
            return self.commit_id(value, value)
        full = self._resolve(f"refs/tags/{value}")
        if full is None:
            if self._has_remote():
                return Result(ABSENT, f"{value} is not in {self.repo.name}'s clone; fetch --tags, or correct it")
            return Result(CONTRADICTED, f"{value} is not a tag in {self.repo.name}")
        return self._held(full, value)

    def pull_request(self, number):
        label = f"PR #{number}"
        if self.repo is None:
            return Result(UNPROVEN, f"{label}: {self.no_repo}", True)
        if self.offline:
            return Result(UNVERIFIED, f"{label}: offline")
        if not self._has_remote():
            return Result(UNPROVEN, f"{label}: {self.repo.name} has no remote, so nothing could confirm it; name its commit instead", True)
        if self._prs is None:
            self._prs = gitio.pull_requests(self.repo)
        if isinstance(self._prs, str):
            return Result(UNVERIFIED, f"{label}: {self._prs}")
        pr = self._prs.get(number)
        if pr is None and len(self._prs) >= gitio.PR_LIMIT:
            pr = gitio.pull_request(self.repo, number)
            if pr is None:
                return Result(UNVERIFIED, f"{label}: beyond the {gitio.PR_LIMIT} pull requests read, and gh could not answer for it")
        if pr is None:
            return Result(CONTRADICTED, f"{label} does not exist on {self.repo.name}'s remote")
        state = str(pr.get("state", "")).upper()
        if state != "MERGED":
            return Result(CONTRADICTED, f"{label} is {state.lower() or 'not merged'}, not merged")
        base = pr.get("baseRefName")
        if base != self.branch:
            return Result(UNPROVEN, f"{label} merged into {base}, not {self.branch}")
        undone = self._pr_undone_by(number)
        if undone:
            return Result(CONTRADICTED, f"{label} was reverted on {self.branch} by {undone[:7]}")
        return self._merged_commit(label, (pr.get("mergeCommit") or {}).get("oid"), f"is merged into {self.branch}")

    def merge_request(self, number):
        label = f"MR !{number}"
        if self.repo is None:
            return Result(UNPROVEN, f"{label}: {self.no_repo}", True)
        if self.offline:
            return Result(UNVERIFIED, f"{label}: offline")
        if not self._has_remote():
            return Result(UNPROVEN, f"{label}: {self.repo.name} has no remote, so nothing could confirm it; name its commit instead", True)
        mr = gitio.merge_request(self.repo, number)
        if isinstance(mr, str):
            return Result(UNVERIFIED, f"{label}: {mr}")
        state = str(mr.get("state", "")).lower()
        if state != "merged":
            return Result(CONTRADICTED, f"{label} is {state or 'not merged'}, not merged")
        target = mr.get("target_branch")
        if target != self.branch:
            return Result(UNPROVEN, f"{label} merged into {target}, not {self.branch}")
        reverter = self._revert_log()[2].get(number)
        if reverter:
            return Result(CONTRADICTED, f"{label} was reverted on {self.branch} by {reverter[:7]}")
        return self._merged_commit(label, mr.get("squash_commit_sha") or mr.get("merge_commit_sha") or mr.get("sha"), f"is merged into {self.branch}")

    def _merged_commit(self, label, oid, words):
        """The forge says merged. git still has to agree, since after a force-push the forge goes on saying it, and the commit answers to
        the rules any commit does. A pull request that only edits the table is no evidence, whoever merged it.
        """
        if not oid:
            return Result(UNPROVEN, f"{label} is merged, and the forge names no commit for it, so git cannot hold it; name the commit")
        full = self._resolve_id(oid) if HEX_ID.match(str(oid)) else None
        if full is None:
            return Result(ABSENT, f"{label}'s commit {str(oid)[:7]} is not in {self.repo.name}'s clone; fetch, or correct it")
        if not self._on_default(full):
            return self._off_the_branch(full, label, f"{label} says merged, and its commit {oid[:7]} is not on {self.branch}")
        undone = self.undone_by(full)
        if undone:
            return Result(CONTRADICTED, f"{label} was reverted on {self.branch} by {undone[:7]}")
        hollow = self._hollow_reason(full, f"{label}'s commit {full[:7]}")  # on a rebase merge, the forge names only the last of them
        if hollow:
            return Result(UNPROVEN, f"{hollow}; if the work is in another commit of it, cite that commit instead of the pull request")
        if self._unpushed:
            return Result(UNPROVEN, self._unpushed_words(label))
        return Result(VERIFIED, f"{label} {words}")

    def branch_named(self, name):
        """(result, whether the branch is already on the default branch)."""
        if self.repo is None:
            return Result(UNPROVEN, f"branch {name}: {self.no_repo}", True), False
        if name == self.branch:
            return Result(CONTRADICTED, f"branch {name} is the default branch, which names no work in progress"), False
        refs = self._branch_refs(name)
        if refs:
            merged = self._on_default(self._branch_tip(refs[0]))
            if self._has_remote() and all(ref.startswith("refs/heads/") for ref in refs):
                return Result(UNPROVEN, f"branch {name} is only on this machine; push it, or a clone and CI will not find it"), merged
            return Result(VERIFIED, f"branch {name} exists"), merged
        return Result(CONTRADICTED, f"branch {name} does not exist in {self.repo.name}"), False

    def claim(self, claim):
        if claim.kind in ("sha", "bare"):
            return self.commit_id(claim.value)
        if claim.kind == "pr":
            return self.pull_request(claim.value)
        if claim.kind == "mr":
            return self.merge_request(claim.value)
        if claim.kind == "tag":
            return self.tag(claim.value)
        if claim.kind == "ref":
            return self.named_ref(claim.value)
        return Result(UNVERIFIED, f"{claim.value!r} matches the plan's evidence pattern")


def best(results):
    """A row stands on the strongest thing it names; `gate` and `shipped` still say what does not hold beside it."""
    for state in (VERIFIED, UNVERIFIED, UNPROVEN, ABSENT, CONTRADICTED):
        chosen = [r for r in results if r.state == state]
        if chosen:
            return chosen[0]
    return None
