#!/bin/bash
# Slurm job template of a backup snapshot (workflow/09_backup/backup_snapshot.py --run or --dry-run). Rendered by
# submit_backup.py; the rendered copy is kept as job.sbatch in the job record logs/09_backup/<job-name>_<slurm-job-id>/.
# Placeholders are upper-case names in double braces.
#SBATCH --job-name={{JOB_NAME}}
#SBATCH --partition={{PARTITION}}
#SBATCH --time={{TIME}}
#SBATCH --cpus-per-task={{CPUS}}
#SBATCH --mem={{MEM}}
#SBATCH --output={{STAGE_LOGS}}/slurm-%j.out
#SBATCH --error={{STAGE_LOGS}}/slurm-%j.err
set -euo pipefail

# move the scheduler output into the job record (the open files follow the rename)
JOB_DIR={{STAGE_LOGS}}/{{JOB_NAME}}_${SLURM_JOB_ID}
mkdir -p "$JOB_DIR"
mv {{STAGE_LOGS}}/slurm-${SLURM_JOB_ID}.out {{STAGE_LOGS}}/slurm-${SLURM_JOB_ID}.err "$JOB_DIR"/

# conda's activation scripts read variables that may be unset, so they run without set -u
set +u
source {{CONDA_BASE}}/etc/profile.d/conda.sh
conda activate isimip4b
set -u
export ISIMIP4B_WORKDIR={{WORKDIR}}
export ISIMIP4B_BACKUP={{BACKUP}}
export PYTHONPATH={{REPO}}/workflow
cd {{REPO}}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD)"

/usr/bin/time -v python3 workflow/09_backup/backup_snapshot.py {{ARGS}}

echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
