# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .margin_check import margin_percent


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    mh_unit_cost = fields.Float(
        string='Unit Cost', compute='_compute_mh_margin', store=True,
        digits='Product Price',
        help="The cost this line's margin is measured against, taken from the "
             "cost basis set for the company.")
    mh_margin = fields.Float(
        string='Margin', compute='_compute_mh_margin', store=True,
        digits='Product Price',
        help="Line subtotal minus cost. Discounts are already inside the subtotal, "
             "so a discount that eats the margin shows up here.")
    mh_margin_percent = fields.Float(
        string='Margin %', compute='_compute_mh_margin', store=True, digits=(16, 2))
    mh_below_floor = fields.Boolean(
        string='Below margin floor', compute='_compute_mh_margin', store=True,
        help="This line does not clear the company's margin rules.")

    def _mh_cost(self):
        """Unit cost under the company's chosen basis, in the order's currency."""
        self.ensure_one()
        company = self.order_id.company_id or self.env.company
        product = self.product_id
        if not product:
            return 0.0
        cost = product.standard_price or 0.0
        if company.mh_cost_basis == 'supplier' and product.seller_ids:
            prices = [s.price for s in product.seller_ids if s.price]
            if prices:
                cost = min(prices)
        # standard_price is held in the company currency; the order may not be.
        order_currency = self.order_id.currency_id
        company_currency = company.currency_id
        if order_currency and company_currency and order_currency != company_currency:
            cost = company_currency._convert(
                cost, order_currency, company,
                self.order_id.date_order or fields.Date.context_today(self))
        return cost

    def _mh_is_checkable(self):
        """Lines the margin rules must never judge.

        Getting this list wrong is what turns a control into something staff
        route around, so each exclusion below is a case where a flag would be
        simply wrong rather than merely inconvenient.
        """
        self.ensure_one()
        company = self.order_id.company_id or self.env.company

        # Section and note lines carry no product and no money.
        if self.display_type:
            return False
        # Down payment lines are an accounting device, not a sale of goods.
        if getattr(self, 'is_downpayment', False):
            return False
        if not self.product_id:
            return False
        # A product nobody sells has no margin to judge.
        if 'sale_ok' in self.product_id._fields and not self.product_id.sale_ok:
            return False
        # Deliberate exemptions set by the business.
        if self.product_id.mh_loss_leader:
            return False
        if self.product_id.categ_id and \
                self.product_id.categ_id in company.mh_excluded_categ_ids:
            return False
        # Cannot judge what has no cost. On by default: without it every
        # uncosted product would block every order.
        if company.mh_ignore_zero_cost and not self._mh_cost():
            return False
        if company.mh_ignore_zero_price and not self.price_subtotal:
            return False
        return True

    @api.depends('product_id', 'product_uom_qty', 'price_subtotal', 'price_unit',
                 'discount', 'order_id.company_id', 'order_id.currency_id')
    def _compute_mh_margin(self):
        for line in self:
            company = line.order_id.company_id or line.env.company
            cost = line._mh_cost() if line.product_id and not line.display_type else 0.0
            total_cost = cost * (line.product_uom_qty or 0.0)
            margin = (line.price_subtotal or 0.0) - total_cost
            percent = margin_percent(line.price_subtotal, total_cost)

            line.mh_unit_cost = cost
            line.mh_margin = margin
            line.mh_margin_percent = percent if percent is not None else 0.0

            below = False
            if line._mh_is_checkable():
                if margin < company.mh_min_margin_amount:
                    below = True
                if percent is not None and percent < company.mh_min_margin_percent:
                    below = True
                # A loss is always a breach, whatever the thresholds say.
                if margin < 0:
                    below = True
            line.mh_below_floor = below


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mh_margin = fields.Float(
        string='Order Margin', compute='_compute_mh_order_margin', store=True,
        digits='Product Price')
    mh_margin_percent = fields.Float(
        string='Order Margin %', compute='_compute_mh_order_margin', store=True,
        digits=(16, 2))
    mh_below_floor = fields.Boolean(
        string='Below margin floor', compute='_compute_mh_order_margin', store=True,
        help="Set when this order breaks the company's margin rules, at whichever "
             "level the company measures.")

    @api.depends('order_line.mh_margin', 'order_line.mh_below_floor',
                 'order_line.price_subtotal', 'company_id')
    def _compute_mh_order_margin(self):
        for order in self:
            company = order.company_id or order.env.company
            lines = order.order_line.filtered(lambda l: not l.display_type)
            margin = sum(lines.mapped('mh_margin'))
            revenue = sum(lines.mapped('price_subtotal'))
            percent = margin_percent(revenue, revenue - margin)

            order.mh_margin = margin
            order.mh_margin_percent = percent if percent is not None else 0.0

            if order._mh_is_exempt():
                order.mh_below_floor = False
                continue

            bad = False
            level = company.mh_check_level
            if level in ('line', 'both'):
                bad = bad or any(lines.mapped('mh_below_floor'))
            if level in ('order', 'both'):
                checkable = lines.filtered(lambda l: l._mh_is_checkable())
                if checkable:
                    if percent is not None and percent < company.mh_min_margin_percent:
                        bad = True
                    if margin < 0:
                        bad = True
            order.mh_below_floor = bad

    def _mh_is_exempt(self):
        """Whole orders the business has chosen not to police."""
        self.ensure_one()
        company = self.company_id or self.env.company
        if self.partner_id and self.partner_id in company.mh_excluded_partner_ids:
            return True
        if self.pricelist_id and self.pricelist_id in company.mh_excluded_pricelist_ids:
            return True
        return False

    def _mh_violations(self):
        """Human readable lines explaining exactly what breaks the rules."""
        self.ensure_one()
        company = self.company_id or self.env.company
        out = []
        for line in self.order_line.filtered(lambda l: l.mh_below_floor):
            out.append(_("%(product)s: margin %(margin).2f (%(pct).1f%%)") % {
                'product': line.product_id.display_name or '',
                'margin': line.mh_margin,
                'pct': line.mh_margin_percent,
            })
        if company.mh_check_level in ('order', 'both') and self.mh_below_floor:
            out.append(_("Order total: margin %(margin).2f (%(pct).1f%%), floor is %(floor).1f%%") % {
                'margin': self.mh_margin,
                'pct': self.mh_margin_percent,
                'floor': company.mh_min_margin_percent,
            })
        return out

    def action_confirm(self):
        """Check the margin at the one moment it can still be changed.

        A report tells you about the loss next month. This refuses to let it
        happen, unless someone with the authority to accept it says so, and then
        records that they did.
        """
        for order in self:
            company = order.company_id or order.env.company
            if company.mh_enforce_mode == 'off' or order._mh_is_exempt():
                continue
            order._compute_mh_order_margin()
            if not order.mh_below_floor:
                continue

            detail = "\n".join("- %s" % v for v in order._mh_violations())
            if company.mh_enforce_mode == 'block' and not self.env.user.has_group(
                    'miko_margin_health.group_margin_override'):
                raise UserError(_(
                    "This order does not meet the margin your company requires.\n\n"
                    "%(detail)s\n\n"
                    "Adjust the prices, or ask someone with margin override rights "
                    "to confirm it."
                ) % {'detail': detail})

            # Warned, or overridden by an authorised user: allowed through, and
            # written into the record so the decision is answerable for later.
            order.message_post(body=_(
                "<b>Confirmed below the margin floor</b><br/>%(detail)s"
            ) % {'detail': detail.replace("\n", "<br/>")})
        return super().action_confirm()
