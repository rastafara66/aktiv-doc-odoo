# -*- coding: utf-8 -*-
"""Наскрізна перевірка «Active Doc» на живому https://doc.aktiv.in.ua — так, як це робить людина.

    python tools/e2e_aktiv_doc.py            # дві тимчасові бази, свій Odoo на :8075, браузер без вікна
    python tools/e2e_aktiv_doc.py --port 8070  # на старих ключах (порт робочого Odoo — зупинити його)
    python tools/e2e_aktiv_doc.py --keep     # бази не видаляти (для розбору)

Тестові організації Active Doc «Тестова база «Актив Doc» А» (00000031) і «Б» (00000032).
Ключ API прив'язаний до адреси Odoo, тож порт — частина ключа: під http://localhost:8070
(поле `key`) і, з 07.10.2026, під http://localhost:8075 (поле `key_8075`). Типово — 8075:
на 8070 живе робочий локальний Odoo, і перевірка на ньому мусила його зупиняти.

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
import re
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
# Серія — з маніфесту гілки, що лежить на диску: 19.0 ганяється збіркою C:\odoo19, 18.0 —
# C:\Odoo\odoo18. Конфіг (постгрес, порт 8070, data_dir) — один, від 19: служба 18 ходить у
# постгрес користувачем, якого в локальному кластері немає.
SERIES = ".".join(re.search(r"'version':\s*'([0-9]+\.[0-9]+)",
                            (REPO / "aktiv_doc" / "__manifest__.py").read_text("utf-8"))
                  .group(1).split(".")[:2])
CONF = pathlib.Path(r"C:\odoo19\odoo.conf")
THREE_A = pathlib.Path(os.environ.get("THREE_A", r"C:\Users\chukhin\Projects\adealer"))
#: Підключення до постгресу й майданчик `db_classes` — як у 3A `run_module_tests.SERIES_DB`:
#: Odoo 20 хоче PostgreSQL ≥ 16, а робочий кластер — 15, тож для 20.0 окремий на 5434.
DB_ARGS, SITE = [], "local"
if SERIES == "18.0":
    ODOO = pathlib.Path(os.environ.get("ODOO_ROOT", r"C:\Odoo\odoo18\server"))
    PY = ODOO.parent / "python" / "python.exe"
    STOCK = [ODOO / "odoo" / "addons"]
    WKHTMLTOPDF = ODOO.parent / "thirdparty"
elif SERIES == "20.0":
    ODOO = pathlib.Path(os.environ.get("ODOO_ROOT", r"C:\Odoo\odoo20\server"))
    PY = ODOO.parent / ".venv" / "Scripts" / "python.exe"
    STOCK = [ODOO / "odoo" / "addons"]
    # Своєї wkhtmltopdf збірка 20 не має — та сама, що в 19.
    WKHTMLTOPDF = pathlib.Path(r"C:\odoo19\wkhtmltox\bin")
    DB_ARGS, SITE = ["--db_host=127.0.0.1", "--db_port=5434", "--db_user=odoo"], "local20"
else:
    ODOO = pathlib.Path(os.environ.get("ODOO_ROOT", r"C:\odoo19"))
    PY = ODOO / ".venv" / "Scripts" / "python.exe"
    STOCK = [ODOO / "odoo" / "addons", ODOO / "custom_addons", ODOO / "my_addons"]
    WKHTMLTOPDF = ODOO / "wkhtmltox" / "bin"
ADDONS = ",".join([str(p) for p in STOCK] + [str(REPO)])
PORT = 8075                       # перевизначає `--port` у main()
URL = "http://localhost:%d" % PORT
DB_A, DB_B = "tmp_adoc_e2e_a", "tmp_adoc_e2e_b"
ORG_A, ORG_B = "Тестова база «Актив Doc» А", "Тестова база «Актив Doc» Б"
CODE_A, CODE_B = "00000031", "00000032"
LOG = REPO / "e2e.local" / "odoo-e2e.log"

problems = []
#: Обрив з'єднання з локальним сервером — як `CONN_LOST` у 3A `tools/ops/walk_menus.py`.
#: Причину знайдено 09.10.2026 (3A PITFALLS §4): великий буфер одним `send()` на цій машині
#: рвався ~60% (переклади ~0,5 МБ після входу). Лікує шар `odoo_win` (сокет частинами, див.
#: `odoo_env()`); повтор лишається сіткою, і кількість повторів друкується.
CONN_LOST = re.compile(r"ERR_CONNECTION_RESET|Failed to fetch|ConnectionLostError")
CONN_TRIES = 3


def check(cond, what):
    print(("  ✔ " if cond else "  🔴 ") + what)
    if not cond:
        problems.append(what)
    return cond


def odoo_env():
    env = dict(os.environ)
    env["PATH"] = str(WKHTMLTOPDF) + os.pathsep + env.get("PATH", "")
    if os.name == "nt":
        # Шар 3A `tools/ops/odoo_win/sitecustomize.py` (той самий, що в run_module_tests):
        # велика відповідь — у сокет частинами (одним записом на цій машині рвалась ~60%:
        # переклади після входу, вигляди рахунків), а файли вкладень Odoo 20 «лише для
        # читання» видаляються, як на Linux.
        shim = str(THREE_A / "tools" / "ops" / "odoo_win")
        env["PYTHONPATH"] = os.pathsep.join(p for p in (shim, env.get("PYTHONPATH")) if p)
    return env


def odoo_cmd(*args):
    return [str(PY), str(ODOO / "odoo-bin"), "-c", str(CONF),
            "--addons-path=" + ADDONS, *DB_ARGS, *args]


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

    def set_system_param(self, key, value):
        """Системний параметр: `set_param` (Odoo 18/19) чи `set_str` (Odoo 20) — за тим, що є
        в базі. Конвертер серії переписує виклики в коді, а назву методу рядком у RPC — ні."""
        try:
            return self.call("ir.config_parameter", "set_param", key, value)
        except RuntimeError as error:
            if "does not exist" not in str(error):
                raise
            return self.call("ir.config_parameter", "set_str", key, value)


def make_db(db):
    # Українська — як у всієї лінійки «Актив»: інакше кнопки Odoo англійські поруч
    # із нашими українськими, і знімки магазину виходять мішаниною мов.
    # Без демо-даних: у 18 вони ставляться типово, і з демо-проводками Odoo вже не дає
    # змінити валюту компанії. Прапорець різний: у 19 і 20 `--without-demo` — булевий
    # («all» він читає як помилку), у 18 — список модулів, `=all`.
    no_demo = "--without-demo=all" if SERIES == "18.0" else "--without-demo"
    subprocess.run(odoo_cmd("-d", db, "-i", "account,aktiv_doc", "--load-language=uk_UA",
                            no_demo, "--stop-after-init", "--log-level=warn"), check=True,
                   env=odoo_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=1800)


def setup_db(db, org, code, key, other_org, other_code):
    s = Session(db)
    company = s.call("res.users", "read", [2], ["company_id"])[0]["company_id"][0]
    # ЄДРПОУ — у поле, яке є в серії: в Odoo 20 `company_registry` немає ні в компанії, ні в
    # контакта, код — у `vat` (як `aktiv_doc/tools/series.py::registry_field`).
    registry = "company_registry" if s.call("res.partner", "fields_get", ["company_registry"]) \
        else "vat"
    s.call("res.company", "write", [company], {"name": org, registry: code,
                                               "aktiv_doc_key": key})
    s.set_system_param("web.base.url", URL)
    s.call("res.users", "write", [2], {"lang": "uk_UA", "tz": "Europe/Kyiv"})
    # Україна й гривня — до першого документа (потім валюту компанії Odoo не змінить):
    # інакше в PDF на знімку «Сполучені Штати» і «$».
    ukraine = s.call("res.country", "search", [("code", "=", "UA")], limit=1)
    uah = s.call("res.currency", "search", [("name", "=", "UAH"), ("active", "in", [True, False])],
                 limit=1)
    s.call("res.currency", "write", uah, {"active": True})
    s.call("res.company", "write", [company], {"country_id": ukraine[0], "currency_id": uah[0]})
    partner = s.call("res.partner", "create", {"name": other_org, "is_company": True,
                                               registry: other_code})
    return s, company, partner


SHOTS = None   # тека для знімків магазину (--shots); None — не знімати
PAGES = []     # усі сторінки браузера — знімаються, якщо прогін упав


def shot(page, name):
    """Кадр для картки магазину: 256 кольорів (стискаємо кольорами, не розміром)."""
    if not SHOTS:
        return
    from PIL import Image
    path = os.path.join(SHOTS, name)
    page.wait_for_timeout(1500)
    page.screenshot(path=path)
    Image.open(path).convert("RGB").quantize(colors=256).save(path, optimize=True)
    print("     знімок %s" % name)


def sign_in_window(page, key_file, cert_file, password, shot_name=None):
    """Підпис у вікні Active Doc, вбудованому в наш діалог."""
    frame = page.frame_locator(".o_aktiv_doc_sign_frame")
    frame.locator("#key").set_input_files(str(key_file))
    frame.locator("#certs").set_input_files([str(cert_file)])
    frame.locator("#password").fill(password)
    frame.locator("#read-key:enabled").wait_for(timeout=90000)
    frame.locator("#read-key").click()
    frame.locator("#signer", has_text="Ключ зчитано").wait_for(timeout=60000)
    if shot_name:
        shot(page, shot_name)
    frame.locator("#sign:enabled").wait_for(timeout=30000)
    frame.locator("#sign").click()
    # Наше вікно закривається само, щойно Active Doc сказав «adoc:signed».
    page.locator(".o_aktiv_doc_sign_frame").wait_for(state="detached", timeout=120000)


def login(browser, db, base=None):
    # Не `base=URL`: значення за замовчуванням береться в момент `def`, а порт
    # (і з ним URL) задає `--port` уже в main().
    base = base or URL
    ctx = browser.new_context(locale="uk-UA", viewport={"width": 1400, "height": 1300})
    page = ctx.new_page()
    PAGES.append(page)
    # Порожня сторінка без навбару нічого не каже — збираємо, що сказав сам браузер.
    errors = []
    page.on("pageerror", lambda exc: errors.append("JS: %s" % exc))
    page.on("console", lambda msg: errors.append("console.error: %s" % msg.text)
            if msg.type == "error" else None)
    page.on("requestfailed", lambda req: errors.append("запит %s %s: %s" % (
        req.method, req.url.replace(base, ""), req.failure)))
    # Вхід — JSON-RPC-ом у контексті браузера (кука сесії спільна з його вкладками), а не
    # формою: перевіряємо підпис, а не сторінку входу. Форма в Odoo 18 рендериться
    # прихованою (її відкриває JS), і натискання «Вхід» на свіжій базі там двічі не
    # надіслало нічого — прогін висів на сторінці входу.
    reply = ctx.request.post(base + "/web/session/authenticate", data={
        "jsonrpc": "2.0", "method": "call",
        "params": {"db": db, "login": "admin", "password": "admin"}}, timeout=120000)
    body = reply.json()
    if body.get("error"):
        raise RuntimeError("вхід у %s: %s" % (db, (body["error"].get("data") or {}).get("message")
                                               or body["error"].get("message")))
    # Перший захід у свіжу базу збирає ассети бекенда — у 18 ~40 с, довше за типові 30 с
    # `goto`, що чекає подію load. Тож чекаємо DOM, а готовність — за навбаром.
    page.goto(base + "/odoo", wait_until="domcontentloaded", timeout=180000)
    # 🔴 Локальний Odoo на Windows зрідка рве з'єднання (3A PITFALLS §4): обірвався один
    # запит старту — веб-клієнт не монтується, сторінка лишається порожньою назавжди
    # (09.10.2026: двічі з трьох прогонів на 19, щоразу на іншій базі; у журналі сервера —
    # лише 200). Як і 3A `walk_menus.py`: такий вхід повторюємо, а кількість повторів
    # друкуємо — нестабільність видно, а не сховано.
    seen = []
    for attempt in range(CONN_TRIES):
        deadline = time.time() + 180
        while time.time() < deadline:
            if page.locator(".o_main_navbar").is_visible():
                if attempt:
                    print("  (вхід у %s: повторів після обриву з'єднання: %d; обірвалось: %s)"
                          % (db, attempt, " | ".join(e[:200] for e in seen[:3])))
                return ctx, page
            if any(CONN_LOST.search(e) for e in errors):
                break
            page.wait_for_timeout(1000)
        else:
            break
        seen, errors[:] = list(errors), []
        if attempt + 1 < CONN_TRIES:
            page.reload(wait_until="domcontentloaded", timeout=180000)
    print("  🔴 інтерфейс %s не змонтувався; браузер сказав: %s"
          % (db, " | ".join(e[:300] for e in (errors or seen)[:6]) or "нічого"))
    raise RuntimeError("інтерфейс %s не змонтувався" % db)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--shots", help="тека для знімків картки магазину (static/description)")
    ap.add_argument("--port", type=int, default=8075, choices=(8070, 8075),
                    help="порт, під який видано ключі (типово 8075 — поруч із робочим Odoo)")
    args = ap.parse_args()
    global SHOTS, PORT, URL
    SHOTS = args.shots
    PORT, URL = args.port, "http://localhost:%d" % args.port
    keys = json.load(open(SECRETS / "api-keys-local-dev.json", encoding="utf-8"))["orgs"]
    field = "key" if PORT == 8070 else "key_%d" % PORT
    if any(field not in keys[org] for org in (ORG_A, ORG_B)):
        print("🔴 у e2e.local/api-keys-local-dev.json немає ключів під :%d (поле %s) — "
              "забрати свіжий файл з VPS (active-doc/.secrets)" % (PORT, field))
        return 2
    key_a, key_b = keys[ORG_A][field], keys[ORG_B][field]
    password = (SECRETS / "PASSWORD.txt").read_text(encoding="utf-8").strip()
    if port_open(PORT):
        print("🔴 порт %d зайнятий — на ньому вже щось працює" % PORT)
        return 2

    print("0. Дві чисті бази з account + aktiv_doc")
    for db in (DB_A, DB_B):
        make_db(db)
    # Фільтр баз — явно: Odoo під Windows ще при імпорті читає `odoo.conf` поруч з
    # odoo-bin, а `-c` перекриває лише свої ключі. У збірці 18 там `dbfilter = .*18$`
    # служби — і сервер відповідав «Database not found» на щойно створені бази.
    server = subprocess.Popen(odoo_cmd("--max-cron-threads=0", "--http-port=%d" % PORT,
                                       "--db-filter=^(%s|%s)$" % (DB_A, DB_B),
                                       "--logfile=" + str(LOG)), env=odoo_env(),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _i in range(120):
            if port_open(PORT):
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
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch()
            print("1. А: рахунок → «Надіслати на підпис» → вікно підпису")
            ctx_a, page = login(browser, DB_A)
            page.goto("%s/odoo/action-account.action_move_out_invoice_type/%d" % (URL, move))
            try:
                page.get_by_role("button", name="Надіслати на підпис").click()
            except Exception:
                # Знімок того, що бачить людина, — замість здогадок про верстку.
                page.screenshot(path=str(SECRETS / "fail.png"))
                raise
            dialog = page.locator(".modal")
            dialog.get_by_role("button", name="Переглянути").click()
            # Чекаємо саму відмальовану сторінку PDF, а не рамку переглядача: перший
            # знімок вийшов із порожнім «0 із 0» — рамка вже була, сторінки ще ні.
            pdf_frame = page.frame_locator(".modal iframe")
            pdf_frame.locator(".page[data-loaded='true']").first.wait_for(timeout=90000)
            check(True, "перегляд PDF у майстрі відмальовано")
            shot(page, "screenshot_send.png")
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
            sign_in_window(page, SECRETS / "Key-6.dat", SECRETS / "test-signer.cer", password,
                           shot_name="screenshot_sign.png")
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
            page_b.locator(".o_form_sheet").wait_for(timeout=60000)
            shot(page_b, "screenshot_incoming.png")
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
                # `datas` в Odoo 20 прибрано — є `raw`; двійкове поле Odoo 20 віддає словником
                # {"content": base64, "size": …}, а 18/19 — рядком base64.
                field = "datas" if a.call("ir.attachment", "fields_get", ["datas"]) else "raw"
                raw = a.call("ir.attachment", "read", [zips[0]["id"]], [field])[0][field]
                if isinstance(raw, dict):
                    raw = raw["content"]
                import base64
                names = zipfile.ZipFile(io.BytesIO(base64.b64decode(raw))).namelist()
                check(len([n for n in names if ".sign" in n]) == 2 and "protokol.html" in names,
                      "в архіві два підписи й протокол (%d файлів)" % len(names))
            if SHOTS:
                page.goto("%s/odoo/action-aktiv_doc.action_aktiv_doc_outgoing/%d" % (URL, doc["id"]))
                page.locator(".o_form_sheet").wait_for(timeout=60000)
                shot(page, "screenshot_document.png")

            print("6. Колонка «Active Doc» у списку рахунків")
            page.goto("%s/odoo/action-account.action_move_out_invoice_type" % URL)
            row = page.locator(".o_data_row").first
            row.wait_for(timeout=60000)
            check("Підписано обома" in row.inner_text(),
                  "у списку рахунків поруч зі «Стан» — «Підписано обома»")
            shot(page, "screenshot_list.png")

            print("7. Odoo відкрито не з адреси ключа — пояснення ДО завантаження")
            move2 = a.call("account.move", "create", {
                "move_type": "out_invoice", "partner_id": partner_b,
                "invoice_line_ids": [(0, 0, {"name": "Консультаційні послуги", "quantity": 1,
                                             "price_unit": 500.0})]})
            a.call("account.move", "action_post", [move2])
            other = URL.replace("localhost", "127.0.0.1")
            ctx_c, page_c = login(browser, DB_A, other)
            page_c.goto("%s/odoo/action-account.action_move_out_invoice_type/%d" % (other, move2))
            page_c.get_by_role("button", name="Надіслати на підпис").click()
            page_c.locator(".modal").get_by_role("button", name="Підписати").click()
            error = page_c.locator(".modal", has_text="відкрийте Odoo за адресою")
            error.wait_for(timeout=60000)
            orphans = a.call("aktiv.doc.document", "search_count",
                             [("record_ref", "=", "account.move,%d" % move2)])
            check(URL in error.inner_text() and orphans == 0,
                  "людина бачить, за якою адресою відкрити Odoo; чернетки в Active Doc немає")
            ctx_c.close()
            ctx_a.close()
            ctx_b.close()
            browser.close()
        except Exception:
            # Падіння на будь-якому кроці — знімки всіх відкритих сторінок, а не
            # здогадки: браузер закриється разом із драйвером, і подивитись буде нічого.
            for index, opened in enumerate(PAGES):
                try:
                    path = SECRETS / ("fail-%d.png" % index)
                    opened.screenshot(path=str(path))
                    print("  знімок падіння: %s (%s)" % (path.name, opened.url))
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
            subprocess.run([sys.executable, str(THREE_A / "tools" / "ops" / "db_classes.py"),
                            "drop", "--site", SITE, DB_A, DB_B], stdout=subprocess.DEVNULL)
    print("\n✅ «Active Doc»: наскрізно пройдено" if not problems
          else "\n🔴 «Active Doc»: не пройдено %d" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
