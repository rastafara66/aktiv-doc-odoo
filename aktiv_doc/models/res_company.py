# -*- coding: utf-8 -*-
from odoo import fields, models

from .aktiv_doc_client import DEFAULT_URL


class ResCompany(models.Model):
    _inherit = "res.company"

    # 🔴 Ключ читає лише адміністратор (`base.group_system`): решта бачить
    # тільки, чи Active Doc підключено (`aktiv_doc_enabled`).
    aktiv_doc_key = fields.Char(
        "Ключ API Active Doc", groups="base.group_system", copy=False,
        help="Ключ організації з кабінету Active Doc («Організація» → «Ключі API»). "
             "Показується там один раз; зберігається лише тут і йде лише з сервера "
             "Odoo — у браузер не потрапляє.")
    aktiv_doc_url = fields.Char(
        "Адреса Active Doc", default=DEFAULT_URL, groups="base.group_system",
        help="Адреса сервісу. Змінювати не потрібно — лише для тестового сервера.")
    aktiv_doc_inbox = fields.Boolean(
        "Вхідні з Active Doc", default=True,
        help="Забирати документи, які контрагенти надіслали на код цієї організації, "
             "у меню «Документообіг → Вхідні».")
    aktiv_doc_cursor = fields.Char(
        "Мітка останньої синхронізації", groups="base.group_system", copy=False,
        help="Службове: з якого моменту питати Active Doc про зміни наступного разу.")
    aktiv_doc_enabled = fields.Boolean(
        "Active Doc підключено", compute="_compute_aktiv_doc_enabled",
        help="Чи вставлено ключ API — без нього кнопки «Надіслати на підпис» немає.")

    def _compute_aktiv_doc_enabled(self):
        for company in self:
            company.aktiv_doc_enabled = bool(company.sudo().aktiv_doc_key)
