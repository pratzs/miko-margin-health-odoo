# -*- coding: utf-8 -*-
from odoo import fields, models

# Every setting lives on the COMPANY, not on a global parameter, so a group with
# several trading entities can run different margin rules in each without them
# interfering. res.config.settings just surfaces these.

ENFORCE_MODES = [
    ('off', 'Report only, never interrupt'),
    ('warn', 'Warn on confirmation, allow it to proceed'),
    ('block', 'Block confirmation until it is fixed or overridden'),
]

CHECK_LEVELS = [
    ('line', 'Each order line on its own'),
    ('order', 'The order total only'),
    ('both', 'Both the order total and every line'),
]

COST_BASIS = [
    ('standard', 'Product cost (standard price)'),
    ('supplier', 'Best supplier price, falling back to product cost'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    # --- what "enough margin" means here -----------------------------------
    mh_min_margin_percent = fields.Float(
        string='Minimum margin %', default=0.0, digits=(16, 2),
        help="A sale at or above this percentage is acceptable. Set to 0 to allow "
             "any margin that is not an outright loss.")
    mh_min_margin_amount = fields.Float(
        string='Minimum margin per line', default=0.0, digits='Product Price',
        help="Cash margin a single line must clear, whatever the percentage says. "
             "Useful where a percentage is meaningless on low value items.")
    mh_cost_basis = fields.Selection(
        COST_BASIS, string='Cost basis', default='standard', required=True,
        help="Which cost the margin is measured against.")

    # --- how hard to push back ---------------------------------------------
    mh_enforce_mode = fields.Selection(
        ENFORCE_MODES, string='On confirmation', default='warn', required=True,
        help="What happens when someone confirms an order that breaks the rules.")
    mh_check_level = fields.Selection(
        CHECK_LEVELS, string='Measure', default='both', required=True)

    # --- what must never be flagged ----------------------------------------
    # These exist because a control that fires on legitimate business stops being
    # a control and starts being something people work around.
    mh_ignore_zero_cost = fields.Boolean(
        string='Skip products with no cost', default=True,
        help="A product with no cost recorded cannot have its margin judged. "
             "Leave this on, or every uncosted product will block orders.")
    mh_ignore_zero_price = fields.Boolean(
        string='Skip free lines', default=True,
        help="Samples, goodwill replacements and 100% discounts are deliberate. "
             "Turn this off only if a zero price should always be questioned.")
    mh_excluded_categ_ids = fields.Many2many(
        'product.category', 'mh_company_categ_rel', 'company_id', 'categ_id',
        string='Exempt product categories',
        help="Categories the margin rules never apply to, such as clearance.")
    mh_excluded_pricelist_ids = fields.Many2many(
        'product.pricelist', 'mh_company_pricelist_rel', 'company_id', 'pricelist_id',
        string='Exempt pricelists',
        help="Orders on these pricelists are never checked. Use for a clearance or "
             "staff pricelist where selling at or below cost is the intention.")
    mh_excluded_partner_ids = fields.Many2many(
        'res.partner', 'mh_company_partner_rel', 'company_id', 'partner_id',
        string='Exempt customers',
        help="Customers whose orders are never checked, such as intercompany or "
             "staff accounts.")
