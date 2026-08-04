# Miko Margin Health for Odoo

Finds products priced below their own cost, stops orders that lose money at the
moment of confirmation, and identifies pricelist rules that can never apply.

| | |
|---|---|
| Series | 14.0 to 19.0 (20.0 on release) |
| Price | USD 49, licence OPL-1 |
| Depends | `product`, `sale` |
| Tests | 30 per series, 6/6 certified |
| Category | Accounting |
| Colour | Miko mark in orchid `#D492C8` to `#A8479A` |

## Why it exists

Odoo will save a sales price under the cost price without a word. The quotation
looks normal, the order confirms, the invoice posts, and the loss only surfaces if
somebody runs a margin report.

**The demo data inside Odoo itself contains six products priced below cost**, one
at minus 308 percent. Install on a fresh database with demo data and it finds them.

## The feature nobody else has

Odoo evaluates pricelist rules in a fixed order and returns the FIRST match. A rule
behind another that already covers the same ground is dead: it looks active, it has
a discount on it, and it has never once applied. This reproduces Odoo's own
ordering and names the rule that wins instead.

Only provable shadowing is claimed: same exact target, same-or-lower quantity
threshold, covering date window. A category rule overlapping a product rule is real
but needs the category tree walked, and a wrong answer would condemn a rule that
does fire.

## What it deliberately never flags

Half the test suite exists to prove the module stays quiet:

- Products marked as deliberate loss leaders
- Products with no cost recorded (a missing cost is an unanswered question, not a
  perfect margin; without this every uncosted product blocks every order)
- Free lines: samples, goodwill, full discounts
- Exempt categories, pricelists and customers, set per company
- Sections, notes and down payment lines

## Settings, all per company

Minimum margin percentage and cash amount, cost basis (product cost or best
supplier price), enforcement off/warn/block, measured per line or order total or
both, plus the exemption lists above. Settings live on their own screen under the
app's menu rather than xpath'd into Odoo's Sales settings, which is restructured
between versions.

## Release cycle

Identical to the other two apps. Source of truth is `miko_margin_health/`;
`build/` and `publish-repo/` are generated. Certify all six series before pushing,
never after. Full store runbook: `Apps/miko-catalog-health-odoo/PUBLISHING.md`.

```bash
cd _dev && python3 build_versions.py
```

Odoo 14 and 15 need `--platform=linux/amd64` on Apple Silicon.

## Version differences this app hit, beyond the shared ones

| Difference | Affects | Handling |
|---|---|---|
| `res.groups.category_id` | gone in 19 (now `privilege_id`) | omitted entirely; it is cosmetic |
| `res.users.groups_id` | renamed `group_ids` in 19 | test helper picks whichever exists |
| `cls.env` in `setUpClass` | 15+ only | tests use instance-level `setUp` |
| xpath STRINGS naming `list` | 18+ only | build rewrites `/list//` to `/tree//` |
| `pricelist.item` date bounds | Date on some series, Datetime on others | coerced before comparison |

**A class-setup failure disables every test in that class and still reports as a
single error.** On Odoo 14 the summary read "14 tests" instead of 30; only the
count gave it away. Always check the test COUNT, not just the failure number.
