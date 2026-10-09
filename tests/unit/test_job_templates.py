"""Unit tests for the Slurm job templates of the producers (03_parameters vegetation and bundle; 04_forcing climate,
land use and water use): the start of the job, up to the activation of the isimip4b environment, runs under
`set -euo pipefail` also when conda's activation scripts read variables that are not set (the magics package of the
environment reads MAGPLUS_HOME), i.e. when the job is submitted from a shell without the environment.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, re, subprocess, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, '..', '..', 'workflow')
TEMPLATES = ['03_parameters/vegetation/vegetation_component.sbatch', '03_parameters/bundle/bundle.sbatch',
             '04_forcing/climate/climate_forcing.sbatch', '04_forcing/landuse/landuse_forcing.sbatch',
             '04_forcing/water_use/water_use_forcing.sbatch']
CONDA_SH = '''conda() {
    # stand-in for conda: its activation scripts read variables that may be unset (magics: MAGPLUS_HOME)
    : "$MAGPLUS_HOME_NOT_SET_IN_THIS_TEST"
    echo "activated $2"
}
'''


class ActivationTest(unittest.TestCase):
    def run_start(self, template):
        """Run the template up to the line after `conda activate`; returns (exit status, output)."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(f'{d}/conda/etc/profile.d'); os.makedirs(f'{d}/logs')
            with open(f'{d}/conda/etc/profile.d/conda.sh', 'w') as fh:
                fh.write(CONDA_SH)
            for ext in ('out', 'err'):
                open(f'{d}/logs/slurm-1.{ext}', 'w').close()
            with open(os.path.join(WF, template)) as fh:
                lines = fh.read().splitlines()
            end = next(i for i, l in enumerate(lines) if 'conda activate isimip4b' in l)
            while end + 1 < len(lines) and lines[end + 1].strip() in ('set -u',):
                end += 1
            text = '\n'.join(lines[:end + 1]) + '\necho "start done"\n'
            text = text.replace('{{CONDA_BASE}}', f'{d}/conda').replace('{{STAGE_LOGS}}', f'{d}/logs')
            text = re.sub(r'\{\{[A-Z_]+\}\}', 'x', text)
            r = subprocess.run(['bash', '-c', text], capture_output=True, text=True,
                               env={'PATH': os.environ['PATH'], 'SLURM_JOB_ID': '1', 'HOME': d})
            return r.returncode, r.stdout + r.stderr

    def test_activation_without_environment(self):
        for t in TEMPLATES:
            with self.subTest(template=t):
                rc, out = self.run_start(t)
                self.assertEqual(rc, 0, out)
                self.assertIn('activated isimip4b', out)
                self.assertIn('start done', out)

    def test_strict_mode_back_after_activation(self):
        for t in TEMPLATES:
            with self.subTest(template=t):
                with open(os.path.join(WF, t)) as fh:
                    text = fh.read()
                after = text.split('conda activate isimip4b', 1)[1]
                self.assertRegex(after.split('python3', 1)[0], r'\nset -u\n')


if __name__ == '__main__':
    unittest.main()
