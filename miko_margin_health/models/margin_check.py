# -*- coding: utf-8 -*-
"""Margin arithmetic and pricelist reachability analysis.

Two independent problems, both invisible in Odoo until someone reconciles a month
and finds the money missing.

**Selling below cost.** Odoo will let you set a sales price under the cost price
and say nothing. Every order then loses money, and because the order itself looks
completely normal nobody notices until the margin report is run, if it ever is.

**Pricelist rules that can never fire.** Odoo evaluates pricelist items in a fixed
order and returns the FIRST one that matches. A rule sitting behind another rule
that already covers every case it would cover is dead: it is in the list, it looks
active, and it has never once applied. Nobody is told. This module works out which
rules those are.

Everything here is pure arithmetic on values already in the database. No network,
no external service.
"""

MARGIN_STATUS = [
    ('ok', 'Healthy'),
    ('below_cost', 'Sold below cost'),
    ('zero_margin', 'No margin'),
    ('thin', 'Thin margin'),
    ('no_cost', 'No cost recorded'),
    ('na', 'Not applicable'),
]

# Below this the product earns almost nothing once handling and payment fees are
# taken out. Reported, never counted, because plenty of trades run thin on
# purpose: loss leaders, clearance, and pass-through items are all legitimate.
THIN_MARGIN_PCT = 5.0


def margin_amount(price, cost):
    """Cash margin per unit."""
    return round((price or 0.0) - (cost or 0.0), 6)


def margin_percent(price, cost):
    """Margin as a percentage of the SELLING price, which is how retail quotes it.

    Returns None when there is no price, because dividing by zero is not a
    "0% margin", it is an unanswerable question and must not be reported as a
    number.
    """
    price = price or 0.0
    if not price:
        return None
    return round(((price - (cost or 0.0)) / price) * 100.0, 4)


def classify_margin(price, cost, sellable=True):
    """Judge one product's list price against its cost.

    Deliberately conservative, for the same reason the barcode and email checks
    are: a false alarm on a legitimate price makes the whole audit untrustworthy.

    - A cost of zero is NOT a 100% margin. It usually means nobody has entered a
      cost yet, so it is reported as 'no_cost' and never counted as breakage.
    - Products that are not sold are 'na'.
    """
    if not sellable:
        return 'na', None, None
    price = price or 0.0
    cost = cost or 0.0

    if cost <= 0.0:
        return 'no_cost', margin_amount(price, cost), margin_percent(price, cost)
    if not price:
        return 'no_cost', None, None

    amount = margin_amount(price, cost)
    percent = margin_percent(price, cost)

    if amount < 0:
        return 'below_cost', amount, percent
    if amount == 0:
        return 'zero_margin', amount, percent
    if percent is not None and percent < THIN_MARGIN_PCT:
        return 'thin', amount, percent
    return 'ok', amount, percent


# --------------------------------------------------------------------------
# Pricelist reachability
# --------------------------------------------------------------------------

# Odoo evaluates product.pricelist.item in this order and takes the first match:
#   applied_on ascending  (variant, then product, then category, then global)
#   min_quantity descending
#   categ_id descending
#   id descending
# A rule is unreachable when an earlier rule matches everything it would match.
SPECIFICITY = {'0_product_variant': 0, '1_product': 1, '2_product_category': 2, '3_global': 3}


def rule_sort_key(rule):
    """Reproduce Odoo's own ordering so reachability is judged the way Odoo picks."""
    return (
        SPECIFICITY.get(rule.get('applied_on'), 9),
        -(rule.get('min_quantity') or 0),
        -(rule.get('id') or 0),
    )


def same_target(a, b):
    """Do two rules aim at exactly the same thing?

    Only an EXACT match counts. A category rule and a product rule inside that
    category overlap in reality, but proving that requires walking the category
    tree and the product's place in it, and a wrong answer there would condemn a
    rule that does fire. Exact matches are provable, so those are all we claim.
    """
    if a.get('applied_on') != b.get('applied_on'):
        return False
    applied = a.get('applied_on')
    if applied == '3_global':
        return True
    if applied == '2_product_category':
        return a.get('categ_id') == b.get('categ_id')
    if applied == '1_product':
        return a.get('product_tmpl_id') == b.get('product_tmpl_id')
    return a.get('product_id') == b.get('product_id')


def dates_cover(outer, inner):
    """Does `outer`'s active window contain the whole of `inner`'s?

    An empty bound means open ended, so a rule with no dates covers all time.
    """
    o_start, o_end = outer.get('date_start'), outer.get('date_end')
    i_start, i_end = inner.get('date_start'), inner.get('date_end')
    if o_start and (not i_start or i_start < o_start):
        return False
    if o_end and (not i_end or i_end > o_end):
        return False
    return True


def find_unreachable(rules):
    """Return {rule_id: reason} for every rule that can never apply.

    A rule is unreachable when some earlier rule, on the same pricelist, aims at
    exactly the same target, is reached for at least the same quantities, and is
    active across at least the same dates. In that situation Odoo returns the
    earlier rule every single time and the later one is dead.
    """
    ordered = sorted(rules, key=rule_sort_key)
    unreachable = {}
    for i, rule in enumerate(ordered):
        for earlier in ordered[:i]:
            if earlier['id'] in unreachable:
                continue  # a dead rule cannot shadow anything
            if not same_target(earlier, rule):
                continue
            # Ordering is min_quantity DESCENDING, so `earlier` is reached at a
            # quantity at least as low as this rule's threshold only when its own
            # threshold is lower or equal.
            if (earlier.get('min_quantity') or 0) > (rule.get('min_quantity') or 0):
                continue
            if not dates_cover(earlier, rule):
                continue
            unreachable[rule['id']] = earlier['id']
            break
    return unreachable
