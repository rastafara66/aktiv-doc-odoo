# -*- coding: utf-8 -*-
from odoo import _, models


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "aktiv.doc.mixin"]

    def _aktiv_doc_problems(self):
        problems = super()._aktiv_doc_problems()
        if self.state != "posted":
            problems.append((
                _("«%s» не проведено", self.display_name),
                _("контрагенту підписують остаточний документ — чернетку ще можуть змінити"),
                _("проведіть документ, тоді надсилайте на підпис")))
        if self.move_type == "entry":
            problems.append((
                _("«%s» — бухгалтерська проводка, а не документ", self.display_name),
                _("на підпис контрагенту йдуть рахунки, акти й накладні"),
                _("відкрийте рахунок, акт чи накладну й надішліть звідти")))
        return problems
