#!/usr/bin/env python3
"""Check repository and workdir paths against docs/directory-contracts.md.

The check only reports. It never renames, moves, or deletes anything.

Usage:
    python3 tests/check_layout.py              # repository only
    python3 tests/check_layout.py --workdir    # also $ISIMIP4B_WORKDIR
    python3 tests/check_layout.py --workdir /path/to/workdir

Exit status is 1 when at least one error is found, otherwise 0. Warnings do
not change the exit status.

When a rule in docs/directory-contracts.md or docs/glossary.md changes, the
constants below must be updated in the same change.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

# --- Identifiers from docs/glossary.md -------------------------------------

GCMS = {"ec-earth3-esm-1-1", "ukesm1-3-ll"}
CLIMATE_SCENARIOS = {"picontrol", "historical", "vl", "h"}
CLIMATE_INPUT_ALIASES = {
    "picontrol", "esm-picontrol", "historical", "esm-hist",
    "scen7-vl", "esm-scen7-vl", "scen7-h", "esm-scen7-h",
}
SOC_SCENARIOS = {
    "histsoc", "1850soc", "2021soc", "2021soc-from-histsoc",
    "ssp1vlsoc-noadapt", "ssp3hsoc-noadapt",
}
SENS_SCENARIOS = {"default", "extrasoc", "2021co2"}
PERIODS = {"spinup", "pre-industrial", "historical", "future"}

# --- Structure from docs/directory-contracts.md ----------------------------

STAGES = [
    "01_acquisition", "02_preprocessing", "03_parameters", "04_forcing",
    "05_simulation", "06_postprocessing", "07_quality_control", "08_delivery",
]
REPO_TOP = {
    ".githooks", ".gitignore", "AGENTS.md", "CLAUDE.md", "README.md",
    "analysis", "configs", "docs", "environments", "manifests", "model",
    "tests", "workflow",
}
# Tool configuration that is not project content.
REPO_IGNORED_TOP = {".git", ".claude"}
REPO_REQUIRED = [
    ".githooks/pre-commit", ".gitignore", "AGENTS.md", "CLAUDE.md",
    "README.md", "analysis/README.md", "configs", "docs/README.md",
    "docs/glossary.md", "docs/directory-contracts.md", "environments",
    "manifests", "model", "tests/check_layout.py", "workflow",
] + ["workflow/" + s for s in STAGES]
REPO_CHILDREN = {
    "configs": {"README.md", "campaigns", "resources"},
    "manifests": {"README.md", "inputs", "parameters", "runs", "deliveries"},
    "tests": {"README.md", "check_layout.py", "unit", "integration", "smoke",
              "fixtures"},
    "workflow": {"README.md", "common"} | set(STAGES),
    "workflow/03_parameters": {"README.md", "domain", "soil", "vegetation",
                               "landuse", "routing", "dams", "irrigation",
                               "water_use"},
    "workflow/04_forcing": {"README.md", "climate", "landuse", "water_use"},
    "workflow/05_simulation": {"README.md", "build", "render", "submit",
                               "monitor", "templates"},
    "workflow/05_simulation/templates": {"README.md", "vic", "slurm"},
}
DOCS_FILES = {
    "README.md", "glossary.md", "directory-contracts.md", "architecture.md",
    "workflow.md", "experiment-matrix.md", "runbook.md",
}
DOCS_DIRS = {"decisions", "audits"}

WORKDIR_TOP = [
    "raw", "intermediate", "parameters", "forcing", "builds", "runs",
    "postprocessed", "qc", "delivery", "analysis", "logs", "scratch",
]
QC_OBJECT_TYPES = {
    "raw", "intermediate", "parameters", "forcing", "builds", "runs",
    "postprocessed", "delivery",
}
PARAMETER_COMPONENTS = REPO_CHILDREN["workflow/03_parameters"] - {"README.md"}
RUN_CHILDREN = {"config", "logs", "states", "output", "run_manifest.json",
                "chunks"}
CHUNK_CHILDREN = {"config", "logs", "states", "output"}
DELIVERY_CHILDREN = {"files", "inventory.tsv", "checksums.sha256",
                     "qc-summary.json", "delivery-manifest.yaml"}

# --- Naming rules ----------------------------------------------------------

VERSION_TOKEN = re.compile(
    r"^(v\d+|old|fix|fixed|final|latest)$")
TOKEN_SPLIT = re.compile(r"[-_.\s]+")
LOWER_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
CHUNK_ID = re.compile(r"^\d{4}-\d{4}$")
CACHE_ID = re.compile(r"^[a-z0-9]+([-_][a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
CACHE_KEY_LINE = re.compile(r"^([a-z_]+):(.*)$")
CACHE_REQUIRED = ["cache_id", "cache_fingerprint", "producer_stage",
                  "created_by", "code_commit", "code_dirty", "created_at",
                  "inputs", "rebuild_command"]
CACHE_ROOT_ENTRIES = {"cache.yaml", "_SUCCESS", "data"}
MANIFEST_INTERMEDIATE =re.compile(r"(^|[^A-Za-z0-9_])intermediate/")
RUN_ID = re.compile(
    r"^(?P<gcm>[a-z0-9-]+)_(?P<climate>[a-z0-9-]+)_(?P<soc>[a-z0-9-]+)"
    r"_(?P<sens>[a-z0-9-]+)_(?P<period>[a-z0-9-]+)(__(?P<label>[a-z0-9-]+))?$")
EXPERIMENT_ID = re.compile(
    r"^(?P<climate>[a-z0-9-]+)_(?P<soc>[a-z0-9-]+)_(?P<sens>[a-z0-9-]+)$")

DATA_SUFFIXES = {
    ".nc", ".nc4", ".h5", ".hdf", ".hdf5", ".he5", ".grb", ".grib", ".grib2",
    ".tif", ".tiff", ".npy", ".npz", ".pkl", ".pickle", ".parquet",
    ".feather", ".zarr", ".out", ".err", ".log", ".o", ".a", ".so", ".exe",
}
CODE_SUFFIXES = {".py", ".sh", ".bash", ".sbatch", ".slurm", ".r", ".jl",
                 ".ipynb", ".c", ".f90", ".f"}
WORKFLOW_TEXT_SUFFIXES = {".py", ".sh", ".bash", ".sbatch", ".slurm", ".yaml",
                          ".yml", ".toml", ".cfg", ".ini", ".txt", ".j2",
                          ".tmpl", ".template", ".r"}
LANGUAGE_DIRS = {"python", "py", "shell", "bash", "sh", "r", "julia"}
ANALYSIS_REFERENCE = re.compile(
    r"(^|[^A-Za-z0-9_])analysis/|^\s*(from|import)\s+analysis\b", re.M)
MAIN_GUARD = re.compile(r"^if\s+__name__\s*==\s*['\"]__main__['\"]", re.M)
CAMPAIGN_SEGMENTS = re.compile(r"^\s*segments\s*:", re.M)
REPO_WARN_BYTES = 1 * 1024 * 1024
REPO_ERROR_BYTES = 5 * 1024 * 1024
WORKDIR_MAX_DEPTH = 7


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"ERROR   {path}: {message}")

    def warn(self, path: str, message: str) -> None:
        self.warnings.append(f"WARNING {path}: {message}")


def version_tokens(name: str) -> list[str]:
    return [t for t in TOKEN_SPLIT.split(name.lower()) if VERSION_TOKEN.match(t)]


def check_name(report: Report, path: str, name: str) -> None:
    tokens = version_tokens(name)
    if tokens:
        report.error(path, f"version-like name token {tokens}; use Git or a "
                           "meaningful identifier")
    if not name.isascii():
        report.error(path, "non-ASCII name")


# --- Repository ------------------------------------------------------------

def list_repo_files(repo: Path, tracked_only: bool = False) -> list[str]:
    """Return tracked and staged files, plus untracked non-ignored files
    unless tracked_only is set (as in the pre-commit hook)."""
    cmd = ["git", "-C", str(repo), "ls-files", "--cached", "-z"]
    if not tracked_only:
        cmd[4:4] = ["--others", "--exclude-standard"]
    try:
        out = subprocess.run(
            cmd,
            check=True, capture_output=True).stdout
        return sorted({p for p in out.decode().split("\0")
                       if p and (repo / p).exists()})
    except (OSError, subprocess.CalledProcessError):
        pass
    files = []
    for root, dirs, names in os.walk(repo):
        rel_root = Path(root).relative_to(repo)
        dirs[:] = [d for d in dirs
                   if not (rel_root == Path(".") and d in REPO_IGNORED_TOP)
                   and d not in {"__pycache__", ".ipynb_checkpoints",
                                 ".pytest_cache"}]
        files.extend(str((rel_root / n).as_posix()) for n in names
                     if not n.endswith((".pyc", ".swp")))
    return sorted(p[2:] if p.startswith("./") else p for p in files)


def check_repo(repo: Path, report: Report, tracked_only: bool = False) -> None:
    files = [f for f in list_repo_files(repo, tracked_only)
             if PurePosixPath(f).parts[0] not in REPO_IGNORED_TOP]
    dirs = sorted({str(PurePosixPath(*PurePosixPath(f).parts[:i]))
                   for f in files
                   for i in range(1, len(PurePosixPath(f).parts))})

    for req in REPO_REQUIRED:
        if not (repo / req).exists():
            report.error(req, "required path is missing")

    for top in sorted({PurePosixPath(p).parts[0] for p in files}):
        if top not in REPO_TOP:
            report.error(top, "top-level entry not allowed by the contract")

    for path in dirs + files:
        check_name(report, path, PurePosixPath(path).name)

    for d in dirs:
        parent = str(PurePosixPath(d).parent)
        name = PurePosixPath(d).name
        allowed = REPO_CHILDREN.get(parent)
        if allowed is not None and name not in allowed:
            report.error(d, f"directory not allowed under {parent}/")
        if parent == "docs" and name not in DOCS_DIRS:
            report.error(d, "docs/ only allows decisions/ and audits/")
        if d.startswith("workflow/") and name.lower() in LANGUAGE_DIRS:
            report.error(d, "language layer directories are not allowed")
        if d.startswith("workflow/common/"):
            report.error(d, "workflow/common/ must stay flat")
        if parent == "analysis" and not LOWER_ID.match(name):
            report.error(d, "analysis task ID must be lowercase words joined "
                            "by hyphens")
        if parent == "analysis" and f"{d}/README.md" not in files:
            report.error(d, "analysis task has no README.md")

    for f in files:
        p = PurePosixPath(f)
        full = repo / f
        parent = str(p.parent)
        suffix = p.suffix.lower()
        if suffix in DATA_SUFFIXES:
            report.error(f, "data, log, or binary file type is not allowed in "
                            "the repository")
        try:
            size = full.stat().st_size
        except OSError:
            size = 0
        if size > REPO_ERROR_BYTES:
            report.error(f, f"file is {size / 2**20:.1f} MiB; large files "
                            "belong in the workdir")
        elif size > REPO_WARN_BYTES:
            report.warn(f, f"file is {size / 2**20:.1f} MiB")
        allowed = REPO_CHILDREN.get(parent)
        if allowed is not None and p.name not in allowed:
            report.error(f, f"file not allowed directly under {parent}/")
        if parent == "docs" and p.name not in DOCS_FILES:
            report.warn(f, "document not listed in the contract")
        if f.startswith("workflow/"):
            if suffix == ".ipynb":
                report.error(f, "notebooks are not allowed in workflow/")
            if suffix in WORKFLOW_TEXT_SUFFIXES and size <= REPO_ERROR_BYTES:
                text = read_text(full)
                if ANALYSIS_REFERENCE.search(text):
                    report.error(f, "workflow code must not reference "
                                    "analysis/")
                if f.startswith("workflow/common/") and MAIN_GUARD.search(text):
                    report.error(f, "workflow/common/ must not contain entry "
                                    "points")
        if (f.startswith("manifests/") and p.name != "README.md"
                and size <= REPO_ERROR_BYTES
                and MANIFEST_INTERMEDIATE.search(read_text(full))):
            report.error(f, "manifests must not reference intermediate/; "
                            "caches are never inputs or delivered objects")
        if f.startswith("configs/campaigns/") and suffix in {".yaml", ".yml"}:
            if CAMPAIGN_SEGMENTS.search(read_text(full)):
                report.error(f, "campaigns must not list segments by hand")

    claude = repo / "CLAUDE.md"
    if claude.exists() and "@AGENTS.md" not in read_text(claude):
        report.error("CLAUDE.md", "must import AGENTS.md with '@AGENTS.md'")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# --- Workdir ---------------------------------------------------------------

def children(path: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(path) as it:
            return sorted(it, key=lambda e: e.name)
    except OSError:
        return []


def subdirs(path: Path) -> list[os.DirEntry]:
    return [e for e in children(path) if e.is_dir(follow_symlinks=False)]


def check_allowed(report: Report, rel: str, entries, allowed, what: str) -> None:
    for e in entries:
        if e.name not in allowed and e.name != "README.md":
            report.error(f"{rel}/{e.name}", f"not a valid {what}")


def check_id(report: Report, rel: str, name: str, what: str) -> None:
    if not LOWER_ID.match(name):
        report.error(rel, f"{what} must be lowercase words joined by hyphens")


def check_workdir(workdir: Path, repo: Path, report: Report) -> None:
    top = {e.name: e for e in children(workdir)}
    for name in WORKDIR_TOP:
        if name not in top:
            report.error(name, "required workdir directory is missing")
    for name in top:
        if name not in WORKDIR_TOP and name != "README.md":
            report.error(name, "top-level entry not allowed by the contract")

    w = workdir

    # raw/
    check_allowed(report, "raw", children(w / "raw"), {"ISIMIP4b", "external"},
                  "raw source")
    for e in subdirs(w / "raw" / "external"):
        check_id(report, f"raw/external/{e.name}", e.name, "dataset ID")

    check_intermediate(w, repo, report)

    # parameters/{candidates,production}/<set>/<component>
    check_allowed(report, "parameters", children(w / "parameters"),
                  {"candidates", "production"}, "parameter status")
    for status in ("candidates", "production"):
        for pset in subdirs(w / "parameters" / status):
            rel = f"parameters/{status}/{pset.name}"
            check_id(report, rel, pset.name, "parameter-set ID")
            check_allowed(report, rel, subdirs(Path(pset.path)),
                          PARAMETER_COMPONENTS, "parameter component")

    # forcing/
    check_allowed(report, "forcing", children(w / "forcing"),
                  {"climate", "landuse", "water_use"}, "forcing family")
    for gcm in subdirs(w / "forcing" / "climate"):
        rel = f"forcing/climate/{gcm.name}"
        if gcm.name not in GCMS:
            report.error(rel, "unknown GCM; see docs/glossary.md")
        check_allowed(report, rel, subdirs(Path(gcm.path)),
                      CLIMATE_INPUT_ALIASES, "climate-scenario input alias")
    for family in ("landuse", "water_use"):
        check_allowed(report, f"forcing/{family}",
                      subdirs(w / "forcing" / family), SOC_SCENARIOS,
                      "soc scenario")

    # builds/vic/<commit>
    check_allowed(report, "builds", children(w / "builds"), {"vic"}, "build")
    for b in subdirs(w / "builds" / "vic"):
        if not COMMIT_SHA.match(b.name):
            report.error(f"builds/vic/{b.name}",
                         "build directory must be a full 40-character commit")

    # runs/<campaign-id>/<run-id>
    campaigns = repo / "configs" / "campaigns"
    for camp in subdirs(w / "runs"):
        rel = f"runs/{camp.name}"
        check_id(report, rel, camp.name, "campaign ID")
        if not any((campaigns / f"{camp.name}{s}").exists()
                   for s in (".yaml", ".yml")):
            report.warn(rel, "no matching configs/campaigns/<campaign-id>.yaml")
        for run in subdirs(Path(camp.path)):
            rrel = f"{rel}/{run.name}"
            check_run_id(report, rrel, run.name)
            check_allowed(report, rrel, children(Path(run.path)), RUN_CHILDREN,
                          "run entry")
            for chunk in subdirs(Path(run.path) / "chunks"):
                crel = f"{rrel}/chunks/{chunk.name}"
                if not CHUNK_ID.match(chunk.name):
                    report.error(crel, "chunk must be <start-year>-<end-year>")
                check_allowed(report, crel, children(Path(chunk.path)),
                              CHUNK_CHILDREN, "chunk entry")

    # postprocessed/<set>/<gcm>/<experiment-id>/<variable>
    for pset in subdirs(w / "postprocessed"):
        rel = f"postprocessed/{pset.name}"
        check_id(report, rel, pset.name, "product-set ID")
        for gcm in subdirs(Path(pset.path)):
            if gcm.name not in GCMS:
                report.error(f"{rel}/{gcm.name}", "unknown GCM")
            for exp in subdirs(Path(gcm.path)):
                check_experiment_id(report, f"{rel}/{gcm.name}/{exp.name}",
                                    exp.name)

    # qc/<object-type>
    check_allowed(report, "qc", children(w / "qc"), QC_OBJECT_TYPES,
                  "QC object type (must be a workdir top-level name)")

    # delivery/<delivery-id>
    for d in subdirs(w / "delivery"):
        rel = f"delivery/{d.name}"
        check_allowed(report, rel, children(Path(d.path)), DELIVERY_CHILDREN,
                      "delivery entry")

    # analysis/<task-id>
    for task in subdirs(w / "analysis"):
        rel = f"analysis/{task.name}"
        check_id(report, rel, task.name, "analysis task ID")
        if not (repo / "analysis" / task.name / "README.md").exists():
            report.error(rel, "no matching repo/analysis/<task-id>/README.md")

    # logs/<stage>
    check_allowed(report, "logs", children(w / "logs"), set(STAGES),
                  "workflow stage name")

    # scratch/<task-id>
    for task in subdirs(w / "scratch"):
        check_id(report, f"scratch/{task.name}", task.name, "task ID")

    walk_workdir(w, report)


def parse_cache_yaml(text: str) -> dict[str, str]:
    """Map top-level keys to their inline value ('' for block values).

    A deliberately small line-based reader: full YAML semantics and the
    fingerprint are validated by the workflow code that uses the cache.
    """
    keys: dict[str, str] = {}
    for line in text.splitlines():
        m = CACHE_KEY_LINE.match(line)
        if m:
            keys[m.group(1)] = m.group(2).strip().strip("'\"")
    return keys


def block_items(text: str, key: str) -> list[str]:
    """Return '- item' lines that follow a top-level key."""
    items, inside = [], False
    for line in text.splitlines():
        if CACHE_KEY_LINE.match(line):
            inside = line.startswith(f"{key}:")
            continue
        m = re.match(r"^\s+-\s+(.*)$", line)
        if inside and m:
            items.append(m.group(1).strip().strip("'\""))
    return items


def check_intermediate(w: Path, repo: Path, report: Report) -> None:
    base = w / "intermediate"
    seen: dict[str, list[str]] = {}
    for e in children(base):
        if not e.is_dir(follow_symlinks=False) and e.name != "README.md":
            report.error(f"intermediate/{e.name}",
                         "files are not allowed directly in intermediate/")
    for stage in subdirs(base):
        srel = f"intermediate/{stage.name}"
        if stage.name not in STAGES:
            report.error(srel, "must be a full workflow stage name")
        for e in children(Path(stage.path)):
            if not e.is_dir(follow_symlinks=False):
                report.error(f"{srel}/{e.name}", "files are not allowed "
                             "directly in a producer-stage directory")
        for cache in subdirs(Path(stage.path)):
            check_cache(report, repo, Path(cache.path), stage.name,
                        f"{srel}/{cache.name}")
            seen.setdefault(cache.name, []).append(stage.name)
    for cache_id, stages in sorted(seen.items()):
        if len(stages) > 1:
            report.error(f"intermediate/*/{cache_id}", "cache ID is used by "
                         f"several producer stages {stages}; it must be unique")


def check_cache(report: Report, repo: Path, path: Path, stage: str,
                rel: str) -> None:
    name = path.name
    if not CACHE_ID.match(name):
        report.error(rel, "cache ID must use lowercase letters, digits, "
                          "hyphens, and underscores")
    for e in children(path):
        is_dir = e.is_dir(follow_symlinks=False)
        if e.name == "data" and not is_dir:
            report.error(f"{rel}/data", "data must be a directory")
        elif e.name in {"cache.yaml", "_SUCCESS"} and is_dir:
            report.error(f"{rel}/{e.name}", "must be a file")
        elif e.name not in CACHE_ROOT_ENTRIES:
            report.error(f"{rel}/{e.name}", "cache root allows only "
                         "cache.yaml, _SUCCESS, and data/; cached content "
                         "goes into data/")
    success = (path / "_SUCCESS").exists()
    if not success:
        report.warn(rel, "no _SUCCESS; incomplete cache must not be reused")
    elif not (path / "data").is_dir():
        report.warn(rel, "complete cache has no data/ directory")
    yaml_path = path / "cache.yaml"
    if not yaml_path.exists():
        report.error(rel, "cache directory has no cache.yaml")
        return
    text = read_text(yaml_path)
    keys = parse_cache_yaml(text)
    yrel = f"{rel}/cache.yaml"
    missing = [k for k in CACHE_REQUIRED if k not in keys]
    if missing:
        report.error(yrel, f"missing required keys {missing}")
    if "status" in keys:
        report.error(yrel, "'status' is not used; completeness is _SUCCESS")
    if keys.get("cache_id", name) != name:
        report.error(yrel, "cache_id does not match the directory name")
    if keys.get("producer_stage", stage) != stage:
        report.error(yrel, "producer_stage does not match the parent "
                           "directory")
    fp = keys.get("cache_fingerprint")
    if fp is not None and not SHA256.match(fp):
        report.error(yrel, "cache_fingerprint must be a 64-character "
                           "SHA-256")
    created_by = keys.get("created_by")
    if created_by is not None:
        if not created_by.startswith("workflow/"):
            report.error(yrel, "created_by must be a path under workflow/")
        elif not (repo / created_by).is_file():
            report.warn(yrel, f"created_by '{created_by}' no longer exists; "
                              "the cache is stale and will not be reused")
    commit = keys.get("code_commit")
    if commit is not None and not COMMIT_SHA.match(commit):
        report.error(yrel, "code_commit must be a full 40-character commit")
    if "code_dirty" in keys and keys["code_dirty"].lower() != "false":
        report.error(yrel, "code_dirty must be false; outputs of uncommitted "
                           "code belong in scratch/")
    created_at = keys.get("created_at")
    if created_at is not None and not UTC_TIME.match(created_at):
        report.error(yrel, "created_at must be UTC ISO 8601, e.g. "
                           "2026-09-28T14:30:00Z")
    for key, prefix in (("input_manifest", "manifests/inputs/"),
                        ("campaign_config", "configs/campaigns/")):
        ref = keys.get(key)
        if key in keys and not ref:
            report.error(yrel, f"{key} is empty; omit the key when it does "
                               "not apply")
        elif ref and not ref.startswith(prefix):
            report.error(yrel, f"{key} must be under {prefix}")
        elif ref and not (repo / ref).is_file():
            report.error(yrel, f"{key} '{ref}' does not exist in the "
                               "repository")
    inputs = block_items(text, "inputs")
    if "inputs" in keys and not inputs and not keys["inputs"]:
        report.error(yrel, "inputs is empty")
    for item in inputs:
        if item.startswith("/"):
            report.error(yrel, f"input '{item}' must be relative to the "
                               "workdir")
    for item in block_items(text, "final_destination"):
        if item.startswith("/") or item.lstrip("./").startswith(
                "intermediate"):
            report.error(yrel, f"final_destination '{item}' must be a "
                               "workdir path outside intermediate/")


def check_run_id(report: Report, rel: str, name: str) -> None:
    m = RUN_ID.match(name)
    if not m:
        report.error(rel, "run ID must be the segment ID <climate-forcing>_"
                          "<climate-scenario>_<soc-scenario>_<sens-scenario>_"
                          "<period>")
        return
    checks = [("gcm", GCMS), ("climate", CLIMATE_SCENARIOS),
              ("soc", SOC_SCENARIOS), ("sens", SENS_SCENARIOS),
              ("period", PERIODS)]
    for key, valid in checks:
        if m.group(key) not in valid:
            report.error(rel, f"unknown {key} '{m.group(key)}' in run ID")


def check_experiment_id(report: Report, rel: str, name: str) -> None:
    m = EXPERIMENT_ID.match(name)
    if not m:
        report.error(rel, "experiment ID must be <climate-scenario>_"
                          "<soc-scenario>_<sens-scenario>")
        return
    for key, valid in (("climate", CLIMATE_SCENARIOS), ("soc", SOC_SCENARIOS),
                       ("sens", SENS_SCENARIOS)):
        if m.group(key) not in valid:
            report.error(rel, f"unknown {key} '{m.group(key)}' in experiment "
                              "ID")


def code_allowed(parts: tuple[str, ...]) -> bool:
    """Rendered run files and build trees may contain scripts."""
    if parts[0] in {"scratch", "builds"}:
        return True
    return parts[0] == "runs" and "config" in parts


def walk_workdir(workdir: Path, report: Report) -> None:
    """Check names, code files, and empty directories below the top level."""
    stack = [(workdir / name, (name,)) for name in WORKDIR_TOP
             if name not in {"raw", "scratch"}]
    while stack:
        path, parts = stack.pop()
        entries = children(path)
        rel = "/".join(parts)
        if not entries and len(parts) > 1:
            report.warn(rel, "empty directory; create paths only when used")
        for e in entries:
            eparts = parts + (e.name,)
            erel = "/".join(eparts)
            if e.name == "README.md" and len(eparts) == 2:
                continue
            check_name(report, erel, e.name)
            if e.is_dir(follow_symlinks=False):
                if len(eparts) < WORKDIR_MAX_DEPTH:
                    stack.append((Path(e.path), eparts))
            elif (Path(e.name).suffix.lower() in CODE_SUFFIXES
                  and not code_allowed(eparts)):
                report.error(erel, "source code must live in the repository")


# --- Main ------------------------------------------------------------------

def main() -> int:
    repo_default = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=repo_default,
                        help="repository root (default: %(default)s)")
    parser.add_argument("--workdir", nargs="?", const="", default=None,
                        help="also check the workdir; without a value, use "
                             "$ISIMIP4B_WORKDIR or the sibling ../workdir")
    parser.add_argument("--tracked-only", action="store_true",
                        help="ignore untracked files (used by the pre-commit "
                             "hook)")
    parser.add_argument("--quiet", action="store_true",
                        help="print only errors and the summary")
    args = parser.parse_args()

    report = Report()
    repo = args.repo.resolve()
    check_repo(repo, report, args.tracked_only)
    checked = "repository"

    if args.workdir is not None:
        workdir_arg = args.workdir or os.environ.get("ISIMIP4B_WORKDIR", "")
        workdir = Path(workdir_arg) if workdir_arg else repo.parent / "workdir"
        if not workdir.is_dir():
            report.error(str(workdir), "workdir not found; set "
                                       "ISIMIP4B_WORKDIR or pass --workdir")
        else:
            wreport = Report()
            check_workdir(workdir.resolve(), repo, wreport)
            report.errors += [m.replace("ERROR   ", "ERROR   workdir/", 1)
                              for m in wreport.errors]
            report.warnings += [m.replace("WARNING ", "WARNING workdir/", 1)
                                for m in wreport.warnings]
            checked = "repository and workdir"

    for line in report.errors:
        print(line)
    if not args.quiet:
        for line in report.warnings:
            print(line)
    print(f"check_layout: {checked}: {len(report.errors)} error(s), "
          f"{len(report.warnings)} warning(s)")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
