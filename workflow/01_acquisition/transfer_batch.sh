#!/usr/bin/env bash
# Pull one approved batch of ISIMIP4b files from DKRZ levante into the raw area,
# verify sizes and md5 on both ends, and write the transfer manifest.
#
# usage: transfer_batch.sh <batch-id> <list-file> <manifest-dir> [ssh-host]
#   <batch-id>      label used in log and manifest names, e.g. 5
#   <list-file>     batch_<n>_files.txt from make_batch_lists.py (paths relative to the DKRZ root);
#                   batch_<n>_expected_sizes.tsv must sit next to it
#   <manifest-dir>  where transfer_manifest_batch_<id>.txt and MD5SUMS are written; the accepted
#                   manifest is committed under repo/manifests/inputs/<dataset-id>/
#   [ssh-host]      ssh alias of DKRZ levante (default: levante; key-based login required)
#
# Requires ISIMIP4B_WORKDIR. Files land unchanged under $ISIMIP4B_WORKDIR/raw/ISIMIP4b/
# with their DKRZ relative path (rsync -L follows DKRZ symlinks). Logs go to
# $ISIMIP4B_WORKDIR/logs/01_acquisition/. Existing files are never overwritten
# (rsync --ignore-existing): a changed upstream file is a new dataset version.
set -uo pipefail
B=${1:?batch id}; LIST=${2:?list file}; MANDIR=${3:?manifest dir}; HOST=${4:-levante}
: "${ISIMIP4B_WORKDIR:?set ISIMIP4B_WORKDIR}"
SRC_ROOT=/work/bb0820/ISIMIP/ISIMIP4b
DST=$ISIMIP4B_WORKDIR/raw/ISIMIP4b
LOGDIR=$ISIMIP4B_WORKDIR/logs/01_acquisition
SIZES=$(dirname "$LIST")/$(basename "$LIST" _files.txt)_expected_sizes.tsv
LOG=$LOGDIR/batch_${B}_rsync_$(date +%F).log
MAN=$MANDIR/transfer_manifest_batch_${B}.txt
mkdir -p "$DST" "$LOGDIR" "$MANDIR"
[ -f "$SIZES" ] || { echo "missing $SIZES" >&2; exit 2; }
echo "[$(date -Is)] batch $B start, $(wc -l < "$LIST") files" | tee -a "$LOG"
# 1. remote size and mtime before the transfer
ssh -o BatchMode=yes "$HOST" "cd $SRC_ROOT && stat -L -c '%s %Y %n' \$(cat) 2>&1" < "$LIST" > "$LOGDIR/batch_${B}_remote_stat_before.txt"
# 2. rsync (follow symlinks, keep relative paths, resumable, never overwrite)
rsync -a --partial --ignore-existing --files-from="$LIST" -L --info=progress2,stats2 "$HOST:$SRC_ROOT/" "$DST/" >> "$LOG" 2>&1
RC=$?; echo "[$(date -Is)] rsync exit $RC" | tee -a "$LOG"
# 3. remote size and mtime after the transfer (must be unchanged)
ssh -o BatchMode=yes "$HOST" "cd $SRC_ROOT && stat -L -c '%s %Y %n' \$(cat) 2>&1" < "$LIST" > "$LOGDIR/batch_${B}_remote_stat_after.txt"
if ! diff -q "$LOGDIR/batch_${B}_remote_stat_before.txt" "$LOGDIR/batch_${B}_remote_stat_after.txt" >/dev/null; then
  echo "[$(date -Is)] WARNING: remote sizes/mtimes changed during transfer" | tee -a "$LOG"
fi
# 4. md5 on both ends
ssh -o BatchMode=yes "$HOST" "cd $SRC_ROOT && md5sum \$(cat)" < "$LIST" > "$LOGDIR/batch_${B}_md5_remote.txt" 2>>"$LOG"
( cd "$DST" && md5sum $(cat "$LIST") ) > "$LOGDIR/batch_${B}_md5_local.txt" 2>>"$LOG"
# 5. compare and write the manifest
python3 - "$B" "$LOGDIR" "$SRC_ROOT" "$DST" "$LIST" "$SIZES" "$MAN" "$MANDIR" <<'EOF_PY'
import sys, os, datetime
B, LOGDIR, SRC, DST, LIST, SIZES, MAN, MANDIR = sys.argv[1:9]
rem = {l.split()[1]: l.split()[0] for l in open(f'{LOGDIR}/batch_{B}_md5_remote.txt') if len(l.split()) == 2}
loc = {l.split()[1]: l.split()[0] for l in open(f'{LOGDIR}/batch_{B}_md5_local.txt') if len(l.split()) == 2}
stat = {l.split(' ', 2)[2].strip(): (l.split()[0], l.split()[1]) for l in open(f'{LOGDIR}/batch_{B}_remote_stat_after.txt') if len(l.split()) >= 3}
link = {l.split('\t')[2]: l.rstrip('\n').split('\t')[3] for l in open(SIZES)}
today = datetime.date.today().isoformat()
ok = bad = missing = 0; lines = []
for p in (l.strip() for l in open(LIST) if l.strip()):
    r, lcl = rem.get(p), loc.get(p)
    size = os.path.getsize(f'{DST}/{p}') if os.path.exists(f'{DST}/{p}') else -1
    st = 'OK' if r and lcl and r == lcl else ('MISSING' if not lcl else 'MISMATCH')
    ok += st == 'OK'; bad += st == 'MISMATCH'; missing += st == 'MISSING'
    mt = datetime.datetime.utcfromtimestamp(int(stat[p][1])).date().isoformat() if p in stat else '-'
    lines.append('\t'.join([st, f'{SRC}/{p}', f'{DST}/{p}', str(size), lcl or '-', r or '-', today,
                            stat.get(p, ('-', '-'))[0], mt, link.get(p, '')]))
with open(MAN, 'w') as fh:
    fh.write('#status\tsource\ttarget\tsize_bytes\tmd5_local\tmd5_remote\ttransfer_date\tremote_size\tremote_mtime\tdkrz_link_target\n')
    fh.write('\n'.join(lines) + '\n')
with open(f'{MANDIR}/MD5SUMS', 'a') as fh:
    for p, m in sorted(loc.items()):
        if p in rem and rem[p] == m: fh.write(f'{m}  {p}\n')
tot = sum(int(l.split('\t')[3]) for l in lines if l.startswith('OK'))
print(f'batch {B}: OK={ok} MISMATCH={bad} MISSING={missing} bytes_ok={tot}')
sys.exit(0 if bad == 0 and missing == 0 else 1)
EOF_PY
RC=$?
echo "[$(date -Is)] batch $B done, verification exit $RC" | tee -a "$LOG"
exit $RC
