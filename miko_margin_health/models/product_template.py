# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from .margin_check import classify_margin, MARGIN_STATUS, THIN_MARGIN_PCT


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    mh_margin_status = fields.Selection(
        MARGIN_STATUS, string='Margin Check', compute='_compute_margin_health',
        store=True, index=True,
        help="How the list price compares with the cost. A product priced under "
             "its cost loses money on every order and Odoo never warns you.")
    mh_margin_amount = fields.Float(
        string='Margin', compute='_compute_margin_health', store=True,
        digits='Product Price',
        help="Sales price minus cost, per unit.")
    mh_margin_percent = fields.Float(
        string='Margin %', compute='_compute_margin_health', store=True,
        digits=(16, 2),
        help="Margin as a percentage of the selling price, the way retail quotes it.")
    mh_is_healthy = fields.Boolean(
        string='Margin OK', compute='_compute_margin_health', store=True, index=True)
    mh_loss_leader = fields.Boolean(
        string='Sold below cost on purpose',
        help="Tick for a product you deliberately sell at or below cost, such as a "
             "loss leader or a contractual item. It is left out of the margin rules "
             "entirely and never blocks an order.")

    @api.depends('list_price', 'standard_price', 'sale_ok', 'mh_loss_leader')
    def _compute_margin_health(self):
        for tmpl in self:
            # A product that is not for sale has no margin to judge. Flagging one
            # would be the same false positive as asking a service for a barcode.
            sellable = tmpl.sale_ok if 'sale_ok' in tmpl._fields else True
            if tmpl.mh_loss_leader:
                sellable = False  # deliberate, so there is nothing to report
            status, amount, percent = classify_margin(
                tmpl.list_price, tmpl.standard_price, sellable=sellable)
            tmpl.mh_margin_status = status
            tmpl.mh_margin_amount = amount if amount is not None else 0.0
            tmpl.mh_margin_percent = percent if percent is not None else 0.0
            # Only losing or making nothing counts. A thin margin and a missing
            # cost are reported so they can be seen, never held against anyone:
            # loss leaders and uncosted items are legitimate.
            tmpl.mh_is_healthy = status not in ('below_cost', 'zero_margin')

    @api.model
    def action_margin_health_rescan(self):
        products = self.search([])
        CHUNK = 2000
        for start in range(0, len(products), CHUNK):
            products[start:start + CHUNK]._compute_margin_health()
        if hasattr(products, 'flush_recordset'):
            products.flush_recordset()
        else:
            products.flush()
        losing = len(products.filtered(lambda p: p.mh_margin_status == 'below_cost'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Margins checked'),
                'message': _('%(total)s products checked, %(bad)s priced below cost.') % {
                    'total': len(products), 'bad': losing},
                'type': 'warning' if losing else 'success',
                'sticky': False,
            },
        }
