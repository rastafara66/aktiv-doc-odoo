# -*- coding: utf-8 -*-
{
    # Англійські ключові слова в назві й summary — свідомо: магазин шукає лише за ними
    # (замір 06.09.2026: український опис знаходиться тільки кирилицею).
    'name': "Active Doc — підпис КЕП і обмін документами з контрагентами / "
            "Ukraine e-signature (KEP) and e-document exchange (EDI)",
    'version': '18.0.1.0.2',
    'summary': "Ukrainian qualified electronic signature (KEP) and e-document exchange "
               "(EDI) for Ukraine: sign invoices, acts and delivery notes and send them to "
               "counterparties without leaving Odoo. Рахунки, акти й накладні підписуються "
               "КЕП і йдуть контрагенту прямо з Odoo.",
    'description': """
Active Doc
==========

Підпис КЕП і обмін первинними документами з контрагентами через сервіс
Active Doc (https://doc.aktiv.in.ua) — не виходячи з Odoo.

* На рахунку, акті, накладній — кнопка «Надіслати на підпис».
* Вікно підпису відкривається всередині Odoo: ключ і пароль не залишають
  сторінку підпису, Odoo їх не бачить.
* Вхідні документи від контрагентів з'являються самі; їх можна підписати чи
  відхилити так само.
* Коли підписали обидві сторони, архів (документ, підписи, протокол
  перевірки) прикріплюється до запису.
""",
    'category': 'Accounting/Accounting',
    'author': "3A Studio",
    'website': "https://doc.aktiv.in.ua",
    'support': "info@aktiv.in.ua",
    'license': 'LGPL-3',
    # 🔴 Лише штатні модулі: «Active Doc» — окремий безкоштовний товар, і
    # «Актив» / «Актив Pro» від нього НЕ залежать (правило надпроєкту: модулі
    # незалежні). Кнопка працює на будь-якому рахунку будь-якої бази.
    'depends': ['account', 'mail'],
    'data': [
        'security/aktiv_doc_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'wizard/aktiv_doc_send_views.xml',
        'wizard/aktiv_doc_reject_views.xml',
        'views/aktiv_doc_document_views.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'aktiv_doc/static/src/js/sign_dialog.js',
            'aktiv_doc/static/src/xml/sign_dialog.xml',
        ],
    },
    # images[0] — картка в каталозі магазину; галерею на сторінці будує index.html.
    'images': [
        'static/description/banner.png',
        'static/description/screenshot_send.png',
        'static/description/screenshot_sign.png',
        'static/description/screenshot_incoming.png',
        'static/description/screenshot_document.png',
        'static/description/screenshot_list.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
