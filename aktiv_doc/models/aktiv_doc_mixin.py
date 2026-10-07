# -*- coding: utf-8 -*-
"""Запис обліку, який можна надіслати на підпис: кнопка, лічильник, стан.

Модель підключає домішку `_inherit` — і отримує все разом. У цій версії —
рахунки, акти й накладні (`account.move`); інші документи (акт звірки тощо)
підключаються тим самим рядком у модулі, де вони живуть.
"""
from collections import defaultdict

from odoo import _, fields, models


class AktivDocMixin(models.AbstractModel):
    _name = "aktiv.doc.mixin"
    _description = "Документ обліку, який можна надіслати на підпис через Active Doc"

    aktiv_doc_count = fields.Integer(
        "Документів Active Doc", compute="_compute_aktiv_doc",
        help="Скільки разів цей запис надсилали на підпис через Active Doc.")
    aktiv_doc_state_label = fields.Char(
        "Підпис КЕП", compute="_compute_aktiv_doc",
        help="Стан останнього документа Active Doc із цього запису.")
    aktiv_doc_enabled = fields.Boolean(
        "Active Doc підключено", compute="_compute_aktiv_doc",
        help="Чи підключено Active Doc для організації запису — без цього кнопки немає.")

    def _aktiv_doc_company(self):
        self.ensure_one()
        return self.company_id if "company_id" in self._fields and self.company_id \
            else self.env.company

    def _compute_aktiv_doc(self):
        refs = ["%s,%s" % (self._name, rid) for rid in self.ids]
        by_ref = defaultdict(list)
        if refs:
            for doc in self.env["aktiv.doc.document"].search([("record_ref", "in", refs)],
                                                             order="id desc"):
                by_ref["%s,%s" % (doc.record_ref._name, doc.record_ref.id)].append(doc)
        for record in self:
            mine = by_ref.get("%s,%s" % (record._name, record.id), [])
            record.aktiv_doc_count = len(mine)
            record.aktiv_doc_state_label = (mine[0].state_label or mine[0].state) if mine else False
            record.aktiv_doc_enabled = bool(record.id) and \
                record._aktiv_doc_company().aktiv_doc_enabled

    def _aktiv_doc_partner(self):
        """Кому надсилати — комерційний контрагент запису, якщо він є."""
        self.ensure_one()
        partner = self.partner_id if "partner_id" in self._fields else self.env["res.partner"]
        return partner.commercial_partner_id if partner else partner

    def _aktiv_doc_problems(self):
        """Чому запис ще не можна надіслати: [(що, чому, що зробити)]. Розширюють моделі."""
        return []

    def action_aktiv_doc_send(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Надіслати на підпис"),
            "res_model": "aktiv.doc.send",
            "view_mode": "form",
            "target": "new",
            "context": {"default_res_model": self._name, "default_res_id": self.id},
        }

    def action_aktiv_doc_open(self):
        self.ensure_one()
        docs = self.env["aktiv.doc.document"].search(
            [("record_ref", "=", "%s,%s" % (self._name, self.id))])
        action = {
            "type": "ir.actions.act_window",
            "name": _("Active Doc: %s", self.display_name),
            "res_model": "aktiv.doc.document",
            "context": {"create": False},
        }
        if len(docs) == 1:
            action.update(view_mode="form", res_id=docs.id)
        else:
            action.update(view_mode="list,form", domain=[("id", "in", docs.ids)])
        return action
