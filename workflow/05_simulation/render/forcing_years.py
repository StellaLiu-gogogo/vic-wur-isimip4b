"""Forcing year mapping: the per-run forcing view runs/<campaign>/<run-id>/forcing/<family>/.

VIC and its plugins open forcing files by <prefix><year>.nc, with <year> the simulation year. The accepted
forcing units cover only the years of their sources: the climate units the years of their ISIMIP input alias,
the land-use and water-use units 1850-2021 (histsoc, 1850soc) or 2022-2100 (2021soc, ssp*soc). Experiments
need other years: 1850soc in 1601-1849 and 2022-2100, 2021soc in 1850-2021, and every spin-up needs years
before the pre-industrial or historical period with repeated pre-industrial control climate.

The renderer therefore builds, per run, a forcing view of symbolic links named by simulation year that point
into the accepted units; units are never modified or copied. Rules (the campaign declares which scenarios are
constant and the spin-up climate cycle):

  identity  the unit has a file for the simulation year: link to it.
  constant  the scenario is constant in time (campaign dhf_forcing.constant, e.g. 1850soc, 2021soc) and the
            unit has no file for the year: link to the first year of the unit with the same number of days
            (365 or 366). The day count must match because VIC indexes daily records within the year and the
            water-use demand is mm/day of a calendar year (annual volume / days in year).
  cycle     spin-up climate: simulation year Y maps to a + (Y - a) mod L in the declared window [a, b]
            (L = b - a + 1); when that year has a different day count, the next year of the window (cyclic)
            with the same day count is used. A year that maps to itself is recorded as identity, and so is a
            start year of the unit made as a copy of its cycle year for the same window (D20).

The mapping of every year is returned as data and recorded in the run manifest.
"""
import calendar, os


def days(year):
    return 366 if calendar.isleap(year) else 365   # proleptic Gregorian


def map_identity_or_constant(sim_years, unit_years, constant):
    """{sim_year: (source_year, rule)} for one DHF unit."""
    have = sorted(set(unit_years))
    if not have:
        raise ValueError('the unit has no yearly files')
    first_by_days = {}
    for y in have:
        first_by_days.setdefault(days(y), y)
    out = {}
    for y in sim_years:
        if y in have:
            out[y] = (y, 'identity')
        elif constant:
            if days(y) not in first_by_days:
                raise ValueError(f'constant unit has no {days(y)}-day year for {y}')
            out[y] = (first_by_days[days(y)], 'constant')
        else:
            raise ValueError(f'year {y} is not in the unit ({have[0]}-{have[-1]}) and the scenario is not '
                             'declared constant')
    return out


def cycle_source(year, window):
    """Source year of simulation year `year` in the cycle window [a, b]: a + (year - a) mod L, or, when that year has
    another day count, the next year of the window (cyclic) with the same day count."""
    a, b = int(window[0]), int(window[1])
    span = list(range(a, b + 1)); n = len(span)
    i = (year - a) % n
    for k in range(n):
        s = span[(i + k) % n]
        if days(s) == days(year):
            return s
    raise ValueError(f'cycle window {a}-{b} has no {days(year)}-day year for {year}')


def map_cycle(sim_years, window, unit_years, start_years=None, cycle_windows=None):
    """{sim_year: (source_year, rule)} for spin-up climate over the window [a, b]; the rule is 'identity' when the
    source year is the simulation year (the file and its time axis are of that year), else 'cycle'.

    A start year of the unit (D20: provenance `start_years` {year: source year}, `cycle_windows` {year: [a, b]}) is a
    copy of its cycle year re-stamped to its own year; it is used as itself ('identity') when it was made for this
    window, so that a spin-up can start in it (VIC checks the start-year file's first time). A start year made for
    another window stops the mapping: its data are not the cycle year of this window."""
    a, b = int(window[0]), int(window[1])
    missing = sorted(set(range(a, b + 1)) - set(unit_years))
    if missing:
        raise ValueError(f'cycle window {a}-{b} not covered by the unit (missing {missing[:5]}...)')
    starts = {int(y): int(s) for y, s in (start_years or {}).items()}
    windows = {int(y): [int(v) for v in w] for y, w in (cycle_windows or {}).items()}
    out = {}
    for y in sim_years:
        s = cycle_source(y, (a, b))
        if y in starts and y in set(unit_years):
            if starts[y] != s or windows.get(y) != [a, b]:
                raise ValueError(f'start year {y} of the unit is a copy of {starts[y]} made for the cycle window '
                                 f'{windows.get(y)}; the campaign window {a}-{b} needs a copy of {s}')
            out[y] = (y, 'identity')
        else:
            out[y] = (s, 'identity' if s == y else 'cycle')
    return out


def relative_link(link_path, target_path):
    """Create link_path -> target_path as a relative symbolic link (the view moves with the workdir)."""
    os.makedirs(os.path.dirname(link_path), exist_ok=True)
    rel = os.path.relpath(target_path, os.path.dirname(link_path))
    if os.path.lexists(link_path):
        if os.readlink(link_path) == rel:
            return
        raise FileExistsError(f'{link_path} exists and points elsewhere')
    os.symlink(rel, link_path)


def build_view(view_dir, entries):
    """Create the links of one run. entries: iterable of (link name relative to view_dir, target absolute path).
    Every target must exist; nothing is written when one is missing."""
    entries = list(entries)
    missing = [t for _, t in entries if not os.path.isfile(t)]
    if missing:
        raise FileNotFoundError(f'{len(missing)} forcing targets missing, e.g. {missing[:3]}')
    for name, target in entries:
        relative_link(os.path.join(view_dir, name), target)
    return len(entries)
