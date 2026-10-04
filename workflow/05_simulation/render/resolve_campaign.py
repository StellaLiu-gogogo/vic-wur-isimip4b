#!/usr/bin/env python3
"""Resolve a campaign (configs/campaigns/<id>.yaml) into segments and runs from the pinned ISIMIP protocol.

The campaign selects experiments; this module derives the segments, their years and their parents from the
experiment definitions of the protocol commit the campaign pins (definitions/experiments/<round>.yaml and
definitions/period.yaml), never from a hand-written list (docs/directory-contracts.md, `configs/`).

Rules (docs/glossary.md, "Segment", "Segment ID", "Run"; protocol 02.experiments.md, spin-up notes):
  period entry       a mapping {climate, soc[, soc_sens | climate_sens]} defines the segment of that period;
                     "Identical to the similar **<climate>/<soc>[/<sens>]** run above." refers to the segment
                     with that composition in the same period, which must be defined explicitly by an experiment
                     of the protocol; "Does not have to be simulated, spin-up should be based on the <year> DHF"
                     means there is no pre-industrial segment and the spin-up links directly to the historical
                     period, with <year>soc as the spin-up DHF.
  sensitivity        the segment's sens scenario is soc_sens or climate_sens of the entry, else `default`; the
                     campaign's `sensitivity_equivalence` maps a sens scenario to another one (2021co2 -> default
                     for VIC-WUR, which has no CO2 response), so such an experiment shares the other's segments.
  spin-up            pre-industrial control climate (`picontrol`), the DHF of the pre-industrial period
                     (1850soc), or the DHF named by the "spin-up should be based on" note (2021soc).
  parents            pre-industrial <- spin-up; historical <- the experiment's pre-industrial segment, or the
                     spin-up when the pre-industrial period is not simulated; future <- historical. A segment
                     shared by several experiments must get the same parent from each of them.
  segment ID         <gcm>_<climate>_<soc>_<sens>_<period>; run ID = segment ID, plus `__<label>` for a run of a
                     non-production campaign restricted to part of a segment (campaign `restriction`).

Usage: resolve_campaign.py --campaign configs/campaigns/smoke.yaml [--label smoke2015] [--json]
"""
import argparse, calendar, json, os, re, sys
from dataclasses import dataclass, field, asdict

import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
PERIODS = ('pre-industrial', 'historical', 'future')
ORDER = {'spinup': 0, 'pre-industrial': 1, 'historical': 2, 'future': 3}
SPINUP_CLIMATE = 'picontrol'
IDENTICAL = re.compile(r'Identical to the similar \*\*([^*]+)\*\* run', re.I)
SPINUP_DHF = re.compile(r'Does not have to be simulated, spin-up should be based on the (\d{4}) DHF', re.I)
CAMPAIGN_KEYS = {'campaign_id', 'production', 'description', 'model', 'parameter_set', 'protocol', 'gcms',
                 'experiments', 'exclusions', 'sensitivity_equivalence', 'restriction', 'initialisation', 'spinup',
                 'dhf_forcing', 'plugins', 'output', 'resources', 'open_decisions'}
CAMPAIGN_REQUIRED = CAMPAIGN_KEYS - {'description', 'restriction', 'spinup', 'open_decisions', 'exclusions'}


class CampaignError(ValueError):
    pass


@dataclass
class Segment:
    gcm: str
    climate: str
    soc: str
    sens: str
    period: str
    start_year: int
    end_year: int
    parent: str = None
    experiments: list = field(default_factory=list)

    @property
    def id(self):
        return f'{self.gcm}_{self.climate}_{self.soc}_{self.sens}_{self.period}'


# ------------------------------------------------------------------------------------------------ inputs
def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def load_campaign(path):
    with open(path) as fh:
        c = yaml.safe_load(fh)
    unknown = set(c) - CAMPAIGN_KEYS
    missing = CAMPAIGN_REQUIRED - set(c)
    if unknown or missing:
        raise CampaignError(f'{path}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}')
    if os.path.splitext(os.path.basename(path))[0] != c['campaign_id']:
        raise CampaignError(f'{path}: file name differs from campaign_id {c["campaign_id"]}')
    if c['production'] and c.get('restriction'):
        raise CampaignError('a production campaign cannot carry a restriction (runs of production campaigns never '
                            'carry a label, docs/directory-contracts.md `runs/`)')
    return c


def load_protocol(protocol_dir, simulation_round):
    d = os.path.join(protocol_dir, 'definitions')
    with open(os.path.join(d, 'experiments', f'{simulation_round}.yaml')) as fh:
        experiments = yaml.safe_load(fh)
    with open(os.path.join(d, 'period.yaml')) as fh:
        periods = yaml.safe_load(fh)
    with open(os.path.join(d, 'climate_scenario.yaml')) as fh:
        climate = yaml.safe_load(fh)
    years = {}
    for p in periods:
        if 'simulation_rounds' in p and simulation_round not in p['simulation_rounds']:
            continue
        pick = lambda v: v[simulation_round] if isinstance(v, dict) else v   # noqa: E731
        years[p['specifier']] = (int(pick(p['start_year'])), int(pick(p['end_year'])))
    aliases = {c['specifier']: c.get('specifier_alias', [c['specifier']]) for c in climate
               if simulation_round in c.get('simulation_rounds', [simulation_round])}
    return experiments, years, aliases


def input_alias(aliases, climate, mode):
    """Input alias of a climate scenario for a GCM run that is `concentration-driven` or `emission-driven`
    (CMIP7 vocabulary: emission-driven aliases start with `esm-`, docs/glossary.md)."""
    if mode not in ('concentration-driven', 'emission-driven'):
        raise CampaignError(f'climate_input must be concentration-driven or emission-driven, not {mode}')
    want_esm = mode == 'emission-driven'
    hits = [a for a in aliases[climate] if a.startswith('esm-') == want_esm]
    if len(hits) != 1:
        raise CampaignError(f'no unique {mode} input alias for {climate}: {aliases[climate]}')
    return hits[0]


# ------------------------------------------------------------------------------------------------ rules
def period_entry(exp, period):
    """(climate, soc, sens) of an explicit entry, ('identical', (climate, soc, sens)) of a reference, or
    ('spinup', soc) when the period is not simulated and the spin-up links to the next period."""
    e = exp.get(period)
    if isinstance(e, dict):
        sens = e.get('soc_sens') or e.get('climate_sens') or 'default'
        return 'explicit', (e['climate'], e['soc'], sens)
    if isinstance(e, str):
        e = ' '.join(e.split())
        m = IDENTICAL.search(e)
        if m:
            parts = m.group(1).strip().split('/')
            if len(parts) not in (2, 3):
                raise CampaignError(f'{exp["specifier"]} {period}: cannot read reference "{m.group(1)}"')
            return 'identical', (parts[0], parts[1], parts[2] if len(parts) == 3 else 'default')
        m = SPINUP_DHF.search(e)
        if m and period == 'pre-industrial':
            return 'spinup', f'{m.group(1)}soc'
    raise CampaignError(f'{exp["specifier"]} {period}: unsupported period entry {e!r}')


def select_experiments(campaign, experiments):
    sel = campaign['experiments']
    rnd = campaign['protocol']['simulation_round']; sector = campaign['protocol']['sector']
    pool = [e for e in experiments if sector in e.get('sectors', []) and rnd in e.get('simulation_rounds', [rnd])]
    by_id = {e['specifier']: e for e in pool}
    if 'ids' in sel:
        unknown = [i for i in sel['ids'] if i not in by_id]
        if unknown:
            raise CampaignError(f'experiments not defined for {sector} in {rnd}: {unknown}')
        chosen = [by_id[i] for i in sel['ids']]
    elif 'priority' in sel:
        chosen = [e for e in pool if e.get('priority') in sel['priority']]
    elif sel.get('all'):
        chosen = list(pool)
    else:
        raise CampaignError('experiments: give ids, priority, or all: true')
    excluded = {x['experiment']: x['reason'] for x in campaign.get('exclusions') or []}
    for x, reason in excluded.items():
        if x not in by_id:
            raise CampaignError(f'exclusion of unknown experiment {x}')
        if not str(reason).strip():
            raise CampaignError(f'exclusion of {x} has no reason')
    return [e for e in chosen if e['specifier'] not in excluded], excluded, pool


def resolve(campaign, protocol_dir):
    """All segments of the campaign per GCM (dict id -> Segment, dependency order) and the experiment chains."""
    rnd = campaign['protocol']['simulation_round']
    experiments, years, _ = load_protocol(protocol_dir, rnd)
    chosen, _, pool = select_experiments(campaign, experiments)
    equiv = {k: v['same_as'] for k, v in (campaign.get('sensitivity_equivalence') or {}).items()}
    spin = campaign.get('spinup') or {}

    # compositions defined explicitly by some experiment of the sector, per period (targets of references)
    defined = {p: set() for p in PERIODS}
    for e in pool:
        for p in PERIODS:
            kind, val = period_entry(e, p)
            if kind == 'explicit':
                defined[p].add(_eq(val, equiv))

    segments, chains = {}, {}
    for gcm in campaign['gcms']:
        for e in chosen:
            chain, parent = [], None
            kind, val = period_entry(e, 'pre-industrial')
            if kind == 'spinup':
                spin_soc, pre = val, None
            else:
                pre = _eq(val, equiv)
                if kind == 'identical' and pre not in defined['pre-industrial']:
                    raise CampaignError(f'{e["specifier"]}: reference {"/".join(val)} is not defined')
                spin_soc = pre[1]
            sy = _spinup_years(spin, years, 'historical' if pre is None else 'pre-industrial')
            parent = _add(segments, Segment(gcm, SPINUP_CLIMATE, spin_soc, 'default', 'spinup', *sy), None, e)
            chain.append(parent)
            for p in PERIODS:
                kind, val = period_entry(e, p)
                if kind == 'spinup':
                    continue
                comp = _eq(val, equiv)
                if kind == 'identical' and comp not in defined[p]:
                    raise CampaignError(f'{e["specifier"]}: reference {"/".join(val)} in {p} is not defined')
                parent = _add(segments, Segment(gcm, *comp, p, *years[p]), parent, e)
                chain.append(parent)
            chains[(gcm, e['specifier'])] = chain
    ordered = dict(sorted(segments.items(), key=lambda kv: (kv[1].gcm, ORDER[kv[1].period], kv[0])))
    return ordered, chains


def _eq(comp, equiv):
    climate, soc, sens = comp
    return climate, soc, equiv.get(sens, sens)


def _spinup_years(spin, years, next_period):
    """Spin-up simulation years: the `length_years` years before the first year of the next period."""
    first = years[next_period][0]
    n = spin.get('length_years')
    if n is None:
        return (None, first - 1)
    return (first - int(n), first - 1)


def _add(segments, seg, parent, exp):
    sid = seg.id
    if sid in segments:
        old = segments[sid]
        if old.parent != parent:
            raise CampaignError(f'segment {sid} gets parent {parent} from {exp["specifier"]} but {old.parent} '
                                f'from {old.experiments}')
    else:
        seg.parent = parent
        segments[sid] = seg
    if exp['specifier'] not in segments[sid].experiments:
        segments[sid].experiments.append(exp['specifier'])
    return sid


# ------------------------------------------------------------------------------------------------ runs
def runs(campaign, segments, label=None):
    """Runs of the campaign: every segment, or with a restriction the segments of the restricted periods with
    the years of `label`. Returns a list of dicts in dependency order."""
    r = campaign.get('restriction')
    out = []
    if r:
        if label is None:
            raise CampaignError(f'campaign {campaign["campaign_id"]} is restricted; choose a label from '
                                f'{sorted(r["runs"])}')
        if label not in r['runs']:
            raise CampaignError(f'unknown label {label}; labels: {sorted(r["runs"])}')
        if not re.fullmatch(r'[a-z0-9-]+', label):
            raise CampaignError(f'label {label} must be lowercase letters, digits and hyphens')
        y0, y1 = (int(v) for v in r['runs'][label]['years'])
    elif label is not None:
        raise CampaignError('labels exist only for restricted non-production campaigns')
    for sid, s in segments.items():
        if r and s.period not in r['periods']:
            continue
        start, end = (y0, y1) if r else (s.start_year, s.end_year)
        if s.start_year is not None and not (s.start_year <= start <= end <= s.end_year):
            raise CampaignError(f'{sid}: years {start}-{end} outside the segment {s.start_year}-{s.end_year}')
        if start is None:
            raise CampaignError(f'{sid}: spin-up length is not declared (campaign spinup.length_years)')
        out.append({'run_id': sid + (f'__{label}' if r else ''), 'segment_id': sid, 'label': label if r else None,
                    'start_year': start, 'end_year': end, 'segment': asdict(s)})
    return out


def leap(year):
    return calendar.isleap(year)   # proleptic Gregorian, the VIC clock calendar of the project


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--label', default=None)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    c = load_campaign(a.campaign)
    segs, chains = resolve(c, os.path.join(workdir(), c['protocol']['path']))
    if a.json:
        print(json.dumps({'segments': [asdict(s) | {'id': k} for k, s in segs.items()],
                          'runs': runs(c, segs, a.label)}, indent=1))
        return
    for k, s in segs.items():
        print(f'{k:62s} {s.start_year}-{s.end_year}  parent {s.parent}  ({len(s.experiments)} experiments)')
    print()
    for r in runs(c, segs, a.label):
        print(f'run {r["run_id"]}  {r["start_year"]}-{r["end_year"]}')


if __name__ == '__main__':
    main()
