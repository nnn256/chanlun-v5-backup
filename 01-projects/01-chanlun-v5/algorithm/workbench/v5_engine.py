"""Bind workbench analyses to the declared V5 recursive research profile."""
from __future__ import annotations

from chanmodel.complete_study import analyze_complete
from chanmodel.model import Config
from chanmodel.unified import analyze_all


PROFILE = 'course_feature_sequence_recursive_v2'
MAX_RANK = 8
CONFIG = Config(
    stroke_mode='strict',
    second_policy='conservative',
    third_boundary='strict_outside',
    max_depth=3,
)


def report(symbol, period, bars, cutoff, digest=None, source='tdx',
           adjustment='unadjusted', max_rank=MAX_RANK):
    """Analyze one timeframe using the same rules as the V5 market runner."""
    value = analyze_complete(
        symbol,
        period,
        bars,
        cutoff,
        digest or '',
        source=source,
        adjustment=adjustment,
        config=CONFIG,
        max_rank=max_rank,
    )
    value['workbench_profile'] = PROFILE
    return value


def analyze_inputs(inputs, cutoff, roles=None, volume_tolerance=1.0, max_rank=MAX_RANK):
    """Analyze timeframe series and links under the declared V5 config."""
    value = analyze_all(
        inputs,
        cutoff,
        config=CONFIG,
        max_rank=max_rank,
        roles=roles,
        volume_tolerance=volume_tolerance,
    )
    value['workbench_profile'] = PROFILE
    for report in value['reports'].values():
        report['workbench_profile'] = PROFILE
    return value
