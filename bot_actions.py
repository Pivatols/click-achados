import hashlib
import html
import json
import os
import random
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "postados.json")
API = "https://open-api.affiliate.shopee.com.br/graphql"

with open(os.path.join(BASE, "settings.json"), encoding="utf-8") as f:
    CFG = json.load(f)

# Segredos vêm do GitHub (Settings > Secrets), nunca do código
try:
    TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"].strip()
    APP_ID = os.environ["SHOPEE_APP_ID"].strip()
    SECRET = os.environ["SHOPEE_SECRET"].strip()
except KeyError as e:
    sys.exit(f"Faltou o secret {e} no GitHub (Settings > Secrets and variables > Actions).")


# ---------- Shopee ----------
def shopee_query(query):
    payload = json.dumps({"query": query}, separators=(",", ":"))
    ts = str(int(__import__("time").time()))
    sig = hashlib.sha256((APP_ID + ts + payload + SECRET).encode()).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={APP_ID}, Timestamp={ts}, Signature={sig}",
    }
    r = requests.post(API, data=payload.encode(), headers=headers, timeout=30)
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def buscar_produtos(keyword, page):
    kw = ", keyword: " + json.dumps(keyword) if keyword else ""
    query = (
        "{ productOfferV2(sortType: " + str(CFG["ordenar_por"])
        + ", page: " + str(page) + ", limit: 30" + kw + ") { nodes { "
        "itemId productName imageUrl priceMin priceMax priceDiscountRate "
        "ratingStar sales commissionRate offerLink shopName } } }"
    )
    return shopee_query(query)["productOfferV2"]["nodes"]


# ---------- Controle de repetidos ----------
def carregar_postados():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def salvar_postados(lista):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(lista[-5000:], f)  # guarda os 5000 mais recentes


# ---------- Telegram ----------
def preco(valor):
    try:
        return "R$ " + f"{float(valor):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return ""


def montar_legenda(p):
    nome = html.escape(p["productName"][:110])
    linhas = [f"🔥 <b>{nome}</b>", ""]
    desc = p.get("priceDiscountRate") or 0
    if desc:
        linhas.append(f"🏷️ <b>{desc}% OFF</b>")
    linhas.append(f"💰 Por apenas <b>{preco(p.get('priceMin'))}</b>")
    if p.get("ratingStar"):
        try:
            linhas.append(f"⭐ Nota {float(p['ratingStar']):.1f}")
        except ValueError:
            pass
    linhas += ["", f"🛒 Comprar: {p['offerLink']}", "",
               "<i>Link de afiliado. Preços podem mudar.</i>"]
    return "\n".join(linhas)


def postar(p):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    legenda = montar_legenda(p)
    r = requests.post(url + "/sendPhoto", data={
        "chat_id": CFG["canal"], "photo": p["imageUrl"],
        "caption": legenda, "parse_mode": "HTML"}, timeout=30)
    if not r.json().get("ok"):
        r = requests.post(url + "/sendMessage", data={
            "chat_id": CFG["canal"], "text": legenda,
            "parse_mode": "HTML"}, timeout=30)
    resp = r.json()
    if not resp.get("ok"):
        raise RuntimeError(resp)


# ---------- Execução única ----------
def aprovado(p, postados):
    try:
        if str(p["itemId"]) in postados:
            return False
        if (p.get("priceDiscountRate") or 0) < CFG["min_desconto"]:
            return False
        if float(p.get("ratingStar") or 0) < CFG["min_nota"]:
            return False
        return bool(p.get("offerLink") and p.get("imageUrl"))
    except (TypeError, ValueError):
        return False


def main():
    agora = datetime.now(ZoneInfo(CFG["fuso_horario"]))
    forcar = os.environ.get("FORCAR") == "1"  # execução manual ignora o horário
    if not forcar and not (CFG["hora_inicio"] <= agora.hour < CFG["hora_fim"]):
        print(f"Fora do horário de postagem ({agora:%H:%M}). Nada a fazer.")
        return

    postados = carregar_postados()
    vistos = set(postados)

    for tentativa in range(1, 9):
        kw = random.choice(CFG["palavras_chave"]) if CFG["palavras_chave"] else None
        page = random.randint(1, 3)
        achados = buscar_produtos(kw, page)
        candidatos = [p for p in achados if aprovado(p, vistos)]
        print(f"Tentativa {tentativa}: '{kw}' pag {page} -> {len(candidatos)} aprovados")
        if candidatos:
            produto = random.choice(candidatos)
            postar(produto)
            postados.append(str(produto["itemId"]))
            salvar_postados(postados)
            print("Postado:", produto["productName"][:70])
            return

    print("Nenhum produto novo encontrado nesta execução.")


if __name__ == "__main__":
    main()
