# -*- coding: utf-8 -*-
{
    'name': "Актив Doc — підпис КЕП і обмін документами з контрагентами / "
            "Ukrainian e-signature (KEP) and document exchange",
    'version': '19.0.1.0.0',
    'summary': "Рахунки, акти й накладні підписуються КЕП і йдуть контрагенту "
               "прямо з Odoo, вхідні з'являються самі. Ukrainian qualified "
               "e-signature (KEP), e-document exchange (EDO) with counterparties.",
    'description': """
Актив Doc
=========

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
    # 🔴 Лише штатні модулі: «Актив Doc» — окремий безкоштовний товар, і
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
    'installable': True,
    'application': False,
    'auto_install': False,
}
