# -*- coding: utf-8 -*-
import datetime

from odoo import api, fields, models, _

from .margin_check import find_unreachable


def as_date(value):
    """Coerce a pricelist date bound to a plain date.

    product.pricelist.item.date_start/date_end is a Date on some Odoo series and
    a Datetime on others. Comparing the two raises TypeError, which crashed the
    compute on any pricelist that had dates at all.
    """
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return fields.Date.to_date(value)

RULE_STATUS = [
    ('ok', 'Can apply'),
    ('unreachable', 'Never applies'),
    ('expired', 'Expired'),
    ('future', 'Not started yet'),
]


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    mh_rule_status = fields.Selection(
        RULE_STATUS, string='Rule Check', compute='_compute_rule_health',
        store=True, index=True,
        help="Whether Odoo can ever return this rule. Odoo takes the FIRST "
             "matching rule, so a rule sitting behind one that already covers "
             "every case it would cover is dead.")
    mh_shadowed_by = fields.Many2one(
        'product.pricelist.item', string='Shadowed by',
        compute='_compute_rule_health', store=True,
        help="The rule Odoo returns instead of this one, every time.")

    @api.depends('pricelist_id', 'applied_on', 'product_tmpl_id', 'product_id',
                 'categ_id', 'min_quantity', 'date_start', 'date_end')
    def _compute_rule_health(self):
        today = fields.Date.context_today(self)
        # Reachability depends on every OTHER rule on the same pricelist, so the
        # whole pricelist is loaded once per pricelist rather than per rule.
        by_pricelist = {}
        for item in self:
            if item.pricelist_id:
                by_pricelist.setdefault(item.pricelist_id.id, True)

        siblings = {}
        if by_pricelist:
            all_items = self.env['product.pricelist.item'].search(
                [('pricelist_id', 'in', list(by_pricelist))])
            for it in all_items:
                siblings.setdefault(it.pricelist_id.id, []).append({
                    'id': it.id,
                    'applied_on': it.applied_on,
                    'product_tmpl_id': it.product_tmpl_id.id,
                    'product_id': it.product_id.id,
                    'categ_id': it.categ_id.id,
                    'min_quantity': it.min_quantity,
                    'date_start': as_date(it.date_start),
                    'date_end': as_date(it.date_end),
                })

        dead = {}
        for pl_id, rules in siblings.items():
            dead.update(find_unreachable(rules))

        for item in self:
            status, shadow = 'ok', False
            end, start = as_date(item.date_end), as_date(item.date_start)
            if end and end < today:
                status = 'expired'
            elif start and start > today:
                status = 'future'
            elif item.id in dead:
                status = 'unreachable'
                shadow = dead[item.id]
            item.mh_rule_status = status
            item.mh_shadowed_by = shadow

    @api.model
    def action_pricelist_rescan(self):
        items = self.search([])
        CHUNK = 2000
        for start in range(0, len(items), CHUNK):
            items[start:start + CHUNK]._compute_rule_health()
        if hasattr(items, 'flush_recordset'):
            items.flush_recordset()
        else:
            items.flush()
        dead = len(items.filtered(lambda i: i.mh_rule_status == 'unreachable'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pricelists checked'),
                'message': _('%(total)s rules checked, %(dead)s that can never apply.') % {
                    'total': len(items), 'dead': dead},
                'type': 'warning' if dead else 'success',
                'sticky': False,
            },
        }
