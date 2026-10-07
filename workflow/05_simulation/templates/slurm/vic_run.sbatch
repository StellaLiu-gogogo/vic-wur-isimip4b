#!/bin/bash
# Slurm job template of one VIC-WUR run (workflow/05_simulation/). Rendered by render/render_run.py into
# runs/<campaign-id>/<run-id>/config/job.sbatch; submitted by submit/submit_run.py. Placeholders are upper-case
# names in double braces. Steps: input checksums (run_manifest.py verify-inputs), VIC, run manifest completion
# (run_manifest.py complete), which also runs when VIC fails.
#SBATCH --job-name={{JOB_NAME}}
#SBATCH --partition={{PARTITION}}
#SBATCH --nodes={{NODES}}
#SBATCH --ntasks={{NTASKS}}
#SBATCH --cpus-per-task={{CPUS_PER_TASK}}
#SBATCH --mem={{MEM}}
#SBATCH --time={{TIME}}
{{SCHEDULER_LINES}}
#SBATCH --output={{RUN_DIR}}/logs/slurm-%j.out
#SBATCH --error={{RUN_DIR}}/logs/slurm-%j.err
set -uo pipefail

RUN_DIR={{RUN_DIR}}
echo "run {{RUN_ID}} (campaign {{CAMPAIGN_ID}}) job ${SLURM_JOB_ID} host $(hostname) start $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# python environment for the manifest steps (conda's activation scripts are not safe under set -u)
set +u
source {{CONDA_BASE}}/etc/profile.d/conda.sh
conda activate isimip4b
set -u
export ISIMIP4B_WORKDIR={{WORKDIR}}
export PYTHONPATH={{REPO}}/workflow
MANIFEST="python3 {{REPO}}/workflow/05_simulation/submit/run_manifest.py"

$MANIFEST verify-inputs --run-dir "$RUN_DIR" --job-id "$SLURM_JOB_ID" --processes {{CHECK_PROCESSES}}
rc=$?
if [ $rc -eq 0 ]; then
  conda deactivate
  # runtime modules of the build (builds/vic/<commit>/build_manifest.json, runtime_modules); Lmod's
  # scripts are not safe under set -u either
  set +u
  source /etc/profile.d/z00_lmod.sh
  module purge
{{MODULE_LOADS}}
  module -t list 2>&1 | sed 's/^/module: /'
  set -u
  # Anunna's Slurm (task/cgroup only) confines the job to its cores but binds no task to its own cores, so
  # no OpenMP binding is set: OMP_PLACES/OMP_PROC_BIND would put every rank's threads on the first cores
  export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK}
  cd "$RUN_DIR"
  {{LAUNCHER}} bash -c 'echo "rank $SLURM_PROCID on $(hostname) cpus $(grep Cpus_allowed_list /proc/self/status | cut -f2)"'
  {{LAUNCHER}} {{EXECUTABLE}} -g "$RUN_DIR/config/vic_global.txt" \
      > "$RUN_DIR/logs/vic_stdout_${SLURM_JOB_ID}.txt" 2>&1
  rc=$?
  echo "VIC exit code $rc at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  set +u; module purge; conda activate isimip4b; set -u
fi

$MANIFEST complete --run-dir "$RUN_DIR" --job-id "$SLURM_JOB_ID" --exit-code $rc
crc=$?
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
# the job fails when VIC failed or when the completion step failed or recorded the attempt as failed (missing
# outputs or state), so that jobs waiting with afterok do not start
if [ $rc -ne 0 ]; then exit $rc; fi
exit $crc
