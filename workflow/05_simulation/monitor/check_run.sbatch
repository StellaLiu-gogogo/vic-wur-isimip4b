#!/bin/bash
# Slurm job template of the run sanity checks (workflow/05_simulation/monitor/check_run.py). Rendered by
# submit_check.py; the rendered copy is kept as job.sbatch in the job record
# logs/05_simulation/<job-name>_<slurm-job-id>/. Placeholders are upper-case names in double braces.
#SBATCH --job-name={{JOB_NAME}}
#SBATCH --partition={{PARTITION}}
#SBATCH --time={{TIME}}
#SBATCH --cpus-per-task=1
#SBATCH --mem={{MEM}}
#SBATCH --output={{STAGE_LOGS}}/slurm-%j.out
#SBATCH --error={{STAGE_LOGS}}/slurm-%j.err
set -eo pipefail

JOB_DIR={{STAGE_LOGS}}/{{JOB_NAME}}_${SLURM_JOB_ID}
mkdir -p "$JOB_DIR"
mv {{STAGE_LOGS}}/slurm-${SLURM_JOB_ID}.out {{STAGE_LOGS}}/slurm-${SLURM_JOB_ID}.err "$JOB_DIR"/

source {{CONDA_BASE}}/etc/profile.d/conda.sh
conda activate isimip4b
export ISIMIP4B_WORKDIR={{WORKDIR}}
export PYTHONPATH={{REPO}}/workflow
cd {{REPO}}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD)"
/usr/bin/time -v python3 workflow/05_simulation/monitor/check_run.py --run-dir {{RUN_DIR}}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
