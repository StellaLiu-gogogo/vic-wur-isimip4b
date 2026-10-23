#!/bin/bash
# Slurm job template for the verifiers of the adopted components domain, routing, irrigation and water_use
# (workflow/03_parameters/{domain,routing,irrigation,water_use}/). Rendered by domain/submit_adopted_qc.py; the
# rendered copy is kept as job.sbatch in the job record logs/03_parameters/<job-name>_<slurm-job-id>/. Placeholders
# are upper-case names in double braces.
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
export OMP_NUM_THREADS=1
cd {{REPO}}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD)"

# every verifier runs, whatever the others found; the job ends with the worst status
# (verifier exit status: passed 0, failed 1, warning 3, not_checked 4; anything else counts as failed)
worst=0
for c in {{COMPONENTS}}; do
    set +e
    /usr/bin/time -v python3 workflow/03_parameters/$c/verify_$c.py {{VERIFIER_ARGS}}
    rc=$?
    set -e
    echo "verify_$c exit status $rc"
    case $rc in
        0) ;;
        3) [ $worst -eq 0 ] && worst=3 ;;
        4) [ $worst -ne 1 ] && worst=4 ;;
        *) worst=1 ;;
    esac
done

echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit $worst
