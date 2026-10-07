# -*- coding: utf-8 -*-
"""Перевірка версій (§8): серія, числове порівняння, перелік модулів, мовчазні збої."""
import json
import pathlib
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.aktiv_doc.models import aktiv_doc_update as updating


@tagged("post_install", "-at_install")
class TestUpdateCheck(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Update = self.env["aktiv.doc.update"]
        self.installed = self.env["ir.module.module"].search([("name", "=", "aktiv_doc")])
        self.version = self.installed.installed_version
        self.series = updating.series_of(self.version)

    def answer(self, body):
        response = MagicMock()
        response.json.return_value = body
        response.raise_for_status.return_value = None
        return patch("requests.get", return_value=response)

    def test_numbers_not_text(self):
        self.assertGreater(updating.parse_version("19.0.1.0.10"), updating.parse_version("19.0.1.0.9"))

    def test_newer_version_of_own_series_shows_banner(self):
        newer = "%s.99.0.0" % self.series
        with self.answer({"aktiv_doc": newer, "someone_else": "%s.99.0.0" % self.series}) as get:
            ok, _reason = self.Update._run_check()
        self.assertTrue(ok)
        self.assertEqual(get.call_args.kwargs["params"], {"series": self.series})
        self.assertNotIn("someone_else", json.loads(
            self.env["ir.config_parameter"].get_param(updating.PARAM_LATEST)))
        message, url = self.Update.update_banner()
        self.assertIn(newer, message)
        self.assertEqual(url, updating.STORE_URL % (self.series, "aktiv_doc"))
        doc = self.env["aktiv.doc.document"].new({"name": "x"})
        self.assertIn(newer, doc.update_message)

    def test_other_series_ignored(self):
        with self.answer({"aktiv_doc": "1.0.99.0.0"}):
            ok, _reason = self.Update._run_check()
        self.assertFalse(ok)
        self.assertEqual(self.Update.update_banner(), (False, False))

    def test_same_version_no_banner(self):
        with self.answer({"aktiv_doc": self.version}):
            self.Update._run_check()
        self.assertEqual(self.Update.update_banner(), (False, False))

    def test_network_failure_is_silent(self):
        with patch("requests.get", side_effect=OSError("down")):
            self.assertFalse(self.Update._cron_check())

    def test_switched_off(self):
        self.env["ir.config_parameter"].set_param(updating.PARAM_UPDATE_CHECK, "off")
        with patch("requests.get") as get:
            ok, _reason = self.Update._run_check()
        self.assertFalse(ok)
        get.assert_not_called()

    def test_every_module_is_listed(self):
        repo = pathlib.Path(updating.__file__).resolve().parents[2]
        on_disk = {path.parent.name for path in repo.glob("*/__manifest__.py")}
        self.assertFalse(on_disk - set(updating.KNOWN_MODULES),
                         "новий модуль репо не названо в KNOWN_MODULES — його покупці "
                         "не отримуватимуть повідомлень про виправлення")
