# -*- coding: utf-8 -*-
"""Наскрізна перевірка «Звітів до ДПС»: «Актив» → «Надіслати до ДПС» → вікно Active Doc на живому
https://doc.aktiv.in.ua → підпис тестовим ключем → «Надіслано до ДПС», квитанції, реєстр подання.

    python tools/e2e_reports.py                       # «Актив» — з теки ../aktiv поруч із репо
    python tools/e2e_reports.py --aktiv C:/Users/chukhin/Projects/aktiv-dps
    python tools/e2e_reports.py --keep                # базу не видаляти (для розбору)

Тестова організація Active Doc «Тестова база «Актив Doc» А» (00000031): «Звітність до ДПС»
увімкнено, і до ДПС вона НІЧОГО не надсилає — вікно складає й підписує справжні пакети, кабінет
їх перевіряє (`check_package`: LINKED_DOCS, назви з шапок, код платника), а відповідь ДПС
імітує: `dps_id` «TEST-<id>» (3A `active-doc-api.md`, «Звітність до ДПС»).

Секрети — ті самі, що в `e2e_aktiv_doc.py` (gitignored `e2e.local/`); у worktree гілки їх
немає — тоді беруться з основної теки репо (`../aktiv-doc-odoo/e2e.local`).

Шлях:
  1. база з account + aktiv_doc + l10n_ua_aktiv, план рахунків України, рахунок постачальника
     з ПДВ 20 % → декларація з ПДВ за місяць: пакет «декларація + Додаток 1»;
  2. «Надіслати до ДПС» на формі декларації → вікно звітності Active Doc усередині Odoo;
  3. підпис тестовим ключем, «Я перевірив…», «Підписати й надіслати» → вікно закрилось саме;
  4. звіт «Надіслано до ДПС» (TEST-…), два файли — головний і Д1; табличка над декларацією;
     запис реєстру подання — «Подано», файл = поданий головний документ.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

import e2e_aktiv_doc as base

ORG_A, CODE_A = base.ORG_A, base.CODE_A
DB = "tmp_adoc_e2e_reports"


def make_db(aktiv):
    no_demo = "--without-demo=all" if base.SERIES == "18.0" else "--without-demo"
    subprocess.run(base.odoo_cmd("-d", DB, "-i", "account,aktiv_doc,l10n_ua_aktiv",
                                 "--load-language=uk_UA", no_demo, "--stop-after-init",
                                 "--log-level=warn"),
                   check=True, env=base.odoo_env(), stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=3600)


def setup(key):
    """Організація А з ключем, план рахунків України, рахунок постачальника з ПДВ за вересень."""
    s = base.Session(DB)
    company = s.call("res.users", "read", [2], ["company_id"])[0]["company_id"][0]
    registry = "company_registry" if s.call("res.partner", "fields_get", ["company_registry"]) \
        else "vat"
    ukraine = s.call("res.country", "search", [("code", "=", "UA")], limit=1)
    uah = s.call("res.currency", "search", [("name", "=", "UAH"), ("active", "in", [True, False])],
                 limit=1)
    s.call("res.currency", "write", uah, {"active": True})
    s.call("res.company", "write", [company], {
        "name": ORG_A, registry: CODE_A, "aktiv_doc_key": key, "country_id": ukraine[0],
        "currency_id": uah[0], "street": "вул. Тестова, 1", "city": "Київ", "zip": "01001",
        "l10n_ua_tin": CODE_A, "l10n_ua_c_reg": "16", "l10n_ua_c_raj": "01",
        "l10n_ua_c_sti_orig": "1601"})
    s.set_system_param("web.base.url", base.URL)
    s.call("res.users", "write", [2], {"lang": "uk_UA", "tz": "Europe/Kyiv"})
    # `try_loading` — метод записів (не @api.model): першим аргументом RPC — порожні ids.
    s.call("account.chart.template", "try_loading", [], "ua_psbo", company, install_demo=False)
    tax = s.call("account.tax", "search", [("type_tax_use", "=", "purchase"), ("amount", "=", 20),
                                           ("company_id", "=", company)], limit=1)
    vendor = s.call("res.partner", "create", {"name": "Постачальник (тест)", "is_company": True,
                                              "vat": "098765432109"})
    bill = s.call("account.move", "create", {
        "move_type": "in_invoice", "partner_id": vendor, "invoice_date": "2026-09-10",
        "date": "2026-09-10", "invoice_line_ids": [(0, 0, {
            "name": "Папір офісний", "quantity": 1, "price_unit": 1000.0,
            "tax_ids": [(6, 0, tax)]})]})
    s.call("account.move", "action_post", [bill])
    vat = s.call("l10n_ua.vat.return", "create", {
        "company_id": company, "date_from": "2026-09-01", "date_to": "2026-09-30",
        "tin": CODE_A, "ipn": "123456789012", "c_reg": "16", "c_raj": "01",
        "c_sti_orig": "1601", "hloc": "м. Київ, вул. Тестова, 1",
        "hsti": "ГУ ДПС у м. Києві", "boss_name": "Іван Тестовий", "boss_tin": "1234567890",
        "use_first_event": False})
    s.call("l10n_ua.vat.return", "action_compute", [vat])
    return s, company, vat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aktiv", default=str(base.REPO.parent / "aktiv"),
                    help="тека з модулями «Актива» (типово ../aktiv; гілка — її worktree)")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--port", type=int, default=8075, choices=(8070, 8075))
    args = ap.parse_args()
    base.PORT, base.URL = args.port, "http://localhost:%d" % args.port
    # Перевіряємо САМЕ ці теки: Odoo бере модуль з першої теки шляху, де він є, а в
    # C:\odoo19\custom_addons лежать «Активи» основної гілки (23.10.2026 перший прогін так і
    # перевірив стару форму без «Надіслати до ДПС»). Тому «Актив» і цей репо — першими.
    base.ADDONS = ",".join([str(pathlib.Path(args.aktiv).resolve()), str(base.REPO),
                            base.ADDONS])
    if not (base.SECRETS / "api-keys-local-dev.json").exists():
        base.SECRETS = base.REPO.parent / "aktiv-doc-odoo" / "e2e.local"
    keys = json.load(open(base.SECRETS / "api-keys-local-dev.json", encoding="utf-8"))["orgs"]
    field = "key" if base.PORT == 8070 else "key_%d" % base.PORT
    key = keys[ORG_A][field]
    password = (base.SECRETS / "PASSWORD.txt").read_text(encoding="utf-8").strip()
    if base.port_open(base.PORT):
        print("🔴 порт %d зайнятий — на ньому вже щось працює" % base.PORT)
        return 2
    check = base.check

    print("0. Чиста база з account + aktiv_doc + l10n_ua_aktiv («Актив» з %s)" % args.aktiv)
    make_db(args.aktiv)
    server = subprocess.Popen(base.odoo_cmd("--max-cron-threads=0", "--http-port=%d" % base.PORT,
                                            "--db-filter=^%s$" % DB,
                                            "--logfile=" + str(base.LOG)), env=base.odoo_env(),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _i in range(120):
            if base.port_open(base.PORT):
                break
            time.sleep(1)
        s, company, vat = setup(key)
        if not check(bool(s.call("l10n_ua.vat.return", "fields_get", ["dps_adoc_state"])),
                     "«Актив» завантажено з %s (є «Надіслати до ДПС»)" % args.aktiv):
            raise RuntimeError("Odoo взяв «Актив» не з %s — дивіться порядок шляху модулів"
                               % args.aktiv)
        me = s.call("res.config.settings", "action_aktiv_doc_check",
                    s.call("res.config.settings", "create", {}))
        check("Звітність до ДПС через Active Doc: увімкнено" in me["params"]["message"],
              "«Перевірити з'єднання»: звітність до ДПС увімкнено")
        s.call("l10n_ua.vat.return", "action_export_xml", [vat])
        names = s.call("l10n_ua.vat.return", "read", [vat], ["xml_filename", "annex1_filename"])[0]
        check(names["xml_filename"] and names["annex1_filename"],
              "декларація з ПДВ: пакет із двох файлів — %s, %s"
              % (names["xml_filename"], names["annex1_filename"]))

        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch()
            print("1. Декларація з ПДВ → «Надіслати до ДПС» → вікно звітності")
            ctx, page = base.login(browser, DB)
            page.goto("%s/odoo/action-l10n_ua_aktiv.action_ua_vat_return/%d" % (base.URL, vat))
            page.locator(".o_form_sheet").wait_for(timeout=120000)
            page.get_by_role("button", name="Надіслати до ДПС").click()
            page.locator(".o_aktiv_doc_sign_frame").wait_for(timeout=120000)
            report = s.call("aktiv.doc.report", "search_read",
                            [("source_ref", "=", "l10n_ua.vat.return,%d" % vat)],
                            fields=["id", "adoc_id", "state", "file_ids", "form"])
            check(len(report) == 1 and report[0]["state"] == "draft"
                  and len(report[0]["file_ids"]) == 2 and report[0]["form"] == "J0200126",
                  "звіт в Active Doc №%s — чернетка, два файли, форма J0200126 (кабінет прийняв "
                  "пакет: LINKED_DOCS, назви, код платника)" % (report and report[0]["adoc_id"]))

            print("2. Підпис тестовим ключем А і надсилання")
            frame = page.frame_locator(".o_aktiv_doc_sign_frame")
            for _i in range(180):
                if frame.locator("#status").inner_text().strip() == "":
                    break
                time.sleep(0.5)
            check(frame.locator("#adoc-no-email").count() == 0,
                  "у вікні є пошта для ДПС (інакше кнопка надсилання вимкнена)")
            frame.locator("#key").set_input_files(str(base.SECRETS / "Key-6.dat"))
            frame.locator("#certs").set_input_files([str(base.SECRETS / "test-signer.cer")])
            frame.locator("#password").fill(password)
            frame.locator("#read-key:enabled").wait_for(timeout=90000)
            frame.locator("#read-key").click()
            frame.locator("#signer", has_text="Ключ зчитано").wait_for(timeout=60000)
            frame.locator("#confirm").check()
            frame.locator("#send:enabled").wait_for(timeout=30000)
            frame.locator("#send").click()
            page.locator(".o_aktiv_doc_sign_frame").wait_for(state="detached", timeout=180000)
            page.get_by_text("оновлюю стан звіту").wait_for(state="hidden", timeout=120000)
            got = s.call("aktiv.doc.report", "read", [report[0]["id"]],
                         ["state", "state_label", "dps_id", "dps_status"])[0]
            check(got["state"] == "sent" and (got["dps_id"] or "").startswith("TEST-"),
                  "вікно закрилось саме; «%s», номер %s (тестова — до ДПС не надсилала)"
                  % (got["state_label"], got["dps_id"]))

            print("3. Стан над декларацією й реєстр подання")
            page.locator(".o_form_sheet").wait_for(timeout=60000)
            banner = page.locator(".alert", has_text="Подання до ДПС:")
            check(banner.count() >= 1 and "Надіслано до ДПС" in banner.first.inner_text(),
                  "над декларацією — «Подання до ДПС: Надіслано до ДПС»")
            check(page.get_by_role("button", name="Надіслати до ДПС").count() == 0,
                  "кнопки «Надіслати до ДПС» більше немає — надіслане не надсилається вдруге")
            sub = s.call("l10n_ua.submission", "search_read",
                         [("source_ref", "=", "l10n_ua.vat.return,%d" % vat)],
                         fields=["state", "xml_filename", "submitted_on"])
            check(len(sub) == 1 and sub[0]["state"] == "submitted"
                  and sub[0]["xml_filename"] == names["xml_filename"],
                  "реєстр подання: «Подано» %s, файл %s" % (
                      sub and sub[0]["submitted_on"], sub and sub[0]["xml_filename"]))
            ctx.close()
            browser.close()
        except Exception:
            for index, opened in enumerate(base.PAGES):
                try:
                    path = base.SECRETS / ("fail-reports-%d.png" % index)
                    opened.screenshot(path=str(path))
                    print("  знімок падіння: %s (%s)" % (path, opened.url))
                except Exception:  # noqa: BLE001 — сторінку вже могли закрити
                    pass
            raise
        finally:
            pw.stop()
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
        if not args.keep:
            subprocess.run([sys.executable, str(base.THREE_A / "tools" / "ops" / "db_classes.py"),
                            "drop", "--site", base.SITE, DB], stdout=subprocess.DEVNULL)
    print("\n✅ «Звіти до ДПС»: наскрізно пройдено" if not base.problems
          else "\n🔴 «Звіти до ДПС»: не пройдено %d" % len(base.problems))
    return 1 if base.problems else 0


if __name__ == "__main__":
    sys.exit(main())
