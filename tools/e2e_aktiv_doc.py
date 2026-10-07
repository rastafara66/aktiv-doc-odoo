# -*- coding: utf-8 -*-
"""Наскрізна перевірка «Актив Doc» на живому https://doc.aktiv.in.ua — так, як це робить людина.

    python tools/e2e_aktiv_doc.py            # дві тимчасові бази, Odoo на :8070, браузер без вікна
    python tools/e2e_aktiv_doc.py --keep     # бази не видаляти (для розбору)

Тестові організації Active Doc «Тестова база «Актив Doc» А» (00000031) і «Б» (00000032),
ключі API видано під http://localhost:8070 — тому Odoo тут слухає саме цей порт.

Секрети — лише в gitignored `e2e.local/` поруч із репо (з VPS, `active-doc/.secrets` і
`samples/test-keys`): `api-keys-local-dev.json`, тестові ключі КЕП `Key-6*.dat`,
сертифікати `*.cer`, `PASSWORD.txt`. У git, у журнал і на екран вони не потрапляють.

Шлях:
  1. А: проведений рахунок організації Б → «Надіслати на підпис» → «Підписати» → вікно
     Active Doc усередині Odoo;
  2. підроблене «adoc:signed» з адреси самої бази (не doc.aktiv.in.ua) вікно ІГНОРУЄ;
  3. підпис тестовим ключем у вікні → вікно закрилось саме, стан «Підписано»;
  4. «Надіслати» → Б: «Оновити зараз» → вхідний документ → «Підписати» у вікні Б;
  5. А: «Оновити зараз» → «Підписано обома сторонами», архів (два підписи) — у рахунку.
"""
import argparse
import io
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request
import http.cookiejar
import zipfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO = pathlib.Path(__file__).resolve().parent.parent
SECRETS = REPO / "e2e.local"
ODOO = pathlib.Path(os.environ.get("ODOO_ROOT", r"C:\odoo19"))
PY = ODOO / ".venv" / "Scripts" / "python.exe"
ADDONS = ",".join([str(ODOO / "odoo" / "addons"), str(ODOO / "custom_addons"),
                   str(ODOO / "my_addons"), str(REPO)])
URL = "http://localhost:8070"
DB_A, DB_B = "tmp_adoc_e2e_a", "tmp_adoc_e2e_b"
ORG_A, ORG_B = "Тестова база «Актив Doc» А", "Тестова база «Актив Doc» Б"
CODE_A, CODE_B = "00000031", "00000032"
LOG = REPO / "e2e.local" / "odoo-e2e.log"

problems = []


def check(cond, what):
    print(("  ✔ " if cond else "  🔴 ") + what)
    if not cond:
        problems.append(what)
    return cond


def odoo_env():
    env = dict(os.environ)
    env["PATH"] = str(ODOO / "wkhtmltox" / "bin") + os.pathsep + env.get("PATH", "")
    return env


def odoo_cmd(*args):
    return [str(PY), str(ODOO / "odoo-bin"), "-c", str(ODOO / "odoo.conf"),
            "--addons-path=" + ADDONS, *args]


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


class Session:
    """JSON-RPC від імені admin у вибраній базі — як браузер, без XML-RPC."""

    def __init__(self, db):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.rpc("/web/session/authenticate", {"db": db, "login": "admin", "password": "admin"})

    def rpc(self, path, params):
        body = json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}).encode()
        request = urllib.request.Request(URL + path, data=body,
                                         headers={"Content-Type": "application/json"})
        reply = json.load(self.opener.open(request, timeout=180))
        if "error" in reply:
            raise RuntimeError((reply["error"].get("data") or {}).get("message")
                               or reply["error"].get("message"))
        return reply["result"]

    def call(self, model, method, *args, **kwargs):
        return self.rpc("/web/dataset/call_kw/%s/%s" % (model, method),
                        {"model": model, "method": method, "args": list(args), "kwargs": kwargs})


def make_db(db):
    subprocess.run(odoo_cmd("-d", db, "-i", "account,aktiv_doc", "--stop-after-init",
                            "--log-level=warn"), check=True, env=odoo_env(),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800)


def setup_db(db, org, code, key, other_org, other_code):
    s = Session(db)
    company = s.call("res.users", "read", [2], ["company_id"])[0]["company_id"][0]
    s.call("res.company", "write", [company], {"name": org, "company_registry": code,
                                               "aktiv_doc_key": key})
    s.call("ir.config_parameter", "set_param", "web.base.url", URL)
    partner = s.call("res.partner", "create", {"name": other_org, "is_company": True,
                                               "company_registry": other_code})
    return s, company, partner


def sign_in_window(page, key_file, cert_file, password):
    """Підпис у вікні Active Doc, вбудованому в наш діалог."""
    frame = page.frame_locator(".o_aktiv_doc_sign_frame")
    frame.locator("#key").set_input_files(str(key_file))
    frame.locator("#certs").set_input_files([str(cert_file)])
    frame.locator("#password").fill(password)
    frame.locator("#read-key:enabled").wait_for(timeout=90000)
    frame.locator("#read-key").click()
    frame.locator("#signer", has_text="Ключ зчитано").wait_for(timeout=60000)
    frame.locator("#sign:enabled").wait_for(timeout=30000)
    frame.locator("#sign").click()
    # Наше вікно закривається само, щойно Active Doc сказав «adoc:signed».
    page.locator(".o_aktiv_doc_sign_frame").wait_for(state="detached", timeout=120000)


def login(browser, db):
    ctx = browser.new_context(locale="uk-UA", viewport={"width": 1400, "height": 1300})
    page = ctx.new_page()
    page.goto("%s/web/login?db=%s" % (URL, db))
    page.fill("input[name=login]", "admin")
    page.fill("input[name=password]", "admin")
    page.click("button[type=submit]")
    page.wait_for_url("**/odoo**", timeout=120000)
    return ctx, page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    keys = json.load(open(SECRETS / "api-keys-local-dev.json", encoding="utf-8"))["orgs"]
    key_a, key_b = keys[ORG_A]["key"], keys[ORG_B]["key"]
    password = (SECRETS / "PASSWORD.txt").read_text(encoding="utf-8").strip()
    if port_open(8070):
        print("🔴 порт 8070 зайнятий — зупиніть свій Odoo на час перевірки")
        return 2

    print("0. Дві чисті бази з account + aktiv_doc")
    for db in (DB_A, DB_B):
        make_db(db)
    server = subprocess.Popen(odoo_cmd("--max-cron-threads=0", "--http-port=8070",
                                       "--logfile=" + str(LOG)), env=odoo_env(),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _i in range(120):
            if port_open(8070):
                break
            time.sleep(1)
        a, _company_a, partner_b = setup_db(DB_A, ORG_A, CODE_A, key_a, ORG_B, CODE_B)
        b, _company_b, _partner_a = setup_db(DB_B, ORG_B, CODE_B, key_b, ORG_A, CODE_A)
        move = a.call("account.move", "create", {
            "move_type": "out_invoice", "partner_id": partner_b,
            "invoice_line_ids": [(0, 0, {"name": "Консультаційні послуги", "quantity": 1,
                                         "price_unit": 1000.0})]})
        a.call("account.move", "action_post", [move])
        me = a.call("res.config.settings", "action_aktiv_doc_check",
                    a.call("res.config.settings", "create", {}))
        check(me["params"]["type"] == "success" and ORG_A in me["params"]["message"],
              "А: «Перевірити з'єднання» — %s" % me["params"]["message"].splitlines()[0])

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            print("1. А: рахунок → «Надіслати на підпис» → вікно підпису")
            ctx_a, page = login(browser, DB_A)
            page.goto("%s/odoo/action-account.action_move_out_invoice_type/%d" % (URL, move))
            page.get_by_role("button", name="Надіслати на підпис").click()
            dialog = page.locator(".modal")
            dialog.get_by_role("button", name="Підписати").click()
            page.locator(".o_aktiv_doc_sign_frame").wait_for(timeout=60000)
            doc = a.call("aktiv.doc.document", "search_read", [("record_ref", "=",
                                                                "account.move,%d" % move)],
                         fields=["id", "adoc_id", "state"])[0]
            check(doc["state"] == "draft", "документ в Active Doc №%s, чернетка" % doc["adoc_id"])

            print("2. Підроблене «підписано» з адреси бази — ігнорується")
            page.evaluate("id => window.postMessage({type: 'adoc:signed', id: id}, '*')",
                          doc["adoc_id"])
            time.sleep(3)
            check(page.locator(".o_aktiv_doc_sign_frame").count() == 1,
                  "вікно підпису не закрилось від повідомлення з чужого origin")

            print("3. Підпис тестовим ключем А")
            sign_in_window(page, SECRETS / "Key-6.dat", SECRETS / "test-signer.cer", password)
            state = a.call("aktiv.doc.document", "read", [doc["id"]], ["state", "state_label"])[0]
            check(state["state"] == "signed", "вікно закрилось саме; стан: «%s»"
                  % state["state_label"])

            print("4. «Надіслати» → Б отримує й підписує")
            page.wait_for_timeout(2000)
            page.get_by_role("button", name="Надіслати", exact=True).click()
            page.wait_for_timeout(3000)
            state = a.call("aktiv.doc.document", "read", [doc["id"]], ["state", "state_label",
                                                                       "in_cabinet"])[0]
            check(state["state"] == "sent" and state["in_cabinet"],
                  "надіслано в кабінет Б: «%s»" % state["state_label"])
            b.call("aktiv.doc.document", "action_sync_now")
            incoming = b.call("aktiv.doc.document", "search_read",
                              [("adoc_id", "=", doc["adoc_id"])],
                              fields=["id", "direction", "can_sign", "partner_id",
                                      "attachment_id"])
            check(incoming and incoming[0]["direction"] == "in" and incoming[0]["can_sign"]
                  and incoming[0]["attachment_id"],
                  "Б: вхідний документ з'явився, файл є, можна підписати")
            ctx_b, page_b = login(browser, DB_B)
            page_b.goto("%s/odoo/action-aktiv_doc.action_aktiv_doc_incoming/%d"
                        % (URL, incoming[0]["id"]))
            page_b.get_by_role("button", name="Підписати").click()
            page_b.locator(".o_aktiv_doc_sign_frame").wait_for(timeout=60000)
            sign_in_window(page_b, SECRETS / "Key-6-b.dat",
                           SECRETS / "test-signer-b-signup.cer", password)
            state_b = b.call("aktiv.doc.document", "read", [incoming[0]["id"]],
                             ["state", "state_label"])[0]
            check(state_b["state"] == "done", "Б підписав: «%s»" % state_b["state_label"])

            print("5. А: підписано обома, архів у рахунку")
            a.call("aktiv.doc.document", "action_sync_now")
            state = a.call("aktiv.doc.document", "read", [doc["id"]],
                           ["state", "state_label", "archive_id", "signatures"])[0]
            check(state["state"] == "done" and state["archive_id"],
                  "А: «%s», архів є" % state["state_label"])
            zips = a.call("ir.attachment", "search_read",
                          [("res_model", "=", "account.move"), ("res_id", "=", move),
                           ("mimetype", "=", "application/zip")], fields=["id"])
            check(len(zips) == 1, "архів прикріплено до рахунку")
            if zips:
                raw = a.call("ir.attachment", "read", [zips[0]["id"]], ["datas"])[0]["datas"]
                import base64
                names = zipfile.ZipFile(io.BytesIO(base64.b64decode(raw))).namelist()
                check(len([n for n in names if ".sign" in n]) == 2 and "protokol.html" in names,
                      "в архіві два підписи й протокол (%d файлів)" % len(names))
            ctx_a.close()
            ctx_b.close()
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
        if not args.keep:
            three_a = pathlib.Path(os.environ.get("THREE_A", r"C:\Users\chukhin\Projects\adealer"))
            subprocess.run([sys.executable, str(three_a / "tools" / "ops" / "db_classes.py"),
                            "drop", DB_A, DB_B], stdout=subprocess.DEVNULL)
    print("\n✅ «Актив Doc»: наскрізно пройдено" if not problems
          else "\n🔴 «Актив Doc»: не пройдено %d" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
