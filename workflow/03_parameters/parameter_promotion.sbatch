#!/bin/bash
# Slurm job template for the promotion of a parameter set from parameters/candidates/ to parameters/production/
# (workflow/03_parameters/promote_parameter_set.py, then verify_parameter_promotion.py). Rendered by
# submit_parameter_promotion.py; the rendered copy is kept as job.sbatch in the job record
# logs/03_parameters/<job-name>_<slurm-job-id>/. Placeholders are upper-case names in double braces.
#SBATCH --job-name={{JOB_NAME}}
#SBATCH --partition={{PARTITION}}
#SBATCH --time={{TIME}}
#SBATCH --cpus-per-task=1
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
cd {{REPO}}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD)"

/usr/bin/time -v python3 workflow/03_parameters/promote_parameter_set.py {{PROMOTER_ARGS}}
/usr/bin/time -v python3 workflow/03_parameters/verify_parameter_promotion.py {{VERIFIER_ARGS}}

echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
