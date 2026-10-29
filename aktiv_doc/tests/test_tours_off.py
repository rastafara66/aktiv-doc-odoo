# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestToursOff(TransactionCase):
    """Навчальні тури Odoo: наявним користувачам їх вимикає встановлення й оновлення модуля, тур,
    запущений вручну, їх не вмикає, новому користувачу їх немає."""

    def test_tours_stay_off(self):
        admin = self.env.ref("base.user_admin")
        admin.tour_enabled = True
        self.env["res.users"]._aktiv_doc_tours_off()
        self.assertFalse(admin.tour_enabled, "наявним користувачам тури вимикає встановлення й оновлення модуля")
        self.assertFalse(self.env["res.users"].with_user(admin).switch_tour_enabled(True))
        self.assertFalse(admin.tour_enabled, "тур, запущений вручну, не вмикає тури знову")
        admin._compute_tour_enabled()
        self.assertFalse(admin.tour_enabled, "новому користувачу турів немає")
        self.assertFalse(self.env["web_tour.tour"].with_user(admin).get_current_tour(), "автоматичного тура немає")
