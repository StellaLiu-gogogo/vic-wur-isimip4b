#!/bin/bash
# Slurm job template of stage 06_postprocessing: one producer, then its check. Rendered by submit.py; the rendered
# copy is kept as job.sbatch in the job record logs/06_postprocessing/<job-name>_<slurm-job-id>/. Placeholders are
# upper-case names in double braces. The stage is self-contained and needs no PYTHONPATH.
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
export OMP_NUM_THREADS={{CPUS}}
cd {{REPO}}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD)"

# the producer must succeed before its check runs; the job ends with the exit status of the check
# (passed 0, failed 1, warning 3, not_checked 4)
/usr/bin/time -v python3 workflow/06_postprocessing/{{PRODUCER}}
set +e
/usr/bin/time -v python3 workflow/06_postprocessing/{{CHECK}}
rc=$?
set -e
echo "check exit status $rc"
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit $rc
