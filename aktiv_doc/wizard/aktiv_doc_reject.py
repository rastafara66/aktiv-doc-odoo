# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class AktivDocReject(models.TransientModel):
    _name = "aktiv.doc.reject"
    _description = "Відхилити вхідний документ Active Doc"

    document_id = fields.Many2one("aktiv.doc.document", string="Документ", required=True,
                                  readonly=True, help="Вхідний документ, який відхиляємо.")
    reason = fields.Text("Причина", help="Контрагент побачить її в Active Doc — напишіть, "
                                         "що виправити.")

    def action_reject(self):
        self.ensure_one()
        reason = (self.reason or "").strip()
        if not reason:
            raise UserError(_(
                "Не вказано причину відмови.\n\n"
                "Чому: контрагент має знати, що виправити.\n"
                "Що зробити: напишіть причину в полі «Причина»."))
        self.document_id._reject(reason)
        return {"type": "ir.actions.act_window_close"}
