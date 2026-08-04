# -*- coding: utf-8 -*-
{
    'name': 'Margin Control & Sold Below Cost Alert (Miko)',
    'version': '14.0.1.0.0',
    'summary': 'Stop orders that lose money, on your own margin rules',
    'description': """
Set the margin your business actually needs, then have Odoo enforce it at the
moment a sales order is confirmed rather than discovering the loss a month later.
Also audits products priced below cost and finds pricelist rules that can never
apply because another rule shadows them.
""",
    'author': 'Tripster Developers',
    'website': 'https://tripsterdevelopers.com/odoo/',
    'category': 'Accounting',
    'license': 'OPL-1',
    'depends': ['product', 'sale'],
    'data': [
        'security/margin_health_security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/miko_margin_health_views.xml',
    ],
    'price': 49.00,
    'currency': 'USD',
    'images': ['images/banner.gif', 'images/banner.png'],
    'application': True,
    'installable': True,
    'support': 'support@tripsterdevelopers.com',
}
