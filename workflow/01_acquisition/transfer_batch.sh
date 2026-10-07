#!/usr/bin/env bash
# Pull one approved batch of files from DKRZ levante, verify them, move the verified files into the raw area,
# and write the transfer manifest.
#
# usage: transfer_batch.sh <batch-id> <list-file> <manifest-dir> [ssh-host] [src-root] [dst-root]
#   <batch-id>      label used in log and manifest names, e.g. 5
#   <list-file>     batch_<n>_files.txt from make_batch_lists.py (paths relative to the DKRZ root);
#                   batch_<n>_expected_sizes.tsv must sit next to it
#   <manifest-dir>  where transfer_manifest_batch_<id>.txt and MD5SUMS are written; the accepted
#                   manifest is committed under repo/manifests/inputs/<dataset-id>/
#   [ssh-host]      ssh alias of DKRZ levante (default: levante; key-based login required)
#   [src-root]      remote directory the list paths are relative to (default: /work/bb0820/ISIMIP/ISIMIP4b)
#   [dst-root]      local destination (default: $ISIMIP4B_WORKDIR/raw/ISIMIP4b); for other DKRZ trees use
#                   $ISIMIP4B_WORKDIR/raw/external/<dataset-id>/<dataset-version>
#
# Requires ISIMIP4B_WORKDIR. Files not yet in <dst-root> are transferred into the staging directory
# $ISIMIP4B_WORKDIR/scratch/acquisition-staging/batch-<batch-id>/ (rsync -L follows DKRZ symlinks; --partial keeps
# an interrupted file there, and running the same batch again resumes it). A file is accepted (OK) only when its
# size equals the approved size (expected sizes file) and the remote size, the remote size and mtime are the same
# before and after the transfer, and its md5 equals the remote md5; a staged file is then moved into <dst-root> with
# its path relative to <src-root> (hard link, then removal from staging). Any other file stays out of the raw area,
# and the manifest says why (column reason). Raw files are never overwritten: a file already in <dst-root> is not
# transferred again, only verified; a changed upstream file is a new dataset version. Logs go to
# $ISIMIP4B_WORKDIR/logs/01_acquisition/.
set -uo pipefail
B=${1:?batch id}; LIST=${2:?list file}; MANDIR=${3:?manifest dir}; HOST=${4:-levante}
: "${ISIMIP4B_WORKDIR:?set ISIMIP4B_WORKDIR}"
SRC_ROOT=${5:-/work/bb0820/ISIMIP/ISIMIP4b}
DST=${6:-$ISIMIP4B_WORKDIR/raw/ISIMIP4b}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
LOGDIR=$ISIMIP4B_WORKDIR/logs/01_acquisition
STAGE=$ISIMIP4B_WORKDIR/scratch/acquisition-staging/batch-$B
SIZES=$(dirname "$LIST")/$(basename "$LIST" _files.txt)_expected_sizes.tsv
LOG=$LOGDIR/batch_${B}_rsync_$(date +%F).log
MAN=$MANDIR/transfer_manifest_batch_${B}.txt
TODO=$LOGDIR/batch_${B}_to_transfer.txt
mkdir -p "$DST" "$LOGDIR" "$MANDIR" "$STAGE"
[ -f "$SIZES" ] || { echo "missing $SIZES" >&2; exit 2; }
echo "[$(date -Is)] batch $B start, $(wc -l < "$LIST") files" | tee -a "$LOG"
# 1. remote size and mtime before the transfer
ssh -o BatchMode=yes "$HOST" "cd $SRC_ROOT && stat -L -c '%s %Y %n' \$(cat) 2>&1" < "$LIST" > "$LOGDIR/batch_${B}_remote_stat_before.txt"
# 2. rsync the files not yet in the raw area into staging (follow symlinks, keep relative paths, resumable)
while IFS= read -r p; do [ -n "$p" ] && [ ! -e "$DST/$p" ] && echo "$p"; done < "$LIST" > "$TODO"
rsync -a --partial --files-from="$TODO" -L --info=progress2,stats2 "$HOST:$SRC_ROOT/" "$STAGE/" >> "$LOG" 2>&1
RC=$?; echo "[$(date -Is)] rsync exit $RC ($(wc -l < "$TODO") files to transfer)" | tee -a "$LOG"
# 3. remote size and mtime after the transfer (must be unchanged)
ssh -o BatchMode=yes "$HOST" "cd $SRC_ROOT && stat -L -c '%s %Y %n' \$(cat) 2>&1" < "$LIST" > "$LOGDIR/batch_${B}_remote_stat_after.txt"
# 4. remote md5
ssh -o BatchMode=yes "$HOST" "cd $SRC_ROOT && md5sum \$(cat)" < "$LIST" > "$LOGDIR/batch_${B}_md5_remote.txt" 2>>"$LOG"
# 5. compare, move the accepted staged files into the raw area, write the manifest
PYTHONPATH="$REPO/workflow${PYTHONPATH:+:$PYTHONPATH}" python3 - "$B" "$LOGDIR" "$SRC_ROOT" "$DST" "$STAGE" "$LIST" "$SIZES" "$MAN" "$MANDIR" <<'EOF_PY' 2>&1 | tee -a "$LOG"
import sys, os, datetime
from common import hashing
B, LOGDIR, SRC, DST, STAGE, LIST, SIZES, MAN, MANDIR = sys.argv[1:10]
rem = {l.split()[1]: l.split()[0] for l in open(f'{LOGDIR}/batch_{B}_md5_remote.txt') if len(l.split()) == 2}
def remote_stat(when):
    return {l.split(' ', 2)[2].strip(): (l.split()[0], l.split()[1])
            for l in open(f'{LOGDIR}/batch_{B}_remote_stat_{when}.txt') if len(l.split()) >= 3 and l.split()[0].isdigit()}
before, stat = remote_stat('before'), remote_stat('after')
approved = {l.split('\t')[2]: l.split('\t')[0] for l in open(SIZES)}
link = {l.split('\t')[2]: l.rstrip('\n').split('\t')[3] for l in open(SIZES)}
today = datetime.date.today().isoformat()
ok = bad = missing = 0; lines = []; accepted = []
for p in (l.strip() for l in open(LIST) if l.strip()):
    in_raw = os.path.exists(f'{DST}/{p}')          # accepted earlier: verified again, never replaced
    local = f'{DST}/{p}' if in_raw else f'{STAGE}/{p}'
    r, lcl, size, why = rem.get(p), None, -1, []
    if not os.path.isfile(local):
        st = 'MISSING'; why.append('not transferred')
    else:
        size = os.path.getsize(local); lcl = hashing.md5(local)
        if p not in approved:
            why.append('not in the approved sizes')
        elif int(approved[p]) != size:
            why.append(f'size {size} differs from the approved size {approved[p]}')
        if p not in before or p not in stat:
            why.append('no remote size and mtime')
        elif before[p] != stat[p]:
            why.append(f'remote size and mtime changed during the transfer ({" ".join(before[p])} -> {" ".join(stat[p])})')
        elif int(stat[p][0]) != size:
            why.append(f'size {size} differs from the remote size {stat[p][0]}')
        if not r:
            why.append('no remote md5')
        elif r != lcl:
            why.append('md5 differs from the remote md5')
        st = 'MISMATCH' if why else 'OK'
    if st == 'OK' and not in_raw:                  # move: hard link (never over an existing file), then unstage
        try:
            os.makedirs(os.path.dirname(f'{DST}/{p}'), exist_ok=True)
            os.link(local, f'{DST}/{p}'); os.unlink(local)
        except OSError as e:
            st = 'MISMATCH'; why.append(f'not moved into the raw area: {e}')
    ok += st == 'OK'; bad += st == 'MISMATCH'; missing += st == 'MISSING'
    if st == 'OK':
        accepted.append((p, lcl))
    else:
        print(f'{st} {p}: {"; ".join(why)}')
    mt = datetime.datetime.utcfromtimestamp(int(stat[p][1])).date().isoformat() if p in stat else '-'
    lines.append('\t'.join([st, f'{SRC}/{p}', f'{DST}/{p}', str(size), lcl or '-', r or '-', today,
                            stat.get(p, ('-', '-'))[0], mt, link.get(p, ''), '; '.join(why) or '-']))
with open(MAN, 'w') as fh:
    fh.write('#status\tsource\ttarget\tsize_bytes\tmd5_local\tmd5_remote\ttransfer_date\tremote_size\tremote_mtime\tdkrz_link_target\treason\n')
    fh.write('\n'.join(lines) + '\n')
with open(f'{MANDIR}/MD5SUMS', 'a') as fh:
    for p, m in sorted(accepted):
        fh.write(f'{m}  {p}\n')
tot = sum(int(l.split('\t')[3]) for l in lines if l.startswith('OK'))
print(f'batch {B}: OK={ok} MISMATCH={bad} MISSING={missing} bytes_ok={tot}')
sys.exit(0 if bad == 0 and missing == 0 else 1)
EOF_PY
RC=${PIPESTATUS[0]}
find "$STAGE" -depth -type d -empty -delete    # staging keeps only files that were not accepted
echo "[$(date -Is)] batch $B done, verification exit $RC" | tee -a "$LOG"
exit $RC
