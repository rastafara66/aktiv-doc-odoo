# -*- coding: utf-8 -*-
from odoo import _, fields, models

from .aktiv_doc_client import origin_of as _origin_of


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    aktiv_doc_key = fields.Char(
        related="company_id.aktiv_doc_key", readonly=False, groups="base.group_system",
        help="Ключ організації з кабінету Active Doc («Організація» → «Ключі API»).")
    aktiv_doc_url = fields.Char(
        related="company_id.aktiv_doc_url", readonly=False, groups="base.group_system",
        help="Адреса сервісу. Змінювати не потрібно — лише для тестового сервера.")
    aktiv_doc_inbox = fields.Boolean(
        related="company_id.aktiv_doc_inbox", readonly=False,
        help="Забирати документи, які контрагенти надіслали на код цієї організації.")

    def action_aktiv_doc_check(self):
        """«Перевірити з'єднання» — `GET me`: хто ми, тариф, залишок, адреса вбудовування."""
        self.ensure_one()
        company = self.company_id
        # Зберігаємо введене: людина тисне «Перевірити» одразу після вставки ключа.
        company.sudo().write({
            "aktiv_doc_key": (self.aktiv_doc_key or "").strip() or False,
            "aktiv_doc_url": (self.aktiv_doc_url or "").strip() or False,
            "aktiv_doc_inbox": self.aktiv_doc_inbox,
        })
        me = self.env["aktiv.doc.client"]._request(company, "GET", "me")
        org, plan, key = me.get("org") or {}, me.get("plan") or {}, me.get("key") or {}
        lines = [_("Організація: %(name)s, код %(code)s%(test)s.",
                   name=org.get("name") or "?", code=org.get("code") or "?",
                   test=_(" (тестова — приймає лише тестові ключі КЕП)") if org.get("test") else "")]
        if plan:
            lines.append(_("Тариф «%(plan)s»: цього місяця надіслано %(sent)s з %(limit)s%(until)s.",
                           plan=plan.get("name") or plan.get("code") or "?",
                           sent=plan.get("sent_this_month", "?"), limit=plan.get("out_month", "?"),
                           until=_(", діє до %s", plan["until"]) if plan.get("until") else ""))
        if org.get("signs_required") and org["signs_required"] > 1:
            lines.append(_("Документи організації підписують %s особи.", org["signs_required"]))
        notice_type = "success"
        allowed = _origin_of(key.get("origin"))
        ours = _origin_of(self.env["ir.config_parameter"].sudo().get_str("web.base.url"))
        if allowed and ours and allowed != ours:
            notice_type = "warning"
            lines.append(_(
                "Увага: ключ дозволяє відкривати вікно підпису лише з %(allowed)s, а ця база "
                "працює на %(ours)s — вікно підпису тут не відкриється. Що зробити: у кабінеті "
                "Active Doc вкажіть для ключа адресу %(ours)s (або створіть новий ключ із нею).",
                allowed=allowed, ours=ours))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("З'єднання з Active Doc є"),
                "message": "\n".join(lines),
                "type": notice_type,
                "sticky": notice_type != "success",
            },
        }
