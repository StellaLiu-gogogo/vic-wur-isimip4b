#!/usr/bin/env bash
# Build the VIC-WUR image driver at the commit pinned in model/vic.lock.yaml and
# record it as a build under $ISIMIP4B_WORKDIR/builds/vic/<commit>/.
#
# usage: build_vic.sh [--scratch] [--jobs N] [--git-url URL]
#   --scratch    test run: leave the result under scratch/vic-build/output/<commit>/<build-date>/
#                and never touch builds/ (also the automatic behaviour when the repository is not clean)
#   --jobs N     parallel compile jobs (default 8)
#   --git-url    clone URL when the checkout does not exist yet (default: the SSH form of the
#                repository in model/vic.lock.yaml, git@github.com:<owner>/<name>.git)
#
# Steps
#   1. read model/vic.lock.yaml (never modified here): repository, branch, commit, freeze_status, driver
#   2. clone or reuse the disposable checkout scratch/vic-build/<commit>/, check out exactly <commit>,
#      require a clean work tree, record `git rev-parse HEAD`
#   3. load the Anunna modules of the 2025 bucket (BUCKET/MODULES below) and verify that mpicc and
#      nc-config resolve inside that bucket, not to a conda environment on PATH
#   4. make clean; make vic_image.exe in vic/drivers/image with MPICC, NC_CFLAGS and NC_LIBS passed
#      explicitly; everything is logged under logs/
#   5. copy vic_image.exe to bin/, sha256; run the checks (-v, -o, ldd) into tests/;
#      the VIC test suite (tests/ of the checkout) is skipped: its unit tests need the Python driver
#      (`from vic import lib`), which this fork does not have, and its system tests need the tonic
#      package and the Stehekin sample data submodule (a download); recorded as skipped
#   6. write build_manifest.json; status `built` when -v and -o run (never `tested`, see 5)
#
# Everything is staged under scratch/vic-build/output/<commit>/<build-date>/ and moved to
# builds/vic/<commit>/ only when the build and the checks succeed; a failed build therefore never
# creates builds/vic/<commit>/. An existing builds/vic/<commit>/ is never overwritten: remove it
# yourself (with the user's authorization) before rebuilding the same commit.
#
# Run-time note: the executable is linked against the architecture-specific 2025 tree of the node
# that built it (see cpu_arch in the manifest). Every job that runs it must load the same modules
# (manifest key runtime_modules) so that the node's own tree of the same versions is used.
#
# Requires ISIMIP4B_WORKDIR. No conda environment is needed; the build uses only Anunna modules.
set -euo pipefail

# ---------------------------------------------------------------- settings
BUCKET=2025
MODULES=(netCDF/4.9.3-gompi-2025a)          # pulls in GCC 14.2.0, OpenMPI 5.0.7, HDF5 1.14.6
BUCKET_ROOT=/shared/easybuild/software/noble/$BUCKET
ARCH_SCRIPT=/shared/easybuild/build/archspec/get_arch.py
LMOD_INIT=/etc/profile.d/z00_lmod.sh
JOBS=8
GIT_URL=""
SCRATCH_ONLY=0
SCRIPT_REL=workflow/05_simulation/build/build_vic.sh

while [ $# -gt 0 ]; do
  case "$1" in
    --scratch) SCRATCH_ONLY=1 ;;
    --jobs) JOBS=${2:?--jobs N}; shift ;;
    --git-url) GIT_URL=${2:?--git-url URL}; shift ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

: "${ISIMIP4B_WORKDIR:?set ISIMIP4B_WORKDIR}"
WORKDIR=$ISIMIP4B_WORKDIR
REPO=$(cd "$(dirname "$(readlink -f "$0")")/../../.." && pwd)
LOCK=$REPO/model/vic.lock.yaml
[ -f "$LOCK" ] || { echo "missing $LOCK" >&2; exit 2; }
[ -d "$WORKDIR" ] || { echo "ISIMIP4B_WORKDIR does not exist: $WORKDIR" >&2; exit 2; }

log() { echo "[$(date -u +%FT%TZ)] $*"; }
lock_value() { sed -n "s/^$1:[[:space:]]*\([^#]*\).*/\1/p" "$LOCK" | sed 's/[[:space:]]*$//' | head -1; }

# manifest writer (used by the EXIT trap on failure and at the end); only python3 stdlib
write_manifest() {
  OUT_DIR=$OUT STATUS=$STATUS FAIL_REASON=$FAIL_REASON BUILD_DATE=$BUILD_DATE HOST=${HOST:-$(hostname)} \
  CPU_ARCH=${CPU_ARCH:-} OS_NAME=${OS_NAME:-} MODEL_REPO=$MODEL_REPO GIT_URL=$GIT_URL MODEL_BRANCH=$MODEL_BRANCH \
  MODEL_COMMIT=$MODEL_COMMIT HEAD_SHA=${HEAD_SHA:-} BRANCH_HAS_COMMIT=${BRANCH_HAS_COMMIT:-} \
  MODEL_COMMIT_DATE=$MODEL_COMMIT_DATE CHECKOUT_COMMIT_DATE=${CHECKOUT_COMMIT_DATE:-} FREEZE_STATUS=$FREEZE_STATUS \
  BUILD_KIND=$BUILD_KIND SRC=${SRC:-} DRIVER_DIR=${DRIVER_DIR:-} BUCKET=$BUCKET MODULES_LOADED="${MODULES[*]}" \
  BUCKET_ROOT=$BUCKET_ROOT MPICC=${MPICC:-} MPICC_VERSION=${MPICC_VERSION:-} MPICC_SHOW=${MPICC_SHOW:-} \
  MPI_VERSION=${MPI_VERSION:-} GCC_PATH=${GCC_PATH:-} NC_CONFIG=${NC_CONFIG:-} NC_VERSION=${NC_VERSION:-} \
  NC_PREFIX=${NC_PREFIX:-} NC_CFLAGS=${NC_CFLAGS:-} NC_LIBS=${NC_LIBS:-} NC_HAS_NC4=${NC_HAS_NC4:-} \
  NC_HAS_PARALLEL=${NC_HAS_PARALLEL:-} BUILD_CMD=${BUILD_CMD:-} JOBS=$JOBS BUILD_SECONDS=${BUILD_SECONDS:-} \
  WARNINGS=${WARNINGS:-} CODE_COMMIT=$CODE_COMMIT CODE_DIRTY=$CODE_DIRTY SCRIPT_REL=$SCRIPT_REL \
  EXE_SHA=${EXE_SHA:-} EXE_SIZE=${EXE_SIZE:-} VIC_VERSION_LINE=${VIC_VERSION_LINE:-} VIC_GIT_TAG=${VIC_GIT_TAG:-} \
  VERSION_RC=${VERSION_RC:-} OPTIONS_RC=${OPTIONS_RC:-} LDD_RC=${LDD_RC:-} LDD_OK=${LDD_OK:-} \
  TO_SCRATCH=$TO_SCRATCH FINAL=$FINAL SCRATCH_ONLY=$SCRATCH_ONLY \
  python3 - <<'PY'
import json, os, pathlib
e = os.environ
def num(k):
    v = e.get(k, "")
    return int(v) if v.lstrip("-").isdigit() else None
def flag(k):
    return {"true": True, "false": False}.get(e.get(k, ""), None)
out = pathlib.Path(e["OUT_DIR"])
def listing(sub):
    d = out / sub
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []
checks_ran = e["STATUS"] in ("built", "tested")
m = {
    "schema": "isimip4b-vic-build-manifest-1",
    "status": e["STATUS"],
    "status_note": ("built: the executable runs -v and -o and links to the recorded toolchain; "
                    "tested is reserved for a build whose VIC test suite ran and passed"),
    "failure_reason": e["FAIL_REASON"] or None,
    "build_kind": e["BUILD_KIND"],
    "build_date": e["BUILD_DATE"],
    "host": e["HOST"],
    "cpu_arch": e["CPU_ARCH"] or None,
    "os": e["OS_NAME"] or None,
    "model": {
        "lock_file": "model/vic.lock.yaml",
        "repository": e["MODEL_REPO"],
        "clone_url": e["GIT_URL"],
        "branch": e["MODEL_BRANCH"],
        "branch_contains_commit": flag("BRANCH_HAS_COMMIT"),
        "model_commit": e["MODEL_COMMIT"],
        "checkout_head": e["HEAD_SHA"] or None,
        "commit_date_lock": e["MODEL_COMMIT_DATE"],
        "commit_date_git": e["CHECKOUT_COMMIT_DATE"] or None,
        "driver": "image",
        "freeze_status": e["FREEZE_STATUS"],
        "checkout_path": e["SRC"],
    },
    "environment": {
        "module_bucket": e["BUCKET"],
        "modules_loaded_explicitly": e["MODULES_LOADED"].split(),
        "module_list_file": "logs/module_list.txt",
        "bucket_root": e["BUCKET_ROOT"],
        "mpicc": e["MPICC"] or None,
        "mpicc_version": e["MPICC_VERSION"] or None,
        "mpicc_show": e["MPICC_SHOW"] or None,
        "mpi": e["MPI_VERSION"] or None,
        "gcc": e["GCC_PATH"] or None,
        "nc_config": e["NC_CONFIG"] or None,
        "netcdf_version": e["NC_VERSION"] or None,
        "netcdf_prefix": e["NC_PREFIX"] or None,
        "netcdf_has_nc4": e["NC_HAS_NC4"] or None,
        "netcdf_has_parallel": e["NC_HAS_PARALLEL"] or None,
        "nc_cflags": e["NC_CFLAGS"] or None,
        "nc_libs": e["NC_LIBS"] or None,
        "conda_environment_used": None,
    },
    "runtime_modules": [e["BUCKET"]] + e["MODULES_LOADED"].split(),
    "runtime_note": ("Load runtime_modules in every job that runs the executable; the 2025 bucket selects "
                     "the CPU-architecture tree of the running node (same library versions)."),
    "build": {
        "build_dir": e["DRIVER_DIR"] or None,
        "build_command": e["BUILD_CMD"] or None,
        "preceded_by": "make clean",
        "jobs": num("JOBS"),
        "duration_seconds": num("BUILD_SECONDS"),
        "compiler_warning_lines": num("WARNINGS"),
        "build_log": "logs/build.log",
    },
    "workflow": {
        "script": e["SCRIPT_REL"],
        "code_commit": e["CODE_COMMIT"],
        "code_dirty": flag("CODE_DIRTY"),
        "scratch_run": e["TO_SCRATCH"] == "1",
        "scratch_flag": e["SCRATCH_ONLY"] == "1",
        "recorded_location": (e["FINAL"] if e["TO_SCRATCH"] == "0" else str(out)),
    },
    "executable": {
        "path": "bin/vic_image.exe",
        "sha256": e["EXE_SHA"] or None,
        "size_bytes": num("EXE_SIZE"),
        "vic_version": e["VIC_VERSION_LINE"] or None,
        "vic_git_tag": e["VIC_GIT_TAG"] or None,
    },
    "tests": {
        "version": {"command": "vic_image.exe -v", "exit_code": num("VERSION_RC"),
                    "passed": num("VERSION_RC") == 0, "output": "tests/version.txt"},
        "compile_options": {"command": "vic_image.exe -o", "exit_code": num("OPTIONS_RC"),
                            "passed": num("OPTIONS_RC") == 0, "output": "tests/compile_options.txt"},
        "ldd": {"command": "ldd vic_image.exe", "exit_code": num("LDD_RC"), "passed": flag("LDD_OK"),
                "criterion": "libnetcdf, libhdf5 and libmpi resolve inside the module bucket; nothing 'not found'",
                "output": "tests/ldd.txt"},
        "vic_test_suite": {
            "status": "skipped",
            "reason": ("tests/unit needs the VIC Python driver (from vic import lib), absent in this fork; "
                       "tests/system needs the tonic package and the Stehekin sample data submodule "
                       "(samples/data, a download)"),
        },
        "files": listing("tests"),
    },
    "logs": listing("logs"),
}
(out / "build_manifest.json").write_text(json.dumps(m, indent=2) + "\n")
PY
}

# ---------------------------------------------------------------- 1. lock file
MODEL_REPO=$(lock_value repository)
MODEL_BRANCH=$(lock_value branch)
MODEL_COMMIT=$(lock_value commit)
MODEL_COMMIT_DATE=$(lock_value commit_date)
MODEL_DRIVER=$(lock_value driver)
FREEZE_STATUS=$(lock_value freeze_status)
[[ "$MODEL_COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "lock commit is not a full SHA: '$MODEL_COMMIT'" >&2; exit 2; }
[ "$MODEL_DRIVER" = image ] || { echo "lock driver is '$MODEL_DRIVER'; this script builds the image driver" >&2; exit 2; }
case "$FREEZE_STATUS" in
  frozen) BUILD_KIND=production ;;
  provisional) BUILD_KIND=candidate ;;
  *) echo "unknown freeze_status '$FREEZE_STATUS'" >&2; exit 2 ;;
esac
if [ -z "$GIT_URL" ]; then
  GIT_URL=$(echo "$MODEL_REPO" | sed -E 's#^https?://github\.com/([^/]+)/([^/.]+)(\.git)?/?$#git@github.com:\1/\2.git#')
fi

# ---------------------------------------------------------------- workflow code state
CODE_COMMIT=$(git -C "$REPO" rev-parse HEAD)
CODE_DIRTY=false
[ -z "$(git -C "$REPO" status --porcelain)" ] || CODE_DIRTY=true

# ---------------------------------------------------------------- output locations
BUILD_DATE=$(date -u +%FT%TZ)
FINAL=$WORKDIR/builds/vic/$MODEL_COMMIT
STAGE=$WORKDIR/scratch/vic-build/output/$MODEL_COMMIT/$(date -u -d "$BUILD_DATE" +%Y%m%dT%H%M%SZ)
TO_SCRATCH=$SCRATCH_ONLY
if [ "$CODE_DIRTY" = true ] && [ "$SCRATCH_ONLY" = 0 ]; then
  log "repository is not clean (rule 14): the build stays under scratch and is not recorded under builds/"
  TO_SCRATCH=1
fi
if [ "$TO_SCRATCH" = 0 ] && [ -e "$FINAL" ]; then
  echo "refusing to overwrite the existing build $FINAL (remove it with authorization, or use --scratch)" >&2
  exit 3
fi
mkdir -p "$STAGE"/{bin,logs,tests}
OUT=$STAGE
exec > >(tee -a "$OUT/logs/build_vic.log") 2>&1
log "build_vic.sh: model $MODEL_COMMIT ($FREEZE_STATUS, $BUILD_KIND build); workflow $CODE_COMMIT dirty=$CODE_DIRTY"
log "staging under $OUT"
STATUS=failed
FAIL_REASON=""
trap 'rc=$?; if [ $rc -ne 0 ] && [ "$STATUS" = failed ]; then FAIL_REASON=${FAIL_REASON:-"exit status $rc"}; write_manifest || true; log "FAILED: $FAIL_REASON (evidence: $OUT)"; fi' EXIT

# ---------------------------------------------------------------- 2. checkout
SRC=$WORKDIR/scratch/vic-build/$MODEL_COMMIT
if [ ! -d "$SRC/.git" ]; then
  log "cloning $GIT_URL into $SRC"
  git clone --no-checkout "$GIT_URL" "$SRC"
fi
if ! git -C "$SRC" cat-file -e "$MODEL_COMMIT^{commit}" 2>/dev/null; then
  log "commit not present locally; fetching from origin"
  git -C "$SRC" fetch origin
fi
git -C "$SRC" -c advice.detachedHead=false checkout --detach "$MODEL_COMMIT"
HEAD_SHA=$(git -C "$SRC" rev-parse HEAD)
[ "$HEAD_SHA" = "$MODEL_COMMIT" ] || { FAIL_REASON="checkout HEAD $HEAD_SHA != $MODEL_COMMIT"; exit 4; }
if [ -n "$(git -C "$SRC" status --porcelain)" ]; then
  git -C "$SRC" status --porcelain
  FAIL_REASON="checkout $SRC is not clean"; exit 4
fi
BRANCH_HAS_COMMIT=false
git -C "$SRC" merge-base --is-ancestor "$MODEL_COMMIT" "origin/$MODEL_BRANCH" 2>/dev/null && BRANCH_HAS_COMMIT=true
CHECKOUT_COMMIT_DATE=$(git -C "$SRC" log -1 --format=%cI HEAD)
log "checkout at $HEAD_SHA (committed $CHECKOUT_COMMIT_DATE; on origin/$MODEL_BRANCH: $BRANCH_HAS_COMMIT)"

# ---------------------------------------------------------------- 3. modules
set +u   # Lmod's own scripts reference unset variables
if ! type module >/dev/null 2>&1; then
  [ -f "$LMOD_INIT" ] || { FAIL_REASON="no module command and no $LMOD_INIT"; exit 5; }
  # shellcheck disable=SC1090
  source "$LMOD_INIT"
fi
module purge >/dev/null 2>&1 || true
module load "$BUCKET" || { FAIL_REASON="module load $BUCKET failed"; exit 5; }
module load "${MODULES[@]}" || { FAIL_REASON="module load ${MODULES[*]} failed"; exit 5; }
set -u
module -t list 2>&1 | grep -v '^$' > "$OUT/logs/module_list.txt"
MPICC=$(command -v mpicc || true)
NC_CONFIG=$(command -v nc-config || true)
for pair in "mpicc:$MPICC" "nc-config:$NC_CONFIG"; do
  name=${pair%%:*}; path=${pair#*:}
  [ -n "$path" ] || { FAIL_REASON="$name not found after loading the modules"; exit 5; }
  case "$path" in
    "$BUCKET_ROOT"/*) ;;
    *) FAIL_REASON="$name resolves to $path, outside the $BUCKET bucket ($BUCKET_ROOT); check PATH (conda?)"; exit 5 ;;
  esac
done
NC_CFLAGS=$("$NC_CONFIG" --cflags)
NC_LIBS=$("$NC_CONFIG" --libs)
NC_VERSION=$("$NC_CONFIG" --version)
NC_PREFIX=$("$NC_CONFIG" --prefix)
NC_HAS_NC4=$("$NC_CONFIG" --has-nc4)
NC_HAS_PARALLEL=$("$NC_CONFIG" --has-parallel)
MPICC_VERSION=$("$MPICC" --version | head -1)
MPICC_SHOW=$("$MPICC" -show)
MPI_VERSION=$(ompi_info --version 2>/dev/null | head -1 || mpichversion 2>/dev/null | head -1 || echo unknown)
GCC_PATH=$(command -v gcc)
CPU_ARCH=$([ -x "$ARCH_SCRIPT" ] && "$ARCH_SCRIPT" 2>/dev/null || echo unknown)
HOST=$(hostname)
OS_NAME=$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -sr)
{
  echo "host: $HOST"; echo "cpu_arch: $CPU_ARCH"; echo "os: $OS_NAME"; echo "kernel: $(uname -r)"
  echo "cpu: $(lscpu | sed -n 's/^Model name:[[:space:]]*//p')"
  echo "mpicc: $MPICC"; echo "mpicc_version: $MPICC_VERSION"; echo "mpicc_show: $MPICC_SHOW"; echo "mpi: $MPI_VERSION"
  echo "gcc: $GCC_PATH"; echo "nc_config: $NC_CONFIG"; echo "netcdf: $NC_VERSION ($NC_PREFIX)"
  echo "nc_cflags: $NC_CFLAGS"; echo "nc_libs: $NC_LIBS"; echo "has_nc4: $NC_HAS_NC4"; echo "has_parallel: $NC_HAS_PARALLEL"
  echo "PATH: $PATH"; echo "LD_LIBRARY_PATH: ${LD_LIBRARY_PATH:-}"
} > "$OUT/logs/environment.txt"
"$NC_CONFIG" --all > "$OUT/logs/nc_config_all.txt" 2>&1 || true
log "toolchain: $MPICC_VERSION; $MPI_VERSION; $NC_VERSION; arch $CPU_ARCH"

# ---------------------------------------------------------------- 4. build
DRIVER_DIR=$SRC/vic/drivers/image
BUILD_CMD="make -j $JOBS vic_image.exe MPICC=$MPICC NC_CFLAGS='$NC_CFLAGS' NC_LIBS='$NC_LIBS'"
log "make clean in $DRIVER_DIR"
make -C "$DRIVER_DIR" clean > "$OUT/logs/make_clean.log" 2>&1
log "$BUILD_CMD"
BUILD_START=$(date +%s)
if ! ( cd "$DRIVER_DIR" && make -j "$JOBS" vic_image.exe MPICC="$MPICC" NC_CFLAGS="$NC_CFLAGS" NC_LIBS="$NC_LIBS" ) > "$OUT/logs/build.log" 2>&1; then
  tail -30 "$OUT/logs/build.log"
  FAIL_REASON="make failed (logs/build.log)"; exit 6
fi
BUILD_SECONDS=$(( $(date +%s) - BUILD_START ))
WARNINGS=$(grep -c 'warning:' "$OUT/logs/build.log" || true)
[ -x "$DRIVER_DIR/vic_image.exe" ] || { FAIL_REASON="make succeeded but vic_image.exe is missing"; exit 6; }
log "build finished in ${BUILD_SECONDS}s with $WARNINGS compiler warning lines"

# ---------------------------------------------------------------- 5. executable and checks
EXE=$OUT/bin/vic_image.exe
cp "$DRIVER_DIR/vic_image.exe" "$EXE"
chmod 755 "$EXE"
EXE_SHA=$(sha256sum "$EXE" | cut -d' ' -f1)
EXE_SIZE=$(stat -c %s "$EXE")
echo "$EXE_SHA  bin/vic_image.exe" > "$OUT/bin/vic_image.exe.sha256"
git -C "$SRC" describe --abbrev=4 --dirty --always --tags > "$OUT/tests/git_describe.txt"

run_check() {  # name, args...: run the executable, keep stdout+stderr and the exit code
  local name=$1; shift
  local rc=0
  "$EXE" "$@" > "$OUT/tests/$name.txt" 2>&1 || rc=$?
  echo "$rc" > "$OUT/tests/$name.rc"
  return $rc
}
VERSION_RC=0; run_check version -v || VERSION_RC=$?
OPTIONS_RC=0; run_check compile_options -o || OPTIONS_RC=$?
LDD_RC=0; ldd "$EXE" > "$OUT/tests/ldd.txt" 2>&1 || LDD_RC=$?
LDD_OK=true
grep -E 'libnetcdf|libhdf5|libmpi' "$OUT/tests/ldd.txt" | grep -v "=> $BUCKET_ROOT/" > /dev/null && LDD_OK=false
grep -q 'not found' "$OUT/tests/ldd.txt" && LDD_OK=false
VIC_VERSION_LINE=$(sed -n 's/^VIC Version[[:space:]]*:[[:space:]]*//p' "$OUT/tests/version.txt" | head -1)
VIC_GIT_TAG=$(sed -n 's/^VIC Git Tag[[:space:]]*:[[:space:]]*//p' "$OUT/tests/version.txt" | head -1)
log "checks: -v rc=$VERSION_RC, -o rc=$OPTIONS_RC, ldd ok=$LDD_OK; VIC version '$VIC_VERSION_LINE' tag '$VIC_GIT_TAG'"
if [ "$VERSION_RC" -eq 0 ] && [ "$OPTIONS_RC" -eq 0 ] && [ "$LDD_OK" = true ]; then
  STATUS=built
else
  FAIL_REASON="executable checks failed (-v rc=$VERSION_RC, -o rc=$OPTIONS_RC, ldd ok=$LDD_OK)"
fi
make -C "$DRIVER_DIR" clean > /dev/null 2>&1 || true   # leave the checkout without build products

# ---------------------------------------------------------------- 6. manifest
write_manifest
[ "$STATUS" = built ] || exit 7

# ---------------------------------------------------------------- record
if [ "$TO_SCRATCH" = 1 ]; then
  log "DONE ($STATUS), scratch run: result left under $OUT"
else
  mkdir -p "$(dirname "$FINAL")"
  [ -e "$FINAL" ] && { FAIL_REASON="$FINAL appeared during the build"; STATUS=failed; exit 3; }
  mv "$STAGE" "$FINAL"
  OUT=$FINAL
  rmdir "$(dirname "$STAGE")" 2>/dev/null || true
  log "DONE ($STATUS): recorded under $FINAL"
fi
echo "sha256 $EXE_SHA  $OUT/bin/vic_image.exe"
