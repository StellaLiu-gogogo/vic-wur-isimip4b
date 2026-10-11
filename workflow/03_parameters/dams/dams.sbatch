#!/bin/bash
# Slurm job template for the dam component producer and verifier (workflow/03_parameters/dams/).
# Rendered by submit_dams.py; the rendered copy is kept as job.sbatch in the job record
# logs/03_parameters/<job-name>_<slurm-job-id>/. Placeholders are upper-case names in double braces.
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

# conda's activation scripts read variables that may be unset (magics: MAGPLUS_HOME), so they run without
# set -u; the job then works also when it is submitted from a shell without the environment
set +u
source {{CONDA_BASE}}/etc/profile.d/conda.sh
conda activate isimip4b
set -u
export ISIMIP4B_WORKDIR={{WORKDIR}}
export PYTHONPATH={{REPO}}/workflow
export OMP_NUM_THREADS=1
cd {{REPO}}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD)"

if [ "{{RUN_PRODUCER}}" = yes ]; then
    /usr/bin/time -v python3 workflow/03_parameters/dams/build_dams.py {{PRODUCER_ARGS}}
fi
if [ "{{RUN_VERIFIER}}" = yes ]; then
    /usr/bin/time -v python3 workflow/03_parameters/dams/verify_dams.py {{VERIFIER_ARGS}}
fi

echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
