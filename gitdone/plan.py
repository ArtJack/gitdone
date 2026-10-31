"""The plan file: everything about a project that its status table cannot say about itself."""
import collections
import datetime
import difflib
import errno
import json
import os
import pathlib
import re
import stat

from . import gitio

Kind = collections.namedtuple("Kind", "name short phrase weight evidence")
Group = collections.namedtuple("Group", "id label title domains total")

DEFAULT_KINDS = [
    {"name": "Live", "weight": 1.0, "evidence": "release"},
    {"name": "Built, not live", "short": "Built", "weight": 0.8, "evidence": "branch"},
    {"name": "Partial", "weight": 0.4, "evidence": "note"},
    {"name": "Not built", "weight": 0.0},
]
EVIDENCE_RULES = (None, "release", "branch", "note")
SECTION_TYPES = ("group", "workstreams", "table", "list", "products", "rows")
RULE_KEYS = ("kinds", "default_branch", "repo", "status_doc", "status_out", "evidence_pattern", "rows_total", "groups")
MAX_NUMBERS = 100000


class PlanError(Exception):
    """The plan cannot be used; the message says why."""


def numbers(value, what):
    """A list of ints from 3, [1, 2] or "1-11,14"."""
    if isinstance(value, bool):
        raise PlanError(f"{what}: expected numbers, got {value!r}")
    if isinstance(value, int):
        return [value]
    if isinstance(value, list):
        if all(isinstance(n, int) and not isinstance(n, bool) for n in value):
            return list(value)
        raise PlanError(f"{what}: expected numbers, got {value!r}")
    if isinstance(value, str):
        out = []
        for part in value.split(","):
            low, dash, high = part.strip().partition("-")
            if not low.isdigit() or (dash and not high.isdigit()) or len(low) > 9 or len(high) > 9:
                raise PlanError(f"{what}: {value!r} is not a range like \"1-11,14\"")
            if len(out) + int(high if dash else low) - int(low) > MAX_NUMBERS:
                raise PlanError(f"{what}: {value[:40]!r} names more than {MAX_NUMBERS} rows")
            out.extend(range(int(low), int(high if dash else low) + 1))
        return out
    raise PlanError(f"{what}: expected numbers, got {value!r}")


def _typed(data, key, expected, default):
    value = data.get(key, default)
    if value is not default and (not isinstance(value, expected) or isinstance(value, bool)):
        raise PlanError(f"{key}: expected a {expected.__name__}, got {value!r}")
    return value


KIND_KEYS = {"name", "short", "phrase", "weight", "evidence"}
FOCUS_KEYS = {"paths", "upkeep"}


def _no_duplicates(pairs):
    """A key given twice is read as its last, and hides from the eye. In a file that sets the gate's rules, that is refused."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise PlanError(f"the plan gives {key!r} twice")
        seen[key] = value
    return seen


def _kind(raw):
    if not isinstance(raw, dict) or "name" not in raw or "weight" not in raw:
        raise PlanError(f"kinds: each kind needs a name and a weight, got {raw!r}")
    unknown = set(raw) - KIND_KEYS
    if unknown:  # `evidance` would otherwise switch a rule off in silence
        raise PlanError(f"kinds: {raw['name']}: unknown key {sorted(unknown)[0]!r}; a kind has {', '.join(sorted(KIND_KEYS))}")
    weight = raw["weight"]
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
        raise PlanError(f"kinds: {raw['name']}: the weight must be between 0 and 1, got {weight!r}")
    if raw.get("evidence") not in EVIDENCE_RULES:
        raise PlanError(f"kinds: {raw['name']}: unknown evidence rule {raw['evidence']!r}")
    name = raw["name"]
    return Kind(name, raw.get("short", name), raw.get("phrase", name.lower()), weight, raw.get("evidence"))


def read_file(path):
    if not stat.S_ISREG(os.stat(path).st_mode):  # a plan can name anything, and a device or a pipe would hang the gate
        raise OSError(errno.EINVAL, "not a regular file")
    return pathlib.Path(path).read_text(encoding="utf-8")


def _text(data, key, default=None):
    """A plan's word. Anything but text here would surface later, far from the plan, and stop somebody's unrelated commit."""
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise PlanError(f"{key}: expected text, got {value!r}")
    return value


def _date(data, key):
    """A day a plan names, as YYYY-MM-DD. Anything else would surface far from the plan, in the middle of somebody's morning."""
    value = _text(data, key)
    if value is None:
        return None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):  # newer Pythons read more shapes than the oldest one here
            raise ValueError
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError:
        raise PlanError(f"{key}: expected a date like 2026-12-01, got {value!r}")


def _strings(data, key):
    value = _typed(data, key, list, [])
    for item in value:
        if not isinstance(item, str):
            raise PlanError(f"{key}: expected a list of file names, got {item!r}")
    return value


def _no_misspelled_rules(data):
    """A plan may carry keys of its own for its sections. One no section reads that is nearly a rule's name is a rule being ignored in silence."""
    rules = {key.replace("_", ""): key for key in (*RULE_KEYS, "badge", "branch_aliases", "verdict_state", "deadline", "requirements", "focus", "start")}
    sections = data.get("sections")
    used = {s["from"] for s in sections if isinstance(s, dict) and isinstance(s.get("from"), str)} if isinstance(sections, list) else set()
    for key in data:
        if key in rules.values() or key in used:
            continue
        close = difflib.get_close_matches(re.sub(r"[-_ ]", "", key.lower()), rules, n=1, cutoff=0.85)
        if close:
            raise PlanError(f"the plan has {key!r}. Did you mean {rules[close[0]]!r}? As written, that rule is ignored")


def symlink_in(base, value):
    """Whether a path a plan or a pointer names is a symbolic link or sits behind one. An absolute path's folders are the machine's own
    business (/tmp is a link on a Mac), so only its last step counts.
    """
    if os.path.isabs(value):
        return os.path.islink(value)
    logical = os.path.normpath(os.path.join(os.path.realpath(base), value))
    return os.path.realpath(logical) != logical


def _same_file(one, other):
    """One file by two names: the same words, or on a disk that ignores case, the same file."""
    if one == other:
        return True
    try:
        return os.path.samefile(one, other)
    except OSError:
        return False


def _not_a_regular_file(path):
    try:
        return not stat.S_ISREG(os.stat(path).st_mode)
    except OSError:
        return False


class Plan:
    def __init__(self, path, read=read_file):
        """`read` turns a path into text. A git hook passes one that reads what the commit will contain."""
        if os.path.islink(pathlib.Path(path).expanduser()):
            raise PlanError(f"the plan {path} is a symbolic link; the tracker's files must be real files")
        self.path = pathlib.Path(path).expanduser().resolve()
        self.read = read
        try:
            data = json.loads(self.text_of(self.path, "the plan"), object_pairs_hook=_no_duplicates)
        except ValueError as err:
            raise PlanError(f"the plan {self.path} is not valid JSON: {err}")
        if not isinstance(data, dict) or data.get("status_doc") is None:
            raise PlanError(f"the plan {self.path} names no status_doc")
        _no_misspelled_rules(data)
        self.data = data
        self.dir = self.path.parent
        self.title = data.get("title", "Status")
        self.release = _text(data, "release", "")
        self.release_sha = _text(data, "release_sha")
        self.doc = self._tracker_file("status_doc", _text(data, "status_doc"))
        self.out = self._tracker_file("status_out", _text(data, "status_out", "STATUS.md"))
        badge = _text(data, "badge")
        self.badge = self._tracker_file("badge", badge) if badge else None
        for one, other in ((self.path, self.doc), (self.path, self.out), (self.doc, self.out)):
            if _same_file(one, other):
                raise PlanError("the plan, the status table and the view must be three different files, "
                                f"or a render would overwrite one: {self.path.name}, {self.doc.name}, {self.out.name}")
        self.tracked = [p for p in (self.path, self.doc, self.out, self.badge) if p]
        self.footer = data.get("footer", "")
        if self.badge and any(_same_file(self.badge, other) for other in (self.path, self.doc, self.out)):
            raise PlanError(f"the badge cannot be the same file as the plan, the table or the view: {self.badge.name}")
        repo = _text(data, "repo")
        self.repo = self._path(repo) if repo else None
        self.default_branch = _text(data, "default_branch", "main")
        self.branch_aliases = _typed(data, "branch_aliases", dict, {})
        self.evidence_pattern = _text(data, "evidence_pattern")
        verdict_state = _text(data, "verdict_state")
        self.verdict_state = self._path(verdict_state) if verdict_state else None
        if self.verdict_state and _not_a_regular_file(self.verdict_state):
            raise PlanError(f"verdict_state: {verdict_state} is not a regular file")
        self.deadline = _date(data, "deadline")
        self.start = _date(data, "start")
        self.requirements = _strings(data, "requirements")
        self.focus = _typed(data, "focus", dict, {})
        for key in self.focus:
            if key not in FOCUS_KEYS:
                raise PlanError(f"focus: {key!r} is not one of {', '.join(sorted(FOCUS_KEYS))}")
        self.generated_by = data.get("generated_by", "gitdone render")
        self.regenerate = data.get("regenerate", "gitdone render --write")
        self.noun = data.get("noun", "rows")
        self.scale = data.get("scale")
        self.rows_total = _typed(data, "rows_total", int, None)
        self.kinds = [_kind(k) for k in _typed(data, "kinds", list, DEFAULT_KINDS)]
        if not self.kinds:
            raise PlanError("kinds: the list is empty")
        self.kind_names = [k.name for k in self.kinds]
        if len(set(self.kind_names)) != len(self.kind_names):
            raise PlanError("kinds: two kinds share a name")
        self.weights = {k.name: k.weight for k in self.kinds}
        self.strict_kind = self.kinds[0]
        self.groups = [self._group(g) for g in _typed(data, "groups", list, [])]
        self.workstreams = _typed(data, "workstreams", list, [])
        for w in self.workstreams:
            if not isinstance(w, dict) or "id" not in w:
                raise PlanError(f"workstreams: each one needs an id, got {w!r}")
        self.order = _typed(data, "order", list, [w["id"] for w in self.workstreams])
        self.sections = _typed(data, "sections", list, None) or self._default_sections()
        for section in self.sections:
            self._check_section(section)

    def root(self):
        """The folder this plan may write inside: its repository, or its own folder when it is in none."""
        top = gitio.git(self.dir, "rev-parse", "--show-toplevel")
        return os.path.realpath(top.out.strip() if top.code == 0 and top.out.strip() else self.dir)

    def check_writable(self, *paths):
        """A plan can come from a clone, and it names what a command overwrites. It never reaches outside its own project, and never
        into git's own folder, where a file it wrote would be run or would break the repository.
        """
        root = self.root()
        git_dirs = []
        for ask in ("--absolute-git-dir", "--git-common-dir"):
            where = gitio.git(self.dir, "rev-parse", ask)
            if where.code == 0 and where.out.strip():
                git_dirs.append(os.path.realpath(os.path.join(self.dir, where.out.strip())))
        for path in paths:
            real = os.path.realpath(path)
            if not real.startswith(root + os.sep):
                raise PlanError(f"the plan names {path}, which is outside {root}; refusing to write there. "
                                "Keep the plan, the table and the view in one project")
            # A worktree may live under .git, and its own files are its own. Everything else there is git's.
            if any((real == place or real.startswith(place + os.sep)) and not root.startswith(place + os.sep) for place in git_dirs):
                raise PlanError(f"the plan names {path}, which is inside git's own folder; refusing to write there")

    def text_of(self, path, what):
        try:
            return self.read(path)
        except OSError as err:
            raise PlanError(f"cannot read {what} {path}: {err.strerror or err}")
        except UnicodeDecodeError:
            raise PlanError(f"{what} {path} is not UTF-8")

    def _tracker_file(self, key, value):
        """A file the tracker reads and rewrites: real, regular, and not in git's own folder, whatever the words say."""
        if symlink_in(self.dir, os.path.expanduser(value)):
            raise PlanError(f"{key}: {value} is a symbolic link, or sits behind one; the tracker's files must be real files")
        path = self._path(value)
        if any(part.lower() == ".git" for part in pathlib.PurePath(os.path.relpath(path, self.dir)).parts):  # from here: a worktree may live under one
            raise PlanError(f"{key}: {value} is inside a .git folder; the tracker's files are the project's own")
        if _not_a_regular_file(path):
            raise PlanError(f"{key}: {value} is not a regular file")
        return path

    def _path(self, value):
        path = pathlib.Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self.dir / path).resolve()

    def _group(self, raw):
        if not isinstance(raw, dict) or "label" not in raw or "domains" not in raw:
            raise PlanError(f"groups: each group needs a label and its domains, got {raw!r}")
        label = raw["label"]
        return Group(raw.get("id", label), label, raw.get("title", label),
                     numbers(raw["domains"], f"group {label}: domains"), raw.get("total"))

    def _check_section(self, section):
        kind = section.get("type") if isinstance(section, dict) else None
        if kind not in SECTION_TYPES:
            raise PlanError(f"sections: unknown type {kind!r}")
        needed = {"table": ("title", "from", "columns"), "list": ("title", "from", "format")}.get(kind, ())
        for key in needed:
            if key not in section:
                raise PlanError(f"sections: a {kind} section needs {key!r}, got {section!r}")
        for column in section.get("columns", []):
            if "head" not in column or "key" not in column:
                raise PlanError(f"sections: a column needs a head and a key, got {column!r}")
        if kind == "group" and section.get("group"):
            self.group(section["group"])

    def _default_sections(self):
        sections = [{"type": "group", "group": g.id, "style": "full"} for g in self.groups]
        if not sections:
            sections = [{"type": "group", "style": "full"}]
        if self.workstreams:
            sections.append({"type": "workstreams"})
        if self.data.get("products"):
            sections.append({"type": "products"})
        if not self.workstreams:
            sections.append({"type": "rows"})
        return sections

    def group(self, group_id):
        for g in self.groups:
            if g.id == group_id:
                return g
        raise PlanError(f"no group has the id {group_id!r}")

    def effective_groups(self, table):
        """The plan's groups, or one implicit group holding the whole table."""
        if self.groups:
            return self.groups
        return [Group("all", "All", self.title, [d.n for d in table.domains], None)]

    def workstream(self, ws_id):
        for w in self.workstreams:
            if w.get("id") == ws_id:
                return w
        raise PlanError(f"order names {ws_id!r}, and no workstream has that id")

    def problems(self, table):
        """Why this plan and this table cannot be rendered together: the shape, then the references."""
        out = list(table.problems)
        if not table.domains:
            out.append(f"{self.doc.name} holds no domain, so there is nothing to measure; a domain starts with `### 1. Name (count)`")
        if len(self.kinds) < 2:
            out.append("kinds: a plan needs at least two kinds, or nothing could ever be open")
        if self.strict_kind.evidence != "release":
            out.append(f"kinds: {self.strict_kind.name} is what strict counts, so it must have \"evidence\": \"release\"")
        seen = {}
        known = {d.n: d for d in table.domains}
        for g in self.groups:
            rows = 0
            for n in g.domains:
                if n not in known:
                    out.append(f"group {g.label} names domain {n}, which the table does not have")
                    continue
                if n in seen:
                    out.append(f"domain {n} is in two groups: {seen[n]} and {g.label}")
                seen[n] = g.label
                rows += len(known[n].rows)
            if g.total is not None and rows != g.total:
                out.append(f"group {g.label}: its domains hold {rows} rows, the plan says {g.total}")
        if self.groups:
            for d in table.domains:
                if d.n not in seen:
                    out.append(f"domain {d.n} ({d.name}) is in no group")
        if self.rows_total is not None and len(table.rows) != self.rows_total:
            out.append(f"the table has {len(table.rows)} rows, the plan says {self.rows_total}")
        ids = {w.get("id") for w in self.workstreams}
        for ws_id in self.order:
            if ws_id not in ids:
                out.append(f"order names {ws_id!r}, and no workstream has that id")
        for w in self.workstreams:
            for n in numbers(w.get("rows", []), f"workstream {w.get('id')}: rows"):
                if n not in table.rows:
                    out.append(f"workstream {w.get('id')} names row {n}, which the table does not have")
        for p in self.data.get("products", []):
            if "rows" in p:
                for n in numbers(p["rows"], f"product {p.get('name')}: rows"):
                    if n not in table.rows:
                        out.append(f"product {p.get('name')} names row {n}, which the table does not have")
        return out
