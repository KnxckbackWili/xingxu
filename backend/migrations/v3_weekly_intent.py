"""Frozen T40 quantity arithmetic shared only by its unreleased revisions.

Never import live ORM/services here. Original rows are retained independently;
a missing value is unknown, and a finite partial sum is never a full target.
"""
from decimal import Decimal, InvalidOperation, localcontext


def summarize(rows, vehicle):
    known_values = []
    null_count = invalid_count = 0
    for row in rows:
        value = row['planned_quantity']
        if value is None:
            null_count += 1
            continue
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            invalid_count += 1
            continue
        if not value.is_finite():
            invalid_count += 1
            continue
        known_values.append(value)
    # Exact addition of all finite binary-float decimal representations, even
    # across very different magnitudes; default Decimal precision can round.
    with localcontext() as context:
        if known_values:
            context.prec = max(28, max(v.adjusted() for v in known_values) - min(v.as_tuple().exponent for v in known_values) + len(str(len(known_values))) + 2)
        known = sum(known_values, Decimal(0))
    unknown = null_count + invalid_count
    positive = known > 0
    target = int(known) if vehicle and not unknown and positive and known == known.to_integral_value() and known <= 2147483647 else None
    review = bool(unknown or vehicle and positive and target is None)
    return {'mode': 'finish' if positive or unknown else 'in_progress', 'target_count': target,
            'migration_review_required': review,
            'original_planned_sum': None if unknown else str(known), 'known_planned_sum': str(known),
            'unknown_quantity_count': unknown, 'null_quantity_count': null_count, 'invalid_quantity_count': invalid_count}
