# -*- coding: utf-8 -*-
"""Звіти до ДПС через Active Doc — із заглушкою сервісу (контракт `3A/active-doc-api.md`,
розділ «Звітність до ДПС»). Підміняється саме HTTP-запит, тож перевіряються й тіло запиту,
і розбір відповідей та відмов кабінету.

Модуль не знає, які звіти бувають, — файли дає той, хто надсилає («Актив»). Тут джерело —
рахунок, а XML — вигадані байти: кабінет-заглушка їх не розбирає. Дані вигадані.
"""
import base64
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.aktiv_doc.models.aktiv_doc_client import AktivDocError
from odoo.addons.aktiv_doc.models.aktiv_doc_report import package_sha
from odoo.addons.aktiv_doc.tests.test_aktiv_doc import FakeAdoc, FakeResponse, HTTP, KEY
from odoo.addons.aktiv_doc.tools.series import attachment_content
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

MAIN = ("16010000000031J0200126100000000110920261601.xml", b"<DECLAR>main</DECLAR>")
ANNEX = ("16010000000031J0200526100000000110920261601.xml", b"<DECLAR>annex</DECLAR>")
BRANCH = ("16010000000031J0500111100000000210920261601.xml", b"<DECLAR>branch</DECLAR>")


class FakeAdocReports(FakeAdoc):
    """Кабінет зі «Звітністю до ДПС»: звіти, вікно звітності, квитанції."""

    def __init__(self, reports_on=True):
        super().__init__()
        self.reports_on = reports_on
        self.reports = {}
        self.receipt_files = {}
        self.report_pages = None

    def report(self, files, **vals):
        self.next_id += 1
        report = {"id": self.next_id, "name": "Податкова декларація з податку на додану вартість",
                  "form": "J0200126", "tin": "00000031", "sti": "1601",
                  "period": {"type": 1, "month": 9, "year": 2026, "label": "вересень 2026"},
                  "doc_stan": 1, "doc_cnt": 1,
                  "files": [{"file_name": f["file_name"], "form": f["file_name"][14:22],
                             "name": "?", "size": 1, "sha256": "ab", "main": i == 0}
                            for i, f in enumerate(files)],
                  "state": "draft", "state_label": "Не надіслано", "dps_id": None,
                  "dps_status": None, "dps_text": None, "sent": None, "reg_number": None,
                  "reg_date": None, "reg_status": None, "receipts": [], "external_ref": None,
                  "created": "2026-10-23T08:00:00Z", "changed": "2026-10-23T08:00:00Z"}
        report.update(vals)
        self.reports[report["id"]] = report
        return report

    def send(self, report_id):
        """Те, що робить вікно: людина надіслала, ДПС прийняла пакет."""
        self.reports[report_id].update(state="sent", state_label="Надіслано до ДПС",
                                       dps_id="40771357730529", dps_status="OK",
                                       sent="2026-10-23T09:00:00Z",
                                       changed="2026-10-23T09:00:00Z")

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        path = url.split("/api/v1/", 1)[1]
        if method == "GET" and path == "me":
            self.calls.append((method, path, headers, json, params))
            return FakeResponse(body={
                "org": {"name": "Тестова організація", "code": "00000031", "test": True,
                        "signs_required": 1, "reports": self.reports_on},
                "plan": {"code": "free", "name": "Безкоштовний", "out_month": 20,
                         "sent_this_month": 0, "until": None},
                "key": {"name": "odoo", "origin": "http://localhost:8070"}})
        if not path.startswith("reports"):
            return super().__call__(method, url, headers, json, params, timeout)
        self.calls.append((method, path, headers, json, params))
        if (method, path) in self.fail:
            return self.fail[(method, path)]
        if not self.reports_on:
            return FakeResponse(403, {"error": "EDPS_OFF", "message": "Звітність не ввімкнено."})
        if method == "POST" and path == "reports":
            report = self.report(json["files"], external_ref=json["external_ref"])
            return FakeResponse(body=report)
        if method == "GET" and path == "reports":
            if self.report_pages:
                return FakeResponse(body=self.report_pages.pop(0))
            return FakeResponse(body={"reports": list(self.reports.values()),
                                      "next": "2026-10-23T10:00:00Z", "more": False})
        parts = path.split("/")
        report = self.reports.get(int(parts[1])) if parts[1].isdigit() else None
        if report is None:
            return FakeResponse(404, {"error": "ENOTFOUND", "message": "Звіт не знайдено."})
        if method == "GET" and len(parts) == 2:
            return FakeResponse(body=report)
        if method == "POST" and parts[2] == "sign_session":
            return FakeResponse(body={
                "url": "https://doc.aktiv.in.ua/embed/report/t%d" % report["id"],
                "expires_in": 1800, "origin": "http://localhost:8070",
                "mode": "send" if report["state"] == "draft" else "receipts"})
        if method == "GET" and parts[2] == "receipts":
            return FakeResponse(content=self.receipt_files[(int(parts[3]), parts[4])])
        return FakeResponse(400, {"error": "EBAD", "message": "Невідомий запит."})


@tagged("post_install", "-at_install")
class TestAktivDocReports(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.invoice = cls.init_invoice("out_invoice", partner=cls.partner_a,
                                       products=[cls.product_a], post=True)
        cls.Report = cls.env["aktiv.doc.report"]

    def setUp(self):
        super().setUp()
        self.adoc = FakeAdocReports()
        patcher = patch(HTTP, side_effect=self.adoc)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env.company.sudo().aktiv_doc_key = KEY

    def submit(self, packages=None, title="Декларація з ПДВ за вересень 2026"):
        return self.Report._aktiv_doc_submit(self.invoice, packages or [[MAIN, ANNEX]], title)

    def calls(self, method, path):
        return [c for c in self.adoc.calls if (c[0], c[1]) == (method, path)]

    # ------------------------------------------------------------------
    def test_submit_passes_the_files_and_opens_the_report_window(self):
        action = self.submit()
        [(_m, _p, headers, payload, _q)] = self.calls("POST", "reports")
        self.assertEqual(headers["X-Adoc-Key"], KEY)
        self.assertEqual([f["file_name"] for f in payload["files"]], [MAIN[0], ANNEX[0]])
        self.assertEqual(base64.b64decode(payload["files"][1]["file"]), ANNEX[1])
        self.assertTrue(payload["external_ref"].endswith("·account.move·%d" % self.invoice.id))
        report = self.Report.search([])
        self.assertEqual(report.state, "draft")
        self.assertEqual(report.source_ref, self.invoice)
        self.assertEqual(report.name, "Декларація з ПДВ за вересень 2026")
        self.assertEqual(report.form, "J0200126")
        self.assertEqual(sorted(report.file_ids.mapped("name")), sorted([MAIN[0], ANNEX[0]]))
        self.assertEqual(report.main_attachment_id.name, MAIN[0])
        self.assertEqual(attachment_content(report.main_attachment_id), MAIN[1])
        # Вікно звітності: чекає «надіслано», а після нього питає сервер, що далі.
        self.assertEqual(action["tag"], "aktiv_doc_sign")
        params = action["params"]
        self.assertEqual(params["url"], "https://doc.aktiv.in.ua/embed/report/t%d" % report.adoc_id)
        self.assertEqual(params["origin"], "https://doc.aktiv.in.ua")
        self.assertEqual(params["message_types"], ["adoc:reported"])
        self.assertEqual((params["refresh_model"], params["refresh_method"]),
                         ("aktiv.doc.report", "action_after_window"))
        self.assertEqual(params["doc_id"], report.id)
        self.assertTrue(self.env.company.aktiv_doc_reports)

    def test_reporting_off_says_how_to_turn_it_on(self):
        self.adoc.reports_on = False
        with self.assertRaises(AktivDocError) as caught:
            self.submit()
        self.assertIn("info@aktiv.in.ua", str(caught.exception))
        self.assertIn("Що зробити:", str(caught.exception))
        self.assertFalse(self.calls("POST", "reports"), "без «Звітності» звіт не передаємо")
        self.assertFalse(self.Report.search([]))

    def test_no_key_no_network(self):
        self.env.company.sudo().aktiv_doc_key = False
        with self.assertRaises(UserError) as caught:
            self.submit()
        self.assertIn("Active Doc не підключено", str(caught.exception))
        self.assertFalse(self.adoc.calls)

    def test_cabinet_refusal_is_shown_as_is(self):
        """Кабінет перевіряє пакет сам (`EREPORT`) — його текст людина бачить дослівно."""
        self.adoc.fail[("POST", "reports")] = FakeResponse(400, {
            "error": "EREPORT", "message": "Бракує додатків, на які посилається головний документ."})
        with self.assertRaises(AktivDocError) as caught:
            self.submit()
        self.assertIn("Бракує додатків", str(caught.exception))
        self.assertEqual(caught.exception.code, "EREPORT")

    def test_same_package_again_reuses_the_draft(self):
        """Видаляти звіти API не вміє: друге «Надіслати» того самого не плодить чернеток."""
        self.submit()
        self.submit()
        self.assertEqual(len(self.calls("POST", "reports")), 1)
        self.assertEqual(len(self.Report.search([])), 1)
        self.assertEqual(self.Report.search([]).package_sha, package_sha([MAIN, ANNEX]))

    def test_after_sending_the_next_package_opens_by_itself(self):
        """Об'єднана з підрозділом — два звіти: надіслали перший, вікно другого — одразу."""
        self.submit([[MAIN, ANNEX], [BRANCH]], title="Об'єднана за вересень 2026")
        first, second = self.Report.search([], order="id")
        self.assertEqual(first.name, "Об'єднана за вересень 2026 — пакет 1 з 2")
        self.assertEqual(first.batch, second.batch)
        self.adoc.send(first.adoc_id)
        action = first.action_after_window()
        self.assertEqual(first.state, "sent")
        self.assertEqual(first.dps_id, "40771357730529")
        self.assertEqual(action["params"]["doc_id"], second.id)
        self.assertTrue(action["params"]["reload"])
        self.adoc.send(second.adoc_id)
        self.assertEqual(second.action_after_window()["tag"], "soft_reload")

    def test_window_closed_without_sending_changes_nothing(self):
        self.submit()
        report = self.Report.search([])
        self.assertEqual(report.action_after_window()["tag"], "soft_reload")
        self.assertEqual(report.state, "draft")

    def test_receipts_land_as_files_and_the_source_is_told(self):
        self.submit()
        report = self.Report.search([])
        self.adoc.send(report.adoc_id)
        self.adoc.reports[report.adoc_id].update(
            state="accepted", state_label="Прийнято ДПС", reg_number="9000123456",
            reg_date="2026-10-23T11:00:00Z", receipts=[
                {"id": 7, "kind": "kvt", "num": 1, "name": "Квитанція № 1",
                 "file_name": MAIN[0], "result": "Документ збережено на центральному рівні",
                 "reg_number": None, "received": "2026-10-23T09:00:01Z", "signed_ok": True,
                 "encrypted": False, "files": ["xml", "signed", "kvt"]},
                {"id": 8, "kind": "kvt", "num": 2, "name": "Квитанція № 2",
                 "file_name": MAIN[0], "result": "Прийнято", "reg_number": "9000123456",
                 "received": "2026-10-23T11:00:00Z", "signed_ok": True, "encrypted": False,
                 "files": ["xml", "pdf"]},
                {"id": 9, "kind": "kvt", "num": 1, "name": "Квитанція № 1",
                 "file_name": ANNEX[0], "result": None, "reg_number": None,
                 "received": "2026-10-23T09:00:02Z", "signed_ok": False, "encrypted": True,
                 "files": ["kvt"]}])
        self.adoc.receipt_files.update({(7, "xml"): b"<kvt1/>", (8, "xml"): b"<kvt2/>",
                                        (8, "pdf"): b"%PDF kvt2"})
        told = []
        with patch.object(type(self.invoice), "_aktiv_doc_report_changed", create=True,
                          side_effect=lambda r: told.append(r.state), autospec=False):
            report.action_refresh()
        self.assertEqual(report.state, "accepted")
        self.assertEqual(report.reg_number, "9000123456")
        self.assertEqual(told, ["accepted"])
        by_id = {r.adoc_receipt_id: r for r in report.receipt_ids}
        self.assertEqual(attachment_content(by_id[7].xml_attachment_id), b"<kvt1/>")
        self.assertEqual(attachment_content(by_id[8].pdf_attachment_id), b"%PDF kvt2")
        # Зашифрована квитанція — без файлів: розшифрує лише ключ клієнта у вікні.
        self.assertFalse(by_id[9].xml_attachment_id)
        self.assertNotIn(("GET", "reports/%d/receipts/9/xml" % report.adoc_id),
                         [(c[0], c[1]) for c in self.adoc.calls])
        # Квитанції — вікно в режимі «квитанції», воно чекає «оновлено».
        action = report.action_receipts_window()
        self.assertEqual(action["params"]["message_types"], ["adoc:report_updated"])

    def test_sent_report_cannot_be_deleted(self):
        self.submit()
        report = self.Report.search([])
        self.adoc.send(report.adoc_id)
        report.action_refresh()
        with self.assertRaises(UserError):
            report.unlink()

    def test_cron_only_where_reporting_is_on(self):
        """Звіт, завантажений у кабінеті, теж з'являється — але лише там, де «Звітність» є."""
        self.adoc.report([{"file_name": MAIN[0]}], name="Податкова декларація з ПДВ")
        self.env.company.aktiv_doc_reports = False
        self.Report._cron_sync()
        self.assertFalse(self.calls("GET", "reports"))
        self.env.company.aktiv_doc_reports = True
        self.Report._cron_sync()
        report = self.Report.search([])
        self.assertEqual(report.name, "Податкова декларація з ПДВ")
        self.assertFalse(report.source_ref)
        self.assertEqual(self.env.company.sudo().aktiv_doc_report_cursor, "2026-10-23T10:00:00Z")

    def test_settings_check_tells_whether_reporting_is_on(self):
        settings = self.env["res.config.settings"].create({"aktiv_doc_key": KEY})
        message = settings.action_aktiv_doc_check()["params"]["message"]
        self.assertIn("Звітність до ДПС через Active Doc: увімкнено", message)
        self.assertTrue(self.env.company.aktiv_doc_reports)
        self.adoc.reports_on = False
        message = settings.action_aktiv_doc_check()["params"]["message"]
        self.assertIn("ще не ввімкнено", message)
        self.assertFalse(self.env.company.aktiv_doc_reports)
