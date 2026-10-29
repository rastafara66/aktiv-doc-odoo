# -*- coding: utf-8 -*-
"""Навчальні тури Odoo («краплі»-підказки модуля web_tour) — вимкнено назавжди.

Odoo вмикає їх кожному адміністратору бази без демо-даних, а «Stop tour» їх не прибирає: будь-який тур, запущений
вручну (кнопка, посилання ``?tour=``), вмикає тури користувачу знову (``switch_tour_enabled`` у
``web_tour/static/src/js/tour_service.js``). Тому новому користувачу тури вимкнено, увімкнути їх не можна, а тим,
хто вже є в базі, їх вимикає ``data/tours_off.xml`` — при встановленні й кожному оновленні модуля. ``web_tour``
стоїть у залежностях явно: так цей клас перекриває його методи за будь-якого порядку модулів.
"""
from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.depends('create_date')
    def _compute_tour_enabled(self):
        for user in self:
            user.tour_enabled = False

    @api.model
    def switch_tour_enabled(self, val):
        self.env.user.sudo().tour_enabled = False
        return False

    @api.model
    def _aktiv_doc_tours_off(self):
        self.sudo().with_context(active_test=False).search(
            [('tour_enabled', '=', True)]).write({'tour_enabled': False})
