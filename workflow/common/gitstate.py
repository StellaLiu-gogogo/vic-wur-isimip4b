"""Git state of the repository, for provenance records and the clean-repository rule (contract, rule 14).

A repository is clean when `git status --porcelain` prints nothing (docs/glossary.md). The code fingerprint of a
producer is the set of Git tree hashes of its directories at HEAD (contract, "Forcing unit and provenance record").
"""
import subprocess


def git(repo, *args):
    """Run git in `repo`; returns the CompletedProcess (no exception on a non-zero exit)."""
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True)


def state(repo):
    """(commit, dirty): the full HEAD commit and whether the repository is not clean. Stops if git fails."""
    out = []
    for args in (('rev-parse', 'HEAD'), ('status', '--porcelain')):
        r = git(repo, *args)
        if r.returncode != 0:
            raise SystemExit(f'git {" ".join(args)} failed in {repo}: {r.stderr.strip()}')
        out.append(r.stdout.strip())
    return out[0], bool(out[1])


def tree_hashes(repo, paths):
    """{path: Git tree hash at HEAD, or None when the path does not exist at HEAD}, in the order given."""
    res = {}
    for p in paths:
        r = git(repo, 'rev-parse', f'HEAD:{p}')
        res[p] = r.stdout.strip() if r.returncode == 0 else None
    return res
