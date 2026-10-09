#!/bin/bash
# Slurm job template for the assembled bundle producer and verifier (workflow/03_parameters/bundle/).
# Rendered by submit_bundle.py; the rendered copy is kept as job.sbatch in the job record
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

source {{CONDA_BASE}}/etc/profile.d/conda.sh
conda activate isimip4b
export ISIMIP4B_WORKDIR={{WORKDIR}}
export PYTHONPATH={{REPO}}/workflow
export OMP_NUM_THREADS=1
cd {{REPO}}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD)"

if [ "{{RUN_PRODUCER}}" = yes ]; then
    /usr/bin/time -v python3 workflow/03_parameters/bundle/assemble_bundle.py {{PRODUCER_ARGS}}
fi
/usr/bin/time -v python3 workflow/03_parameters/bundle/verify_bundle.py {{VERIFIER_ARGS}}

echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
