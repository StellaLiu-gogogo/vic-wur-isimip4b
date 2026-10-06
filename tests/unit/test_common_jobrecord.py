"""Unit tests for workflow/common/jobrecord.py with the Slurm commands replaced (no job is submitted).

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import os, subprocess, tempfile, unittest
from unittest import mock

import yaml

from common import jobrecord


class FakeSlurm:
    """Records sbatch/scontrol calls; sbatch answers with `answer`."""
    def __init__(self, answer='4242;cluster', rc=0):
        self.calls = []; self.answer = answer; self.rc = rc

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[0] == 'sbatch':
            return subprocess.CompletedProcess(cmd, self.rc, stdout=self.answer + '\n', stderr='bad request')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')


class JobRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = self.tmp.name
        self.template = f'{self.d}/job.sbatch.template'
        with open(self.template, 'w') as fh:
            fh.write('#SBATCH --job-name={{JOB_NAME}}\n#SBATCH --mem={{MEM}}\npython3 x.py {{ARGS}}\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_render(self):
        text = jobrecord.render(self.template, {'JOB_NAME': 'a-b', 'MEM': '9G', 'ARGS': '--years 2015'})
        self.assertEqual(text, '#SBATCH --job-name=a-b\n#SBATCH --mem=9G\npython3 x.py --years 2015\n')
        with self.assertRaises(SystemExit):
            jobrecord.render(self.template, {'JOB_NAME': 'a-b', 'MEM': '9G'})       # {{ARGS}} left

    def test_submit_on_hold_record_then_release(self):
        slurm = FakeSlurm(); logs = f'{self.d}/logs/04_forcing'
        details = {'resources': {'mem': '9G'}, 'outputs': ['scratch/x']}
        with mock.patch.object(jobrecord.subprocess, 'run', slurm), mock.patch('builtins.print'):
            job_id, job_dir = jobrecord.submit('#!/bin/bash\n', logs, 'landuse-forcing-histsoc-2015', 'workflow/a.py',
                                               'workflow/a.sbatch', 'c' * 40, True, details)
        self.assertEqual((job_id, job_dir), ('4242', f'{logs}/landuse-forcing-histsoc-2015_4242'))
        self.assertEqual([c[0][0] for c in slurm.calls], ['sbatch', 'scontrol'])
        self.assertIn('--hold', slurm.calls[0][0])
        self.assertEqual(slurm.calls[0][1]['input'], '#!/bin/bash\n')
        self.assertEqual(slurm.calls[1][0], ['scontrol', 'release', '4242'])
        self.assertEqual(open(f'{job_dir}/job.sbatch').read(), '#!/bin/bash\n')
        rec = yaml.safe_load(open(f'{job_dir}/job.yaml'))
        self.assertEqual(list(rec), ['slurm_job_id', 'job_name', 'rendered_by', 'template', 'code_commit', 'code_dirty',
                                     'submitted_at', 'resources', 'outputs'])
        self.assertEqual((rec['slurm_job_id'], rec['code_dirty']), (4242, True))

    def test_sbatch_failure_writes_no_record(self):
        slurm = FakeSlurm(rc=1); logs = f'{self.d}/logs/03_parameters'
        with mock.patch.object(jobrecord.subprocess, 'run', slurm):
            with self.assertRaises(SystemExit) as cm:
                jobrecord.submit('x', logs, 'job', 'a', 'b', 'c', False, {})
        self.assertIn('sbatch failed', str(cm.exception))
        self.assertEqual(os.listdir(logs), [])
        self.assertEqual(len(slurm.calls), 1)                    # nothing released

    def test_conda_base(self):
        with mock.patch.object(jobrecord.subprocess, 'run',
                               return_value=subprocess.CompletedProcess([], 0, stdout='/opt/conda\n')):
            self.assertEqual(jobrecord.conda_base(), '/opt/conda')
        with mock.patch.object(jobrecord.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='')), \
                mock.patch.dict(os.environ, {'CONDA_EXE': '/opt/miniconda/bin/conda'}):
            self.assertEqual(jobrecord.conda_base(), '/opt/miniconda')


if __name__ == '__main__':
    unittest.main()
