#!/bin/bash
# Scheduled backup snapshot (docs/directory-contracts.md "Data protection", D13). The user's scrontab runs this
# script on the 1st and the 15th of each month at 02:00 UTC as a small Slurm job; it submits the snapshot job with
# its job record through submit_backup.py, under the user's standing approval of the D13 rules (2026-11-02).
# Any argument is passed on to submit_backup.py (e.g. --dry-run prints the job without submitting it).
#
# scrontab entry (scrontab -e; the two variables are the ones of environments/README.md):
#   #SCRON --partition=main --time=00:10:00 --cpus-per-task=1 --mem=1G --job-name=backup-schedule
#   #SCRON --output=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir/logs/09_backup/scrontab-%j.out
#   0 2 1,15 * * ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir ISIMIP4B_BACKUP=/lustre/backup/WUR/ESG/liu297/isimip4b /lustre/nobackup/WUR/ESG/liu297/isimip4b/repo/workflow/09_backup/scheduled_backup.sh
set -euo pipefail
: "${ISIMIP4B_WORKDIR:?set ISIMIP4B_WORKDIR}"
: "${ISIMIP4B_BACKUP:?set ISIMIP4B_BACKUP}"
REPO=$(cd "$(dirname "$0")/../.." && pwd)
# a scheduled job starts with a minimal environment: the conda installation and Slurm's commands are added here
export CONDA_EXE=${CONDA_EXE:-$HOME/miniconda3/bin/conda}
CONDA_BASE=$(dirname "$(dirname "$CONDA_EXE")")
export PATH=$CONDA_BASE/envs/isimip4b/bin:$CONDA_BASE/bin:/shared/apps/slurm/current/bin:$PATH
export PYTHONPATH=$REPO/workflow
cd "$REPO"
echo "scheduled backup $(date -u +%Y-%m-%dT%H:%M:%SZ) host $(hostname) commit $(git rev-parse --short HEAD)"
exec python3 workflow/09_backup/submit_backup.py \
  --approved "user, 2026-11-02 (standing approval of the D13 rules; scheduled snapshot)" "$@"
