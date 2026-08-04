# -*- coding: utf-8 -*-
"""Margin Health tests.

Two things have to hold at once and they pull against each other:

  NO LEAKAGE     every route by which an order can lose money must be caught,
                 especially discounts, which are the usual one
  NO FALSE ALARM every legitimate below-cost sale must pass without a murmur,
                 or staff learn to click through the warning and the control is
                 worth nothing
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.margin_check import classify_margin, find_unreachable, margin_percent


@tagged('post_install', '-at_install')
class TestMarginArithmetic(TransactionCase):

    def test_classification(self):
        self.assertEqual(classify_margin(100, 60)[0], 'ok')
        self.assertEqual(classify_margin(50, 80)[0], 'below_cost')
        self.assertEqual(classify_margin(50, 50)[0], 'zero_margin')
        self.assertEqual(classify_margin(100, 97)[0], 'thin')

    def test_zero_cost_is_not_a_hundred_percent_margin(self):
        """A missing cost is an unanswered question, not a perfect margin."""
        self.assertEqual(classify_margin(100, 0)[0], 'no_cost')

    def test_zero_price_gives_no_percentage(self):
        """Dividing by zero is not 0%, it is unanswerable, so it must not be a number."""
        self.assertIsNone(margin_percent(0, 10))

    def test_not_for_sale_is_not_judged(self):
        self.assertEqual(classify_margin(10, 50, sellable=False)[0], 'na')


@tagged('post_install', '-at_install')
class TestPricelistReachability(TransactionCase):

    def _rule(self, rid, **kw):
        base = {'id': rid, 'applied_on': '1_product', 'product_tmpl_id': 7,
                'product_id': False, 'categ_id': False, 'min_quantity': 0,
                'date_start': False, 'date_end': False}
        base.update(kw)
        return base

    def test_a_duplicate_rule_can_never_apply(self):
        dead = find_unreachable([self._rule(1), self._rule(2)])
        self.assertEqual(len(dead), 1, 'exactly one of an identical pair is dead')

    def test_quantity_breaks_are_all_reachable(self):
        """The classic ladder. Every step must survive, or we are lying."""
        rules = [self._rule(1, min_quantity=0),
                 self._rule(2, min_quantity=10),
                 self._rule(3, min_quantity=50)]
        self.assertEqual(find_unreachable(rules), {})

    def test_rules_on_different_products_never_shadow_each_other(self):
        rules = [self._rule(1, product_tmpl_id=7), self._rule(2, product_tmpl_id=8)]
        self.assertEqual(find_unreachable(rules), {})

    def test_a_narrower_date_window_inside_a_wider_one_is_dead(self):
        """Odoo evaluates items by id DESCENDING, so the higher id is reached
        first. The narrow rule is only dead when the wide one is reached first."""
        narrow = self._rule(1, date_start=fields.Date.to_date('2026-01-01'),
                            date_end=fields.Date.to_date('2026-06-30'))
        wide = self._rule(2, date_start=False, date_end=False)
        self.assertIn(1, find_unreachable([narrow, wide]))

    def test_a_narrow_window_reached_first_stays_alive(self):
        """Reversed ids: the narrow rule now wins inside its dates and the wide
        one still applies outside them, so BOTH are reachable."""
        wide = self._rule(1, date_start=False, date_end=False)
        narrow = self._rule(2, date_start=fields.Date.to_date('2026-01-01'),
                            date_end=fields.Date.to_date('2026-06-30'))
        self.assertEqual(find_unreachable([wide, narrow]), {})

    def test_a_wider_window_is_never_shadowed_by_a_narrower_one(self):
        narrow = self._rule(1, date_start=fields.Date.to_date('2026-01-01'),
                            date_end=fields.Date.to_date('2026-06-30'))
        wide = self._rule(2, date_start=False, date_end=False)
        self.assertNotIn(2, find_unreachable([narrow, wide]))

    def test_different_specificity_never_shadows(self):
        """A category rule and a product rule overlap in reality, but proving it
        needs the category tree walked. We only claim what we can prove."""
        rules = [self._rule(1, applied_on='1_product'),
                 self._rule(2, applied_on='2_product_category', categ_id=3,
                            product_tmpl_id=False)]
        self.assertEqual(find_unreachable(rules), {})


@tagged('post_install', '-at_install')
class TestPricelistOnRealRecords(TransactionCase):
    """The pure function was tested with dicts, which hid a crash.

    product.pricelist.item date bounds are a Datetime on some series and a Date
    on others, so comparing them to today raised TypeError on any pricelist that
    actually had dates. Only real records catch that.
    """

    def test_dated_rules_compute_without_crashing(self):
        pl = self.env['product.pricelist'].create({'name': 'Dated'})
        product = self.env['product.template'].create(
            {'name': 'Dated product', 'list_price': 10.0})
        item = self.env['product.pricelist.item'].create({
            'pricelist_id': pl.id,
            'applied_on': '1_product',
            'product_tmpl_id': product.id,
            'compute_price': 'percentage',
            'percent_price': 10,
            'date_end': '2020-12-31 00:00:00',
        })
        item._compute_rule_health()
        self.assertEqual(item.mh_rule_status, 'expired')

    def test_a_future_rule_is_reported_as_not_started(self):
        pl = self.env['product.pricelist'].create({'name': 'Future'})
        product = self.env['product.template'].create(
            {'name': 'Future product', 'list_price': 10.0})
        item = self.env['product.pricelist.item'].create({
            'pricelist_id': pl.id,
            'applied_on': '1_product',
            'product_tmpl_id': product.id,
            'compute_price': 'percentage',
            'percent_price': 10,
            'date_start': '2099-01-01 00:00:00',
        })
        item._compute_rule_health()
        self.assertEqual(item.mh_rule_status, 'future')

    def test_a_duplicate_rule_on_real_records_is_flagged(self):
        pl = self.env['product.pricelist'].create({'name': 'Dupes'})
        product = self.env['product.template'].create(
            {'name': 'Dupe product', 'list_price': 10.0})
        vals = {'pricelist_id': pl.id, 'applied_on': '1_product',
                'product_tmpl_id': product.id, 'compute_price': 'percentage',
                'percent_price': 5, 'min_quantity': 0}
        a = self.env['product.pricelist.item'].create(dict(vals))
        b = self.env['product.pricelist.item'].create(dict(vals, percent_price=12))
        (a | b)._compute_rule_health()
        statuses = (a.mh_rule_status, b.mh_rule_status)
        self.assertIn('unreachable', statuses,
                      'one of two identical rules can never apply')


@tagged('post_install', '-at_install')
class TestOrderEnforcement(TransactionCase):

    def setUp(self):
        # Instance level, not setUpClass: cls.env only exists from Odoo 15, and
        # this module supports 14.
        super().setUp()
        self.company = self.env.company
        self.company.write({
            'mh_enforce_mode': 'block',
            'mh_check_level': 'both',
            'mh_min_margin_percent': 0.0,
            'mh_min_margin_amount': 0.0,
        })
        self.customer = self.env['res.partner'].create({'name': 'Margin Test Co'})

    def _product(self, name, price, cost, **kw):
        return self.env['product.template'].create(
            dict(name=name, list_price=price, standard_price=cost, **kw))

    def _order(self, product, qty=1, price=None, discount=0.0, **order_vals):
        vals = dict(partner_id=self.customer.id)
        vals.update(order_vals)
        order = self.env['sale.order'].create(vals)
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': product.product_variant_id.id,
            'product_uom_qty': qty,
            'price_unit': price if price is not None else product.list_price,
            'discount': discount,
        })
        return order

    # ---------------- leakage ----------------

    def test_a_losing_order_is_blocked(self):
        p = self._product('Loser', 50, 80)
        order = self._order(p)
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_a_discount_that_eats_the_margin_is_caught(self):
        """The main leak. The price looks fine; the discount is what loses money."""
        p = self._product('Discounted', 100, 90)
        order = self._order(p, discount=30.0)   # 70 net against a 90 cost
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_a_percentage_floor_is_enforced_not_just_a_loss(self):
        self.company.mh_min_margin_percent = 25.0
        p = self._product('Thin', 100, 85)      # 15%, above water but under floor
        order = self._order(p)
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_a_healthy_order_confirms(self):
        p = self._product('Healthy', 100, 40)
        order = self._order(p)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    # ---------------- false alarms ----------------

    def test_a_product_with_no_cost_never_blocks(self):
        """Otherwise every uncosted product stops the business trading."""
        p = self._product('Uncosted', 100, 0)
        order = self._order(p)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_a_free_line_never_blocks(self):
        p = self._product('Sample', 100, 40)
        order = self._order(p, price=0.0)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_a_deliberate_loss_leader_never_blocks(self):
        p = self._product('Loss leader', 50, 80, mh_loss_leader=True)
        order = self._order(p)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_an_exempt_category_never_blocks(self):
        categ = self.env['product.category'].create({'name': 'Clearance'})
        self.company.mh_excluded_categ_ids = [(6, 0, [categ.id])]
        p = self._product('Clearing', 50, 80, categ_id=categ.id)
        order = self._order(p)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_an_exempt_customer_never_blocks(self):
        self.company.mh_excluded_partner_ids = [(6, 0, [self.customer.id])]
        p = self._product('Staff sale', 50, 80)
        order = self._order(p)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_section_lines_are_ignored(self):
        p = self._product('Fine', 100, 40)
        order = self._order(p)
        self.env['sale.order.line'].create({
            'order_id': order.id, 'display_type': 'line_section', 'name': 'Section',
        })
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    # ---------------- enforcement modes ----------------

    def test_off_never_interrupts(self):
        self.company.mh_enforce_mode = 'off'
        p = self._product('Loser off', 50, 80)
        order = self._order(p)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_warn_allows_but_records_it(self):
        self.company.mh_enforce_mode = 'warn'
        p = self._product('Loser warn', 50, 80)
        order = self._order(p)
        before = len(order.message_ids)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertGreater(len(order.message_ids), before,
                           'an override must leave a trace on the order')

    def _grant(self, xmlid):
        """res.users.groups_id was renamed group_ids in Odoo 19."""
        gid = self.env.ref(xmlid).id
        field = 'group_ids' if 'group_ids' in self.env.user._fields else 'groups_id'
        self.env.user.write({field: [(4, gid)]})

    def test_override_group_can_confirm_and_it_is_logged(self):
        self._grant('miko_margin_health.group_margin_override')
        p = self._product('Loser override', 50, 80)
        order = self._order(p)
        before = len(order.message_ids)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertGreater(len(order.message_ids), before)

    def test_line_level_only_ignores_a_healthy_total(self):
        """One bad line inside a profitable order still gets caught at line level."""
        self.company.mh_check_level = 'line'
        good = self._product('Good', 1000, 100)
        bad = self._product('Bad', 10, 90)
        order = self._order(good)
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': bad.product_variant_id.id,
            'product_uom_qty': 1,
            'price_unit': 10,
        })
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_order_level_only_allows_a_bad_line_in_a_profitable_order(self):
        self.company.mh_check_level = 'order'
        good = self._product('Good2', 1000, 100)
        bad = self._product('Bad2', 10, 90)
        order = self._order(good)
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': bad.product_variant_id.id,
            'product_uom_qty': 1,
            'price_unit': 10,
        })
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_margin_figures_are_stored_on_the_line(self):
        p = self._product('Figures', 100, 40)
        order = self._order(p, qty=2)
        line = order.order_line[0]
        self.assertEqual(line.mh_unit_cost, 40)
        self.assertEqual(line.mh_margin, 120)      # 200 revenue - 80 cost
        self.assertAlmostEqual(line.mh_margin_percent, 60.0, places=2)
