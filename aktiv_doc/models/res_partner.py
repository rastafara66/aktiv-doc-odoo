# -*- coding: utf-8 -*-
from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    aktiv_doc_partner_count = fields.Integer(
        "Документів Active Doc", compute="_compute_aktiv_doc_partner_count",
        help="Скільки документів Active Doc надіслано цьому контрагенту чи отримано від нього.")

    def _compute_aktiv_doc_partner_count(self):
        counts = {}
        if self.ids:
            rows = self.env["aktiv.doc.document"]._read_group(
                [("partner_id", "in", self.ids)], groupby=["partner_id"], aggregates=["__count"])
            counts = {partner.id: count for partner, count in rows}
        for partner in self:
            partner.aktiv_doc_partner_count = counts.get(partner.id, 0)

    def action_aktiv_doc_open(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Active Doc: %s", self.display_name),
            "res_model": "aktiv.doc.document",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"create": False},
        }
