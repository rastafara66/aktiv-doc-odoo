# -*- coding: utf-8 -*-
"""Модуль «Active Doc» із заглушкою сервісу: підміняється саме HTTP-запит (`_http`),
тож перевіряються й заголовок із ключем, і розбір помилок сервісу.

Дані вигадані: коди 12345678 / 87654321, ключ `adk_test`.
"""
import base64
import io
import zipfile
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.aktiv_doc.tools.series import attachment_content, registry_field

HTTP = "odoo.addons.aktiv_doc.models.aktiv_doc_client._http"
PDF = b"%PDF-1.4 test document"
KEY = "adk_test_secret_key"


class FakeResponse:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code = status
        self._body = body
        self.content = content

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeAdoc:
    """Сервіс Active Doc у пам'яті — за контрактом `3A/active-doc-api.md`."""

    def __init__(self):
        self.docs = {}
        self.calls = []
        self.next_id = 100
        self.fail = {}      # (метод, шлях) -> FakeResponse
        self.pages = None   # список відповідей на GET documents (пагінація)

    def doc(self, **vals):
        self.next_id += 1
        doc = {"id": self.next_id, "name": "Документ", "file_name": "doc.pdf", "sha256": "ab",
               "size": 10, "direction": "out", "state": "draft",
               "state_label": "Чернетка, чекає вашого підпису", "sender": {"name": "Ми",
                                                                       "code": "11111111"},
               "recipient": None, "signs_needed": {"sender": 1, "recipient": 1},
               "can_sign": True, "signatures": [], "reject_reason": None,
               "external_ref": None, "created": "2026-10-07T07:00:00Z",
               "changed": "2026-10-07T07:00:00Z"}
        doc.update(vals)
        self.docs[doc["id"]] = doc
        return doc

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        path = url.split("/api/v1/", 1)[1]
        self.calls.append((method, path, headers, json, params))
        if (method, path) in self.fail:
            return self.fail[(method, path)]
        if method == "GET" and path == "me":
            return FakeResponse(body={
                "org": {"name": "Тестова організація", "code": "11111111", "test": True,
                        "signs_required": 1},
                "plan": {"code": "free", "name": "Безкоштовний", "out_month": 20,
                         "sent_this_month": 3, "until": None},
                "key": {"name": "odoo", "origin": "http://localhost:8070"}})
        if method == "POST" and path == "documents":
            doc = self.doc(name=json["name"], file_name=json["file_name"],
                           external_ref=json["external_ref"])
            return FakeResponse(body=doc)
        if method == "GET" and path == "documents":
            if self.pages:
                return FakeResponse(body=self.pages.pop(0))
            return FakeResponse(body={"documents": list(self.docs.values()),
                                      "next": "2026-10-07T08:00:00Z", "more": False})
        parts = path.split("/")
        doc = self.docs.get(int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else None
        if doc is None:
            return FakeResponse(404, {"error": "ENOTFOUND", "message": "Документ не знайдено."})
        action = parts[2] if len(parts) > 2 else None
        if method == "GET" and action is None:
            return FakeResponse(body=doc)
        if method == "POST" and action == "sign_session":
            return FakeResponse(body={"url": "https://doc.aktiv.in.ua/pidpys/t/xyz",
                                      "side": "sender", "expires_in": 600,
                                      "origin": "http://localhost:8070"})
        if method == "POST" and action == "send":
            doc.update(state="sent", state_label="Надіслано, чекає підпису", can_sign=False,
                       recipient={"name": json["name"], "code": json["code"],
                                  "in_cabinet": False})
            return FakeResponse(body=doc)
        if method == "POST" and action == "reject":
            doc.update(state="rejected", state_label="Відхилено", can_sign=False,
                       reject_reason=json["reason"])
            return FakeResponse(body=doc)
        if method == "GET" and action == "file":
            return FakeResponse(content=PDF)
        if method == "GET" and action == "archive":
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("protokol.html", "<p>ok</p>")
            return FakeResponse(content=buffer.getvalue())
        return FakeResponse(400, {"error": "EBAD", "message": "Невідомий запит."})


@tagged("post_install", "-at_install")
class TestAktivDoc(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # ЄДРПОУ — у поле, яке є в серії (в Odoo 20 «Реєстру компанії» немає, код — у `vat`).
        cls.partner_a.write({registry_field(cls.env): "12345678", "email": "buyer@example.com"})
        cls.invoice = cls.init_invoice("out_invoice", partner=cls.partner_a,
                                       products=[cls.product_a], post=True)

    def setUp(self):
        super().setUp()
        self.adoc = FakeAdoc()
        patcher = patch(HTTP, side_effect=self.adoc)
        self.http = patcher.start()
        self.addCleanup(patcher.stop)
        pdf = patch.object(type(self.env["ir.actions.report"]), "_render_qweb_pdf",
                           return_value=(PDF, "pdf"))
        pdf.start()
        self.addCleanup(pdf.stop)

    def connect(self):
        self.env.company.sudo().aktiv_doc_key = KEY

    def wizard(self, record=None):
        record = record or self.invoice
        return self.env["aktiv.doc.send"].with_context(
            default_res_model=record._name, default_res_id=record.id).create({})

    def assert_no_key_in(self, text):
        self.assertNotIn(KEY, text or "")

    # ------------------------------------------------------------------
    def test_no_key_no_button_and_clear_error(self):
        self.assertFalse(self.invoice.aktiv_doc_enabled)
        with self.assertRaises(UserError) as caught:
            self.wizard().action_create()
        self.assertIn("Active Doc не підключено", str(caught.exception))
        self.assertFalse(self.adoc.calls, "без ключа в мережу не ходимо")

    def test_wizard_reports_all_problems_at_once(self):
        draft = self.init_invoice("out_invoice", partner=self.partner_b, products=[self.product_a])
        wizard = self.wizard(draft)
        wizard.recipient_code = "123"
        with self.assertRaises(UserError) as caught:
            wizard.action_create()
        message = str(caught.exception)
        self.assertIn("Знайдено проблем: 3", message)
        for part in ("не підключено", "не проведено", "не ЄДРПОУ і не РНОКПП"):
            self.assertIn(part, message)

    def test_defaults_from_partner(self):
        self.connect()
        wizard = self.wizard()
        self.assertEqual(wizard.recipient_code, "12345678")
        self.assertEqual(wizard.recipient_email, "buyer@example.com")
        self.assertEqual(wizard.report_id, self.env.ref("account.account_invoices"))
        self.assertTrue(self.invoice.aktiv_doc_enabled)

    def test_full_outgoing_cycle(self):
        self.connect()
        action = self.wizard().action_create()
        self.assertEqual(action["tag"], "aktiv_doc_sign")
        self.assertEqual(action["params"]["origin"], "https://doc.aktiv.in.ua")
        self.assertEqual(action["params"]["allowed_origin"], "http://localhost:8070")
        doc = self.env["aktiv.doc.document"].browse(action["params"]["doc_id"])
        self.assertEqual(doc.record_ref, self.invoice)
        self.assertEqual(doc.state, "draft")
        self.assertEqual(doc.counterparty_code, "12345678")
        self.assertEqual(attachment_content(doc.attachment_id), PDF)
        # Ключ — лише в заголовку; запис обліку — у external_ref.
        method, path, headers, payload, params = self.adoc.calls[0]
        self.assertEqual((method, path), ("POST", "documents"))
        self.assertEqual(headers["X-Adoc-Key"], KEY)
        self.assertTrue(payload["external_ref"].endswith("·account.move·%d" % self.invoice.id))
        self.assertEqual(base64.b64decode(payload["file"]), PDF)
        self.assertEqual(self.invoice.aktiv_doc_count, 1)

        # Вікно підпису сказало «підписано» → сервер перепитує Active Doc.
        self.adoc.docs[doc.adoc_id].update(state="signed", state_label="Підписано, можна надіслати",
                                           can_sign=False)
        doc.action_refresh()
        self.assertEqual(doc.state, "signed")
        self.assertEqual(doc.counterparty_code, "12345678",
                         "до «Надіслати» отримувача в Active Doc немає — наш вибір не стирається")
        self.assertIn("Підписано, можна надіслати", self.invoice.message_ids[0].body)

        doc.action_send()
        sent = self.adoc.calls[-1]
        self.assertEqual(sent[1], "documents/%d/send" % doc.adoc_id)
        self.assertEqual(sent[3]["code"], "12345678")
        self.assertEqual(doc.state, "sent")

        # Контрагент підписав — cron забирає зміну й архів.
        self.adoc.docs[doc.adoc_id].update(state="done", state_label="Підписано обома сторонами",
                                           signatures=[{"side": "sender", "name": "Іваненко І.",
                                                        "title": "директор", "org": "Ми",
                                                        "org_code": "11111111",
                                                        "time": "2026-10-07T08:00:00Z",
                                                        "format": "cades-detached",
                                                        "test_key": True}])
        self.env["aktiv.doc.document"]._cron_sync()
        self.assertEqual(doc.state, "done")
        self.assertTrue(doc.archive_id)
        self.assertIn("Іваненко І.", doc.signatures)
        move_archives = self.env["ir.attachment"].search(
            [("res_model", "=", "account.move"), ("res_id", "=", self.invoice.id),
             ("mimetype", "=", "application/zip")])
        self.assertEqual(len(move_archives), 1, "архів лягає й до рахунку")
        self.assertEqual(self.env.company.sudo().aktiv_doc_cursor, "2026-10-07T08:00:00Z")

    def test_sign_refused_when_not_our_turn(self):
        self.connect()
        doc = self.env["aktiv.doc.document"].browse(
            self.wizard().action_create()["params"]["doc_id"])
        self.adoc.docs[doc.adoc_id].update(state="sent", can_sign=False,
                                           state_label="Надіслано, чекає підпису")
        with self.assertRaises(UserError) as caught:
            doc.action_sign()
        self.assertIn("Зараз підписати", str(caught.exception))

    def test_incoming_documents_and_partner_by_code(self):
        self.connect()
        supplier = self.env["res.partner"].create({"name": "Постачальник", "ref": "87654321"})
        first = self.adoc.doc(direction="in", name="Акт 7", state="sent", can_sign=True,
                              sender={"name": "Постачальник", "code": "87654321"},
                              recipient={"name": "Ми", "code": "11111111"})
        second = self.adoc.doc(direction="in", name="Акт 8", state="sent", can_sign=True,
                               sender={"name": "Інший", "code": "22222222"})
        self.adoc.pages = [
            {"documents": [first], "next": "2026-10-07T07:30:00Z", "more": True},
            {"documents": [second], "next": "2026-10-07T07:40:00Z", "more": False},
        ]
        self.env["aktiv.doc.document"]._cron_sync()
        docs = self.env["aktiv.doc.document"].search([("direction", "=", "in")], order="adoc_id")
        self.assertEqual(docs.mapped("name"), ["Акт 7", "Акт 8"])
        self.assertEqual(docs[0].partner_id, supplier)
        self.assertEqual(docs[0].counterparty_code, "87654321")
        self.assertEqual(attachment_content(docs[0].attachment_id), PDF)
        params = [call[4] for call in self.adoc.calls if call[1] == "documents"]
        self.assertEqual(params[1], {"changed_since": "2026-10-07T07:30:00Z"})
        self.assertEqual(self.env.company.sudo().aktiv_doc_cursor, "2026-10-07T07:40:00Z")

        # Відхилити — лише з причиною.
        wizard = self.env["aktiv.doc.reject"].create({"document_id": docs[0].id})
        with self.assertRaises(UserError):
            wizard.action_reject()
        wizard.reason = "Не та сума"
        wizard.action_reject()
        self.assertEqual(docs[0].state, "rejected")
        self.assertEqual(docs[0].reject_reason, "Не та сума")

    def test_inbox_switched_off(self):
        self.connect()
        self.env.company.aktiv_doc_inbox = False
        self.adoc.doc(direction="in", name="Акт 9", sender={"name": "X", "code": "22222222"})
        self.env["aktiv.doc.document"]._cron_sync()
        self.assertFalse(self.env["aktiv.doc.document"].search([("direction", "=", "in")]))

    def test_tariff_limit_message_shown_as_is(self):
        self.connect()
        doc = self.env["aktiv.doc.document"].browse(
            self.wizard().action_create()["params"]["doc_id"])
        self.adoc.docs[doc.adoc_id].update(state="signed", can_sign=False)
        doc.action_refresh()
        self.adoc.fail[("POST", "documents/%d/send" % doc.adoc_id)] = FakeResponse(
            402, {"error": "ELIMIT", "message": "Вичерпано 20 вихідних документів цього місяця. "
                                                "Тариф «Бізнес» — без меж."})
        with self.assertRaises(UserError) as caught:
            doc.action_send()
        message = str(caught.exception)
        self.assertIn("Вичерпано 20 вихідних", message)
        self.assertIn("змініть тариф", message)
        self.assertEqual(caught.exception.code, "ELIMIT")
        self.assert_no_key_in(message)

    def test_network_failure_is_explained(self):
        self.connect()
        self.http.side_effect = requests.ConnectionError("down")
        with self.assertRaises(UserError) as caught:
            self.wizard().action_create()
        self.assertIn("Немає зв'язку з Active Doc", str(caught.exception))
        self.assert_no_key_in(str(caught.exception))
        # Документа без Active Doc не лишається.
        self.assertFalse(self.env["aktiv.doc.document"].search([]))

    def test_cron_survives_one_broken_company(self):
        self.connect()
        self.adoc.fail[("GET", "documents")] = FakeResponse(401, {"error": "EKEY",
                                                                  "message": "Ключ відкликано."})
        self.env["aktiv.doc.document"]._cron_sync()   # не падає

    def test_settings_check_warns_about_origin(self):
        self.env["ir.config_parameter"].sudo().set_str("web.base.url", "https://erp.example.com")
        settings = self.env["res.config.settings"].create({"aktiv_doc_key": KEY})
        result = settings.action_aktiv_doc_check()
        params = result["params"]
        self.assertEqual(params["type"], "warning")
        self.assertIn("Тестова організація", params["message"])
        self.assertIn("вікно підпису тут не відкриється", params["message"])
        self.assertEqual(self.env.company.sudo().aktiv_doc_key, KEY)

        self.env["ir.config_parameter"].sudo().set_str("web.base.url", "http://localhost:8070")
        self.assertEqual(settings.action_aktiv_doc_check()["params"]["type"], "success")

    def test_signed_document_cannot_be_deleted(self):
        self.connect()
        doc = self.env["aktiv.doc.document"].browse(
            self.wizard().action_create()["params"]["doc_id"])
        self.adoc.docs[doc.adoc_id].update(state="signed")
        doc.action_refresh()
        with self.assertRaises(UserError):
            doc.unlink()

    def test_invoice_column_follows_document(self):
        """Колонка «Active Doc» у списку рахунків — за станом останнього документа."""
        self.connect()
        doc = self.env["aktiv.doc.document"].browse(
            self.wizard().action_create()["params"]["doc_id"])
        self.assertEqual(self.invoice.aktiv_doc_state, "waiting")
        self.adoc.docs[doc.adoc_id].update(state="signed", can_sign=False,
                                           state_label="Підписано, не надіслано")
        self.invoice.action_aktiv_doc_refresh()
        self.assertEqual(self.invoice.aktiv_doc_state, "signed")
        self.invoice.action_aktiv_doc_send_signed()      # кнопка в шапці рахунку
        self.assertEqual(self.invoice.aktiv_doc_state, "sent")
        self.adoc.docs[doc.adoc_id].update(state="done")
        self.env["aktiv.doc.document"]._cron_sync()
        self.assertEqual(self.invoice.aktiv_doc_state, "done")
        self.assertEqual(self.env["account.move"].search_count(
            [("id", "=", self.invoice.id), ("aktiv_doc_state", "=", "done")]), 1,
            "поле збережене — список його фільтрує")

    def test_wrong_address_stopped_before_upload(self):
        """Odoo відкрито не з адреси ключа — пояснення ДО завантаження, без чернетки-сироти."""
        self.connect()
        send = type(self.env["aktiv.doc.send"])
        with patch.object(send, "_browser_origin", return_value="http://127.0.0.1:8069"):
            with self.assertRaises(UserError) as caught:
                self.wizard().action_create()
        message = str(caught.exception)
        self.assertIn("http://localhost:8070", message)
        self.assertIn("відкрийте Odoo за адресою", message)
        self.assertEqual([call[1] for call in self.adoc.calls], ["me"],
                         "документ в Active Doc не завантажувався")
        with patch.object(send, "_browser_origin", return_value="http://localhost:8070"):
            self.assertEqual(self.wizard().action_create()["tag"], "aktiv_doc_sign")

    def test_code_with_other_script_digits_rejected(self):
        self.connect()
        wizard = self.wizard()
        wizard.recipient_code = "١٢٣٤٥٦٧٨"   # «١٢٣٤٥٦٧٨»
        with self.assertRaises(UserError) as caught:
            wizard.action_create()
        self.assertIn("не ЄДРПОУ і не РНОКПП", str(caught.exception))

    def test_journal_entry_is_not_a_document(self):
        self.connect()
        entry = self.env["account.move"].create({
            "move_type": "entry",
            "line_ids": [(0, 0, {"account_id": self.company_data["default_account_revenue"].id,
                                 "debit": 10.0}),
                         (0, 0, {"account_id": self.company_data["default_account_expense"].id,
                                 "credit": 10.0})],
        })
        entry.action_post()
        with self.assertRaises(UserError) as caught:
            self.wizard(entry).action_create()
        self.assertIn("бухгалтерська проводка", str(caught.exception))
