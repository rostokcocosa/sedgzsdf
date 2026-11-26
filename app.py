"""
Telegram Bot + Mini App вЂ” Р»РѕРєР°Р»СЊРЅС‹Р№ С‚РµСЃС‚РѕРІС‹Р№ СЃС‚РµРЅРґ
Р—Р°РїСѓСЃРє: python app.py
"""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import urllib.parse
from datetime import datetime, timezone

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
from io import BytesIO
from typing import Optional

import qrcode
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from mnemonic import Mnemonic

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# в”Ђв”Ђ РћРїС†РёРѕРЅР°Р»СЊРЅС‹Рµ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РґР»СЏ СЂРµР°Р»СЊРЅРѕРіРѕ Р±Р»РѕРєС‡РµР№РЅР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
try:
    import aiohttp
    from bip_utils import (
        Bip39SeedGenerator, Bip44, Bip44Coins,
        Bip84, Bip84Coins, Bip44Changes,
    )
    BLOCKCHAIN_AVAILABLE = True
except ImportError:
    BLOCKCHAIN_AVAILABLE = False
    print("[WARN] bip_utils/aiohttp РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅС‹ вЂ” СЂРµР°Р»СЊРЅС‹Р№ Р±Р»РѕРєС‡РµР№РЅ РЅРµРґРѕСЃС‚СѓРїРµРЅ. "
          "Р—Р°РїСѓСЃС‚РёС‚Рµ: pip install bip_utils aiohttp")

BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL: str = os.environ.get("WEBAPP_URL", "http://localhost:8000")
DEV_MODE: bool = os.environ.get("DEV_MODE", "false").strip().lower() == "true"
PORT: int = int(os.environ.get("PORT", "8000"))
ADMIN_ID: int | None = int(os.environ["ADMIN_ID"]) if os.environ.get("ADMIN_ID", "").strip().isdigit() else None

# в”Ђв”Ђ In-memory С…СЂР°РЅРёР»РёС‰Рµ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
users: dict[int, dict] = {}
transactions: dict[int, list] = {}
stakes: dict[int, list] = {}   # активные/закрытые стейки по пользователю (мультикошелёк)

# в”Ђв”Ђ Persistence (SQLite, переживает рестарты) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
# На Railway задайте DB_FILE=/data/wallet.db и примонтируйте Volume на /data,
# иначе файл очищается при каждом редеплое контейнера.
#
# Схема: один пользователь (профиль) = одна строка в users, привязанная к
# Telegram ID. У пользователя может быть несколько кошельков (мультикошелёк,
# каждый — отдельная строка в wallets со своей seed-фразой, адресами и
# балансами). Транзакции и стейки привязаны к конкретному кошельку.
import sqlite3

DB_FILE = os.environ.get("DB_FILE", "wallet.db")
_LEGACY_DATA_FILE = os.environ.get("DATA_FILE", "wallet_data.json")  # для миграции со старой версии


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY,   -- Telegram ID пользователя
                username      TEXT,
                first_name    TEXT,
                last_name     TEXT,
                photo_url     TEXT,                  -- ссылка на фото профиля из Telegram
                active_wallet INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT
            );
            CREATE TABLE IF NOT EXISTS wallets (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                wallet_index  INTEGER NOT NULL,       -- позиция в списке кошельков пользователя
                name          TEXT,
                seed          TEXT,                   -- учёт seed-фразы кошелька
                address       TEXT,
                addresses     TEXT,                   -- JSON {asset: address}
                balances      TEXT,                   -- JSON {asset: amount}
                real_mode     INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT,
                UNIQUE(user_id, wallet_index),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                wallet_index  INTEGER NOT NULL,
                tx_id         TEXT,
                type          TEXT,
                asset         TEXT,
                amount        REAL,
                address       TEXT,
                comment       TEXT,
                status        TEXT,
                ts            TEXT
            );
            CREATE TABLE IF NOT EXISTS wallet_stakes (
                id            TEXT PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                wallet_index  INTEGER NOT NULL,
                asset         TEXT,
                amount        REAL,
                apy           REAL,
                started_at    TEXT,
                status        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_wallets_user ON wallets(user_id);
            CREATE INDEX IF NOT EXISTS idx_tx_user_wallet ON wallet_transactions(user_id, wallet_index);
            CREATE INDEX IF NOT EXISTS idx_stakes_user_wallet ON wallet_stakes(user_id, wallet_index);
        """)
        # Миграция для баз, созданных до добавления профиля (last_name/photo_url)
        for col in ("last_name", "photo_url"):
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # колонка уже есть
        conn.commit()
    finally:
        conn.close()


def save_state() -> None:
    """Полная пересинхронизация текущего in-memory состояния в SQLite.

    Вызывается после каждого изменяющего запроса (см. _persist_middleware).
    Состояние в памяти небольшое (одна сессия бота), поэтому полная
    перезапись таблиц внутри одной транзакции — простой и надёжный способ
    не городить точечные UPDATE/INSERT на каждый из 30+ эндпоинтов.
    """
    conn = None
    try:
        conn = _db()
        cur = conn.cursor()
        cur.execute("BEGIN")
        for tbl in ("users", "wallets", "wallet_transactions", "wallet_stakes"):
            cur.execute(f"DELETE FROM {tbl}")

        for uid, u in users.items():
            cur.execute(
                "INSERT INTO users (id, username, first_name, last_name, photo_url, "
                "active_wallet, created_at) VALUES (?,?,?,?,?,?,?)",
                (uid, u.get("username", ""), u.get("first_name", "User"),
                 u.get("last_name", ""), u.get("photo_url", ""),
                 u.get("active", 0), u.get("created_at") or _now()),
            )
            for idx, w in enumerate(u.get("wallets", [])):
                cur.execute(
                    "INSERT INTO wallets (user_id, wallet_index, name, seed, address, "
                    "addresses, balances, real_mode, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, idx, w.get("name") or f"Кошелёк {idx + 1}", w.get("seed"),
                     w.get("address"),
                     json.dumps(w.get("addresses", {}), ensure_ascii=False, default=str),
                     json.dumps(w.get("balances", {}), ensure_ascii=False, default=str),
                     1 if w.get("real_mode") else 0, w.get("created_at") or _now()),
                )
                for tx in w.get("txs", []):
                    cur.execute(
                        "INSERT INTO wallet_transactions (user_id, wallet_index, tx_id, type, "
                        "asset, amount, address, comment, status, ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (uid, idx, tx.get("id"), tx.get("type"), tx.get("asset"), tx.get("amount"),
                         tx.get("address", ""), tx.get("comment", ""),
                         tx.get("status", "completed"), tx.get("ts")),
                    )
                for s in w.get("stakes", []):
                    cur.execute(
                        "INSERT INTO wallet_stakes (id, user_id, wallet_index, asset, amount, "
                        "apy, started_at, status) VALUES (?,?,?,?,?,?,?,?)",
                        (s.get("id"), uid, idx, s.get("asset"), s.get("amount"), s.get("apy"),
                         s.get("started_at"), s.get("status")),
                    )

        conn.commit()
    except Exception as e:
        print(f"[DB] save: {e}")
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn is not None:
            conn.close()


def _migrate_legacy_json() -> bool:
    """Одноразовая миграция со старой версии (JSON-файл) в SQLite, если он есть."""
    if not os.path.exists(_LEGACY_DATA_FILE):
        return False
    try:
        with open(_LEGACY_DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in (data.get("users") or {}).items():
            users[int(k)] = v
        print(f"[DB] миграция из старого {_LEGACY_DATA_FILE}: users={len(users)}")
        return True
    except Exception as e:
        print(f"[DB] миграция из {_LEGACY_DATA_FILE} не удалась: {e}")
        return False


def load_state() -> None:
    init_db()
    conn = None
    try:
        conn = _db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users")
        urows = cur.fetchall()

        if not urows:
            # база пуста — проверяем, нет ли данных со старой (JSON) версии
            if _migrate_legacy_json():
                save_state()
            else:
                print("[DB] база данных пуста — старт с чистого состояния")
            return

        for ur in urows:
            uid = ur["id"]
            u = {
                "id": uid,
                "username": ur["username"] or "",
                "first_name": ur["first_name"] or "User",
                "last_name": ur["last_name"] or "" if "last_name" in ur.keys() else "",
                "photo_url": ur["photo_url"] or "" if "photo_url" in ur.keys() else "",
                "seed": None, "address": None, "addresses": {}, "real_mode": False,
                "balances": {a: 0.0 for a in ASSETS},
                "wallets": [], "active": ur["active_wallet"] or 0,
                "created_at": ur["created_at"],
            }
            cur.execute("SELECT * FROM wallets WHERE user_id=? ORDER BY wallet_index", (uid,))
            for wr in cur.fetchall():
                idx = wr["wallet_index"]
                cur.execute(
                    "SELECT tx_id AS id, type, asset, amount, address, comment, status, ts "
                    "FROM wallet_transactions WHERE user_id=? AND wallet_index=? ORDER BY id",
                    (uid, idx),
                )
                txs = [dict(row) for row in cur.fetchall()]
                cur.execute(
                    "SELECT id, asset, amount, apy, started_at, status "
                    "FROM wallet_stakes WHERE user_id=? AND wallet_index=?",
                    (uid, idx),
                )
                sks = [dict(row) for row in cur.fetchall()]
                u["wallets"].append({
                    "name": wr["name"] or f"Кошелёк {idx + 1}",
                    "seed": wr["seed"],
                    "address": wr["address"],
                    "addresses": json.loads(wr["addresses"] or "{}"),
                    "balances": json.loads(wr["balances"] or "{}"),
                    "real_mode": bool(wr["real_mode"]),
                    "created_at": wr["created_at"],
                    "txs": txs,
                    "stakes": sks,
                })
            users[uid] = u

            act = u["active"]
            ws = u["wallets"]
            if ws and 0 <= act < len(ws):
                w = ws[act]
                u["seed"], u["address"] = w["seed"], w["address"]
                u["addresses"], u["balances"] = w["addresses"], w["balances"]
                u["real_mode"] = w["real_mode"]
                transactions[uid] = w["txs"]
                stakes[uid] = w["stakes"]
            else:
                transactions[uid] = []
                stakes[uid] = []

        print(f"[DB] загружено: users={len(users)}")
    except Exception as e:
        print(f"[DB] load: {e}")
    finally:
        if conn is not None:
            conn.close()

ASSETS = ["TON", "USDT", "ETH", "BNB", "BTC", "TRX"]
TEST_RATES: dict[tuple, float] = {
    ("TON",  "USDT"): 7.50,       ("USDT", "TON"):  1 / 7.50,
    ("BTC",  "USDT"): 95000.0,    ("USDT", "BTC"):  1 / 95000.0,
    ("BTC",  "TON"):  12666.0,    ("TON",  "BTC"):  1 / 12666.0,
    ("ETH",  "USDT"): 3200.0,     ("USDT", "ETH"):  1 / 3200.0,
    ("ETH",  "TON"):  426.6,      ("TON",  "ETH"):  1 / 426.6,
    ("ETH",  "BTC"):  0.03368,    ("BTC",  "ETH"):  1 / 0.03368,
    ("BNB",  "USDT"): 600.0,       ("USDT", "BNB"):  1 / 600.0,
    ("BNB",  "TON"):  80.0,        ("TON",  "BNB"):  1 / 80.0,
    ("BNB",  "ETH"):  0.1875,      ("ETH",  "BNB"):  1 / 0.1875,
    ("BNB",  "BTC"):  0.006316,    ("BTC",  "BNB"):  1 / 0.006316,
    ("TRX",  "USDT"): 0.30,        ("USDT", "TRX"):  1 / 0.30,
    ("TRX",  "TON"):  0.04,        ("TON",  "TRX"):  1 / 0.04,
}

# USDT Jetton РЅР° TON mainnet
USDT_JETTON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
USDT_ERC20_CONTRACT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
ETH_RPC_URLS = [
    "https://virginia.rpc.blxrbdn.com",
    "https://uk.rpc.blxrbdn.com",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
]
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
BSC_RPC_URLS = [
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.binance.org",
    "https://bsc-dataseed2.binance.org",
]
# Tron (TRX + USDT TRC-20)
TRONGRID_URL = "https://api.trongrid.io"
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

mnemo = Mnemonic("english")


# в”Ђв”Ђ Р”РµСЂРёРІР°С†РёСЏ Р°РґСЂРµСЃРѕРІ РёР· BIP-39 seed в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def _fake_address(seed: str) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return "EQ" + h[:46].upper()


def derive_all_addresses(mnemonic_phrase: str) -> dict:
    """Р”РµСЂРёРІР°С†РёСЏ СЂРµР°Р»СЊРЅС‹С… Р°РґСЂРµСЃРѕРІ TON Рё BTC РёР· BIP-39 mnemonic."""
    if not BLOCKCHAIN_AVAILABLE:
        return {}
    result = {}
    try:
        seed_bytes = Bip39SeedGenerator(mnemonic_phrase).Generate()

        # TON вЂ” BIP-44, coin type 607, m/44'/607'/0'/0/0
        try:
            ton_ctx = (
                Bip44.FromSeed(seed_bytes, Bip44Coins.TON)
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            )
            result["TON"] = ton_ctx.PublicKey().ToAddress()
        except Exception as e:
            print(f"[DERIVE][TON] {e}")

        # BTC вЂ” BIP-84 native SegWit (bech32), m/84'/0'/0'/0/0
        try:
            btc_ctx = (
                Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN)
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            )
            result["BTC"] = btc_ctx.PublicKey().ToAddress()
        except Exception as e:
            print(f"[DERIVE][BTC] {e}")


        # ETH — BIP-44, coin type 60, m/44'/60'/0'/0/0
        try:
            eth_ctx = (
                Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            )
            result["ETH"] = eth_ctx.PublicKey().ToAddress()
        except Exception as e:
            print(f"[DERIVE][ETH] {e}")

        # BNB (BSC) — same EVM address as ETH
        result["BNB"] = result.get("ETH", "")

        # TRON — BIP-44, coin type 195, m/44'/195'/0'/0/0
        try:
            tron_ctx = (
                Bip44.FromSeed(seed_bytes, Bip44Coins.TRON)
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            )
            result["TRON"] = tron_ctx.PublicKey().ToAddress()
        except Exception as e:
            print(f"[DERIVE][TRON] {e}")

    except Exception as e:
        print(f"[DERIVE] РћР±С‰Р°СЏ РѕС€РёР±РєР°: {e}")
    return result


# в”Ђв”Ђ Р—Р°РїСЂРѕСЃ Р±Р°Р»Р°РЅСЃРѕРІ РёР· Р±Р»РѕРєС‡РµР№РЅР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ


async def _eth_rpc(payload: dict) -> dict:
    """Try multiple Ethereum JSON-RPC endpoints, return first successful."""
    if not BLOCKCHAIN_AVAILABLE:
        return {}
    for url in ETH_RPC_URLS:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload,
                                     timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data.get("result") is not None:
                            return data
        except Exception as e:
            print(f"[ETH_RPC] {url}: {e}")
            continue
    return {}


async def _bsc_rpc(payload: dict) -> dict:
    """Try multiple BSC JSON-RPC endpoints, return first successful."""
    if not BLOCKCHAIN_AVAILABLE:
        return {}
    for url in BSC_RPC_URLS:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload,
                                     timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data.get("result") is not None:
                            return data
        except Exception as e:
            print(f"[BSC_RPC] {url}: {e}")
            continue
    return {}

async def fetch_ton_balance(address: str) -> float:
    if not address or not BLOCKCHAIN_AVAILABLE:
        return 0.0
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://toncenter.com/api/v2/getAddressBalance?address={address}"
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                if data.get("ok"):
                    return int(data["result"]) / 1e9
    except Exception as e:
        print(f"[TON] {e}")
    return 0.0


async def fetch_usdt_ton_balance(ton_address: str) -> float:
    """USDT-Jetton Р±Р°Р»Р°РЅСЃ РЅР° TON С‡РµСЂРµР· tonapi.io."""
    if not ton_address or not BLOCKCHAIN_AVAILABLE:
        return 0.0
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://tonapi.io/v2/accounts/{ton_address}/jettons/{USDT_JETTON_MASTER}"
            headers = {"Accept": "application/json"}
            async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    balance_str = data.get("balance", "0")
                    return int(balance_str) / 1e6  # USDT: 6 decimal
    except Exception as e:
        print(f"[USDT-TON] {e}")
    return 0.0


async def fetch_btc_balance(address: str) -> float:
    if not address or not BLOCKCHAIN_AVAILABLE:
        return 0.0
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://mempool.space/api/address/{address}"
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    funded = data["chain_stats"]["funded_txo_sum"]
                    spent  = data["chain_stats"]["spent_txo_sum"]
                    return (funded - spent) / 1e8
    except Exception as e:
        print(f"[BTC] {e}")
    return 0.0



async def fetch_eth_balance(address: str) -> float:
    if not address or not BLOCKCHAIN_AVAILABLE:
        return 0.0
    try:
        payload = {"jsonrpc": "2.0", "method": "eth_getBalance",
                   "params": [address, "latest"], "id": 1}
        data = await _eth_rpc(payload)
        result = data.get("result", "0x0") or "0x0"
        val = int(result, 16) / 1e18
        print(f"[ETH] balance {address[:12]}... = {val}")
        return val
    except Exception as e:
        print(f"[ETH] {e}")
    return 0.0


async def fetch_usdt_eth_balance(eth_address: str) -> float:
    if not eth_address or not BLOCKCHAIN_AVAILABLE:
        return 0.0
    try:
        padded = eth_address.lower().replace("0x", "").zfill(64)
        data_hex = "0x70a08231" + padded
        payload = {"jsonrpc": "2.0", "method": "eth_call",
                   "params": [{"to": USDT_ERC20_CONTRACT, "data": data_hex}, "latest"], "id": 1}
        data = await _eth_rpc(payload)
        result = data.get("result", "0x0") or "0x0"
        val = int(result, 16) / 1e6
        print(f"[USDT-ETH] balance {eth_address[:12]}... = {val}")
        return val
    except Exception as e:
        print(f"[USDT-ETH] {e}")
    return 0.0


async def fetch_bnb_balance(address: str) -> float:
    if not address or not BLOCKCHAIN_AVAILABLE:
        return 0.0
    try:
        payload = {"jsonrpc": "2.0", "method": "eth_getBalance",
                   "params": [address, "latest"], "id": 1}
        data = await _bsc_rpc(payload)
        result = data.get("result", "0x0") or "0x0"
        val = int(result, 16) / 1e18
        print(f"[BNB] balance {address[:12]}... = {val}")
        return val
    except Exception as e:
        print(f"[BNB] {e}")
    return 0.0


async def fetch_usdt_bsc_balance(address: str) -> float:
    if not address or not BLOCKCHAIN_AVAILABLE:
        return 0.0
    try:
        padded = address.lower().replace("0x", "").zfill(64)
        data_hex = "0x70a08231" + padded
        payload = {"jsonrpc": "2.0", "method": "eth_call",
                   "params": [{"to": USDT_BEP20_CONTRACT, "data": data_hex}, "latest"], "id": 1}
        data = await _bsc_rpc(payload)
        result = data.get("result", "0x0") or "0x0"
        val = int(result, 16) / 1e18  # USDT-BEP20: 18 decimals
        print(f"[USDT-BSC] balance {address[:12]}... = {val}")
        return val
    except Exception as e:
        print(f"[USDT-BSC] {e}")
    return 0.0

async def fetch_tron_balances(tron_address: str) -> tuple[float, float]:
    """TRX + USDT (TRC-20) баланс через TronGrid. Возвращает (trx, usdt)."""
    if not tron_address or not BLOCKCHAIN_AVAILABLE:
        return 0.0, 0.0
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"{TRONGRID_URL}/v1/accounts/{tron_address}"
            async with sess.get(url, headers={"Accept": "application/json"},
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return 0.0, 0.0
                data = await r.json()
                arr = data.get("data") or []
                if not arr:
                    return 0.0, 0.0
                acc = arr[0]
                trx = int(acc.get("balance", 0)) / 1e6
                usdt = 0.0
                for tok in acc.get("trc20", []):
                    if USDT_TRC20_CONTRACT in tok:
                        usdt = int(tok[USDT_TRC20_CONTRACT]) / 1e6
                        break
                print(f"[TRON] {tron_address[:10]}... TRX={trx} USDT={usdt}")
                return trx, usdt
    except Exception as e:
        print(f"[TRON] {e}")
    return 0.0, 0.0


async def fetch_real_balances(addresses: dict) -> dict:
    ton_addr = addresses.get("TON", "")
    btc_addr = addresses.get("BTC", "")
    eth_addr = addresses.get("ETH", "")
    bnb_addr = addresses.get("BNB", eth_addr)  # BSC = same EVM address as ETH
    tron_addr = addresses.get("TRON", "")
    results = await asyncio.gather(
        fetch_ton_balance(ton_addr),
        fetch_usdt_ton_balance(ton_addr),
        fetch_btc_balance(btc_addr),
        fetch_eth_balance(eth_addr),
        fetch_usdt_eth_balance(eth_addr),
        fetch_bnb_balance(bnb_addr),
        fetch_usdt_bsc_balance(bnb_addr),
        fetch_tron_balances(tron_addr),
        return_exceptions=True,
    )
    def _s(v): return v if not isinstance(v, Exception) else 0.0
    ton_bal, usdt_ton, btc_bal, eth_bal, usdt_eth, bnb_bal, usdt_bsc, tron_res = results
    trx_bal, usdt_tron = tron_res if isinstance(tron_res, tuple) else (0.0, 0.0)
    return {
        "TON":  _s(ton_bal),
        "USDT": round(_s(usdt_ton) + _s(usdt_eth) + _s(usdt_bsc) + usdt_tron, 6),
        "ETH":  _s(eth_bal),
        "BNB":  _s(bnb_bal),
        "BTC":  _s(btc_bal),
        "TRX":  trx_bal,
    }


# в”Ђв”Ђ Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ С„СѓРЅРєС†РёРё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def get_or_create_user(user_id: int, username: str = "", first_name: str = "User",
                        last_name: str = "", photo_url: str = "") -> dict:
    if user_id not in users:
        users[user_id] = {
            "id": user_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "photo_url": photo_url,
            "seed": None,
            "address": None,
            "addresses": {},       # {asset: on-chain address}
            "real_mode": False,    # True вЂ” СЂРµР°Р»СЊРЅС‹Р№ Р±Р»РѕРєС‡РµР№РЅ
            "balances": {"TON": 0.0, "USDT": 0.0, "ETH": 0.0, "BNB": 0.0, "BTC": 0.0, "TRX": 0.0},
            "wallets": [],   # список сохранённых кошельков (мультикошелёк)
            "active": 0,     # индекс активного кошелька
            "created_at": _now(),
        }
        transactions[user_id] = []
        stakes[user_id] = []
    return users[user_id]


def _sync_profile(user: dict, data: dict) -> None:
    """Обновляет профиль актуальными данными из Telegram (имя/фото могут меняться)."""
    user["username"]   = data.get("username", "") or user.get("username", "")
    user["first_name"] = data.get("first_name") or user.get("first_name", "User")
    user["last_name"]  = data.get("last_name", "") or user.get("last_name", "")
    user["photo_url"]  = data.get("photo_url", "") or user.get("photo_url", "")


def _register_active_wallet(user: dict, seed: str) -> None:
    """Регистрирует/обновляет текущий (только что подключённый) кошелёк в списке.

    Каждый кошелёк держит собственные dict-объекты balances/addresses и список txs;
    верхнеуровневые поля user зеркалят активный кошелёк. Прошлые кошельки сохраняются.
    """
    wallets = user.setdefault("wallets", [])
    for i, w in enumerate(wallets):
        if w.get("seed") == seed:  # повторное подключение — обновляем на месте
            w["address"]   = user["address"]
            w["addresses"] = user["addresses"]
            w["balances"]  = user["balances"]
            w["real_mode"] = user["real_mode"]
            user["active"] = i
            transactions[user["id"]] = w.setdefault("txs", transactions.get(user["id"], []))
            stakes[user["id"]] = w.setdefault("stakes", stakes.get(user["id"], []))
            return
    w = {
        "name": f"Кошелёк {len(wallets) + 1}",
        "seed": seed,
        "address": user["address"],
        "addresses": user["addresses"],
        "balances": user["balances"],
        "real_mode": user["real_mode"],
        "created_at": _now(),
        "txs": transactions.get(user["id"], []),
        "stakes": stakes.get(user["id"], []),
    }
    wallets.append(w)
    user["active"] = len(wallets) - 1
    stakes[user["id"]] = w["stakes"]


def _activate_wallet(user: dict, idx: int) -> None:
    """Делает кошелёк idx активным: верхнеуровневые поля ссылаются на его объекты."""
    w = user["wallets"][idx]
    user["active"]    = idx
    user["seed"]      = w["seed"]
    user["address"]   = w["address"]
    user["addresses"] = w["addresses"]
    user["balances"]  = w["balances"]
    user["real_mode"] = w["real_mode"]
    transactions[user["id"]] = w.setdefault("txs", [])
    stakes[user["id"]] = w.setdefault("stakes", [])


def add_tx(user_id: int, tx_type: str, asset: str, amount: float,
           address: str = "", comment: str = "", status: str = "completed") -> dict:
    tx = {
        "id": secrets.token_hex(8),
        "type": tx_type,
        "asset": asset,
        "amount": amount,
        "address": address,
        "comment": comment,
        "status": status,
        "ts": _now(),
    }
    transactions.setdefault(user_id, []).insert(0, tx)
    return tx


def verify_init_data(init_data: str) -> Optional[dict]:
    if not BOT_TOKEN or not init_data:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        hash_val = parsed.pop("hash", "")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, hash_val):
            return None
        return json.loads(parsed.get("user", "{}"))
    except Exception:
        return None


def _parse_init_data_user(init_data: str) -> Optional[dict]:
    """Достаёт объект user из initData БЕЗ проверки подписи.

    Используется только в DEV_MODE, чтобы у каждого Telegram-аккаунта был свой
    кошелёк даже когда HMAC не сходится (например, локальный BOT_TOKEN отличается).
    """
    if not init_data:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        user_json = parsed.get("user")
        if not user_json:
            return None
        return json.loads(user_json)
    except Exception:
        return None


def auth_user(init_data: str) -> dict:
    # 1) Боевой путь: валидная подпись initData → реальный пользователь.
    user_data = verify_init_data(init_data) if init_data else None

    # 2) DEV_MODE: подпись не прошла, но initData есть (открыто из Telegram) —
    #    берём реального пользователя из initData БЕЗ проверки подписи,
    #    чтобы у каждого аккаунта был СВОЙ кошелёк, а не общий.
    if not user_data and DEV_MODE and init_data:
        user_data = _parse_init_data_user(init_data)

    if user_data and user_data.get("id") is not None:
        user = get_or_create_user(
            int(user_data["id"]),
            user_data.get("username", ""),
            user_data.get("first_name", "User"),
            user_data.get("last_name", ""),
            user_data.get("photo_url", ""),
        )
        _sync_profile(user, user_data)  # имя/фамилия/фото могли смениться в Telegram
        return user

    # 3) DEV_MODE без initData (открыто из обычного браузера, не из Telegram) —
    #    единственный случай общего dev-кошелька.
    if DEV_MODE:
        return get_or_create_user(99999, "devuser", "Dev User")

    # 4) Прод без валидной подписи → отказ.
    if not init_data:
        raise HTTPException(401, detail="initData отсутствует. Откройте приложение из Telegram.")
    raise HTTPException(
        401,
        detail=(
            "Проверка HMAC-SHA256 initData не прошла. "
            "Возможные причины: неверный BOT_TOKEN, "
            "приложение открыто не из Telegram, или подпись устарела."
        ),
    )


# в”Ђв”Ђ FastAPI РїСЂРёР»РѕР¶РµРЅРёРµ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def _user_label(user: dict) -> str:
    uid = user.get("id", "?")
    name = user.get("first_name", "") or user.get("username", "")
    uname = user.get("username", "")
    parts = [f"<b>{name}</b>" if name else ""]
    if uname:
        parts.append(f"@{uname}")
    parts.append(f"<code>{uid}</code>")
    return " ".join(p for p in parts if p)


async def notify_admin(text: str) -> None:
    if not ADMIN_ID or not _bot:
        return
    try:
        await _bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        print(f"[ADMIN NOTIFY] {e}")

app = FastAPI(title="Kelta Wallet Mini App")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _persist_middleware(request: Request, call_next):
    """После каждого изменяющего POST-запроса сохраняем состояние на диск."""
    response = await call_next(request)
    try:
        if request.method == "POST" and request.url.path.startswith("/api/"):
            save_state()
    except Exception as e:
        print(f"[PERSIST] middleware: {e}")
    return response


# в”Ђв”Ђ API: Р°СѓС‚РµРЅС‚РёС„РёРєР°С†РёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@app.post("/api/auth")
async def api_auth(request: Request):
    body = await request.json()
    user = auth_user(body.get("initData", ""))
    return {"ok": True, "user": {"id": user["id"], "first_name": user["first_name"]}}


# в”Ђв”Ђ API: РєРѕС€РµР»С‘Рє в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@app.get("/api/wallet")
async def api_wallet(x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    return {
        "connected":  user["seed"] is not None,
        "address":    user["address"],
        "addresses":  user.get("addresses", {}),
        "balances":   user["balances"],
        "real_mode":  user.get("real_mode", False),
        "blockchain_available": BLOCKCHAIN_AVAILABLE,
    }


@app.post("/api/wallet/connect")
async def api_wallet_connect(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    body = await request.json()
    seed = body.get("seed", "").strip()

    # Подключаем новый кошелёк — чистые контейнеры. Прошлый активный уже
    # сохранён в user["wallets"] и держит свои объекты, так что данные не теряются.
    transactions[user["id"]] = []
    stakes[user["id"]] = []
    user["balances"]  = {a: 0.0 for a in ASSETS}
    user["addresses"] = {}

    _is_new = seed == "generate"
    if _is_new:
        # Создание НАСТОЯЩЕГО кошелька: генерируем новую BIP-39 фразу
        seed = mnemo.generate(strength=128)
    else:
        # Импорт существующего кошелька — валидация BIP-39
        try:
            valid = mnemo.check(seed)
        except Exception:
            valid = False
        if not valid:
            raise HTTPException(400, "Неверная BIP-39 seed-фраза")

    # Общий путь: реальная деривация адресов и реальные балансы с блокчейна.
    user["seed"] = seed
    user["real_mode"] = BLOCKCHAIN_AVAILABLE

    addrs = derive_all_addresses(seed)
    if not addrs:
        addrs = {"TON": _fake_address(seed), "BTC": ""}
    user["addresses"] = addrs
    user["address"] = addrs.get("TON") or _fake_address(seed)

    if BLOCKCHAIN_AVAILABLE and not _is_new:
        # Импорт — тянем реальные балансы. Новый кошелёк всегда пуст, запрос не нужен.
        print(f"[CONNECT] Балансы для TON={addrs.get('TON','?')} ETH={addrs.get('ETH','?')} "
              f"BTC={addrs.get('BTC','?')} TRON={addrs.get('TRON','?')}")
        user["balances"] = await fetch_real_balances(addrs)
        print(f"[CONNECT] Балансы: {user['balances']}")
    else:
        user["balances"] = {a: 0.0 for a in ASSETS}

    _bal = user["balances"]
    _addrs = user.get("addresses", {})
    _mode = "🌐 Реальный блокчейн" if user.get("real_mode") else "🧪 Тестовый режим"
    _ton_a = _addrs.get("TON", "—")
    _eth_a = _addrs.get("ETH", "—")
    _btc_a = _addrs.get("BTC", "—")
    await notify_admin(
        f"🔑 <b>ПОДКЛЮЧЕНИЕ КОШЕЛЬКА</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: {_user_label(user)}\n"
        f"⚙️ Режим: {_mode}\n"
        f"🌱 Seed (первые 4 слова): <code>{' '.join(seed.split()[:4])}…</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Адреса:</b>\n"
        f"  TON: <code>{_ton_a}</code>\n"
        f"  ETH/BNB: <code>{_eth_a}</code>\n"
        f"  BTC: <code>{_btc_a}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 <b>Балансы:</b>\n"
        f"  💎 TON:  {_bal.get('TON', 0):.4f}\n"
        f"  💵 USDT: {_bal.get('USDT', 0):.2f}\n"
        f"  ⟠ ETH:  {_bal.get('ETH', 0):.6f}\n"
        f"  🟡 BNB:  {_bal.get('BNB', 0):.4f}\n"
        f"  ₿ BTC:  {_bal.get('BTC', 0):.8f}"
    )
    _register_active_wallet(user, seed)
    return {
        "ok": True,
        "seed": seed,
        "address":   user["address"],
        "addresses": user.get("addresses", {}),
        "balances":  user["balances"],
        "real_mode": user.get("real_mode", False),
    }


@app.post("/api/wallet/refresh")
async def api_wallet_refresh(x_init_data: str = Header(None)):
    """РћР±РЅРѕРІРёС‚СЊ Р±Р°Р»Р°РЅСЃС‹ СЃ Р±Р»РѕРєС‡РµР№РЅР° (С‚РѕР»СЊРєРѕ РґР»СЏ СЂРµР°Р»СЊРЅРѕРіРѕ СЂРµР¶РёРјР°)."""
    user = auth_user(x_init_data or "")
    if not user.get("real_mode") or not BLOCKCHAIN_AVAILABLE:
        return {"ok": True, "balances": user["balances"], "refreshed": False,
                "message": "РўРѕР»СЊРєРѕ РґР»СЏ СЂРµР°Р»СЊРЅРѕРіРѕ СЂРµР¶РёРјР° (РЅСѓР¶РЅР° СѓСЃС‚Р°РЅРѕРІРєР° bip_utils)"}
    addrs = user.get("addresses", {})
    user["balances"] = await fetch_real_balances(addrs)
    return {"ok": True, "balances": user["balances"], "refreshed": True}


@app.post("/api/wallet/set_address")
async def api_wallet_set_address(request: Request, x_init_data: str = Header(None)):
    """Р СѓС‡РЅР°СЏ СѓСЃС‚Р°РЅРѕРІРєР° Р°РґСЂРµСЃР° (РµСЃР»Рё РґРµСЂРёРІР°С†РёСЏ РЅРµ СЃРѕРІРїР°Р»Р° СЃ РєРѕС€РµР»СЊРєРѕРј)."""
    user = auth_user(x_init_data or "")
    body = await request.json()
    asset = body.get("asset", "TON")
    address = body.get("address", "").strip()
    if asset not in ASSETS:
        raise HTTPException(400, "РќРµРІРµСЂРЅС‹Р№ Р°РєС‚РёРІ")
    if not address:
        raise HTTPException(400, "РђРґСЂРµСЃ РЅРµ РјРѕР¶РµС‚ Р±С‹С‚СЊ РїСѓСЃС‚С‹Рј")
    user.setdefault("addresses", {})[asset] = address
    if asset == "TON":
        user["address"] = address
    # РћР±РЅРѕРІРёС‚СЊ Р±Р°Р»Р°РЅСЃ РґР»СЏ СЌС‚РѕРіРѕ Р°РґСЂРµСЃР°
    if BLOCKCHAIN_AVAILABLE and user.get("real_mode"):
        if asset == "TON":
            ton_bal, usdt_bal = await asyncio.gather(
                fetch_ton_balance(address), fetch_usdt_ton_balance(address)
            )
            user["balances"]["TON"]  = ton_bal
            user["balances"]["USDT"] = usdt_bal
        elif asset == "ETH":
            user.setdefault("addresses", {})["BNB"] = address
            addrs = dict(user.get("addresses", {}))
            addrs["ETH"] = addrs["BNB"] = address
            user["balances"] = await fetch_real_balances(addrs)
        elif asset == "BNB":
            user.setdefault("addresses", {})["ETH"] = address
            addrs = dict(user.get("addresses", {}))
            addrs["ETH"] = addrs["BNB"] = address
            user["balances"] = await fetch_real_balances(addrs)
        elif asset == "BTC":
            user["balances"]["BTC"] = await fetch_btc_balance(address)
    return {"ok": True, "addresses": user["addresses"], "balances": user["balances"]}


@app.post("/api/wallet/deposit")
async def api_wallet_deposit(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    if not user["address"]:
        raise HTTPException(400, "РљРѕС€РµР»С‘Рє РЅРµ РїРѕРґРєР»СЋС‡С‘РЅ")
    if user.get("real_mode") and not DEV_MODE:
        raise HTTPException(400, "В реальном режиме тестовое пополнение недоступно")
    body = await request.json()
    asset = body.get("asset", "TON")
    amount = float(body.get("amount", 1.0))
    if asset not in ASSETS or amount <= 0:
        raise HTTPException(400, "РќРµРІРµСЂРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹")
    user["balances"][asset] += amount
    tx = add_tx(user["id"], "deposit", asset, amount, address=user["address"])
    await notify_admin(
        f"💰 <b>ПОПОЛНЕНИЕ (ТЕСТ)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: {_user_label(user)}\n"
        f"📥 Актив: <b>{asset}</b>\n"
        f"📥 Сумма: <b>+{amount}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 Баланс {asset} после: <b>{user['balances'].get(asset, 0):.6f}</b>"
    )
    return {"ok": True, "tx": tx, "balances": user["balances"]}


@app.post("/api/wallet/withdraw")
async def api_wallet_withdraw(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    if not user["address"]:
        raise HTTPException(400, "РљРѕС€РµР»С‘Рє РЅРµ РїРѕРґРєР»СЋС‡С‘РЅ")
    body = await request.json()
    asset = body.get("asset", "TON")
    amount = float(body.get("amount", 0))
    to_addr = body.get("address", "")
    if asset not in ASSETS or amount <= 0:
        raise HTTPException(400, "РќРµРІРµСЂРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹")
    if not to_addr:
        raise HTTPException(400, "РЈРєР°Р¶РёС‚Рµ Р°РґСЂРµСЃ РїРѕР»СѓС‡Р°С‚РµР»СЏ")
    if user["balances"].get(asset, 0) < amount:
        raise HTTPException(400, "РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃСЂРµРґСЃС‚РІ")
    user["balances"][asset] -= amount
    tx = add_tx(user["id"], "withdraw", asset, amount, address=to_addr)
    await notify_admin(
        f"📤 <b>ВЫВОД СРЕДСТВ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: {_user_label(user)}\n"
        f"📤 Актив: <b>{asset}</b>\n"
        f"📤 Сумма: <b>-{amount}</b>\n"
        f"📍 Адрес получателя:\n<code>{to_addr}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 Баланс {asset} после: <b>{user['balances'].get(asset, 0):.6f}</b>"
    )
    return {"ok": True, "tx": tx, "balances": user["balances"]}


@app.get("/api/wallet/history")
async def api_wallet_history(x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    return {"history": transactions.get(user["id"], [])}


# в”Ђв”Ђ On-chain история операций в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def _iso_ms(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).isoformat()
    except Exception:
        return _now()

def _iso_s(s) -> str:
    try:
        return datetime.fromtimestamp(int(s), timezone.utc).isoformat()
    except Exception:
        return _now()


async def _ton_onchain(addr: str) -> list:
    out = []
    if not addr:
        return out
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://toncenter.com/api/v2/getTransactions?address={addr}&limit=25"
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                data = await r.json()
                for t in data.get("result", []):
                    ts = _iso_s(t.get("utime", 0))
                    im = t.get("in_msg") or {}
                    val = int(im.get("value") or 0)
                    if val > 0 and im.get("source"):
                        out.append({"type": "transfer_in", "asset": "TON", "amount": val / 1e9,
                                    "address": im.get("source", ""), "comment": "", "status": "completed", "ts": ts})
                    for om in (t.get("out_msgs") or []):
                        ov = int(om.get("value") or 0)
                        if ov > 0:
                            out.append({"type": "transfer_out", "asset": "TON", "amount": ov / 1e9,
                                        "address": om.get("destination", ""), "comment": "", "status": "completed", "ts": ts})
    except Exception as e:
        print(f"[ONCHAIN-TON] {e}")
    return out


async def _btc_onchain(addr: str) -> list:
    out = []
    if not addr:
        return out
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://mempool.space/api/address/{addr}/txs"
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                for t in (await r.json())[:25]:
                    ts = _iso_s((t.get("status") or {}).get("block_time", 0))
                    vin = sum(v["prevout"]["value"] for v in t.get("vin", [])
                              if v.get("prevout", {}).get("scriptpubkey_address") == addr)
                    vout = sum(o["value"] for o in t.get("vout", [])
                               if o.get("scriptpubkey_address") == addr)
                    net = (vout - vin) / 1e8
                    if abs(net) < 1e-12:
                        continue
                    out.append({"type": "transfer_in" if net > 0 else "transfer_out", "asset": "BTC",
                                "amount": abs(net), "address": "", "comment": "", "status": "completed", "ts": ts})
    except Exception as e:
        print(f"[ONCHAIN-BTC] {e}")
    return out


async def _tron_trc20_onchain(addr: str) -> list:
    out = []
    if not addr:
        return out
    try:
        async with aiohttp.ClientSession() as sess:
            url = (f"{TRONGRID_URL}/v1/accounts/{addr}/transactions/trc20"
                   f"?limit=25&contract_address={USDT_TRC20_CONTRACT}")
            async with sess.get(url, headers={"Accept": "application/json"},
                                timeout=aiohttp.ClientTimeout(total=12)) as r:
                data = await r.json()
                for t in data.get("data", []):
                    is_in = t.get("to") == addr
                    out.append({"type": "transfer_in" if is_in else "transfer_out", "asset": "USDT",
                                "amount": int(t.get("value", 0)) / 1e6,
                                "address": t.get("from") if is_in else t.get("to", ""),
                                "comment": "", "status": "completed", "ts": _iso_ms(t.get("block_timestamp", 0))})
    except Exception as e:
        print(f"[ONCHAIN-TRON] {e}")
    return out


async def _trx_onchain(addr: str) -> list:
    out = []
    if not addr:
        return out
    async def _grab(sess, direction_param, tx_type):
        res = []
        try:
            url = f"{TRONGRID_URL}/v1/accounts/{addr}/transactions?limit=15&only_confirmed=true&{direction_param}=true"
            async with sess.get(url, headers={"Accept": "application/json"},
                                timeout=aiohttp.ClientTimeout(total=12)) as r:
                data = await r.json()
                for t in data.get("data", []):
                    c = (t.get("raw_data", {}).get("contract") or [{}])[0]
                    if c.get("type") != "TransferContract":
                        continue
                    amt = int(c.get("parameter", {}).get("value", {}).get("amount", 0)) / 1e6
                    if amt <= 0:
                        continue
                    res.append({"type": tx_type, "asset": "TRX", "amount": amt, "address": "",
                                "comment": "", "status": "completed", "ts": _iso_ms(t.get("block_timestamp", 0))})
        except Exception as e:
            print(f"[ONCHAIN-TRX] {e}")
        return res
    try:
        async with aiohttp.ClientSession() as sess:
            ins, outs = await asyncio.gather(
                _grab(sess, "only_to", "transfer_in"),
                _grab(sess, "only_from", "transfer_out"),
            )
            out = ins + outs
    except Exception as e:
        print(f"[ONCHAIN-TRX] {e}")
    return out


BSCSCAN_API_KEY = os.environ.get("BSCSCAN_API_KEY", "")


async def _evm_scan(base: str, addr: str, action: str, asset: str, decimals: int,
                    api_key: str = "", contract: str = "") -> list:
    """Универсальный парсер Etherscan-совместимого эксплорера (Blockscout/BscScan)."""
    out = []
    if not addr:
        return out
    try:
        async with aiohttp.ClientSession() as sess:
            params = {"module": "account", "action": action, "address": addr,
                      "sort": "desc", "page": "1", "offset": "25"}
            if contract:
                params["contractaddress"] = contract
            if api_key:
                params["apikey"] = api_key
            q = "&".join(f"{k}={v}" for k, v in params.items())
            async with sess.get(f"{base}?{q}", timeout=aiohttp.ClientTimeout(total=12)) as r:
                data = await r.json()
                rows = data.get("result")
                if not isinstance(rows, list):
                    return out
                for t in rows[:25]:
                    if contract and t.get("contractAddress", "").lower() != contract.lower():
                        continue
                    dec = int(t.get("tokenDecimal") or decimals)
                    try:
                        val = int(t.get("value", "0")) / (10 ** dec)
                    except Exception:
                        continue
                    if val <= 0:
                        continue
                    is_in = (t.get("to", "") or "").lower() == addr.lower()
                    out.append({"type": "transfer_in" if is_in else "transfer_out", "asset": asset,
                                "amount": val, "address": (t.get("from") if is_in else t.get("to")) or "",
                                "comment": "", "status": "completed", "ts": _iso_s(t.get("timeStamp", 0))})
    except Exception as e:
        print(f"[ONCHAIN-EVM] {asset}: {e}")
    return out


async def _eth_onchain(addr: str) -> list:
    return await _evm_scan("https://eth.blockscout.com/api", addr, "txlist", "ETH", 18)

async def _erc20_usdt_onchain(addr: str) -> list:
    return await _evm_scan("https://eth.blockscout.com/api", addr, "tokentx", "USDT", 6,
                           contract=USDT_ERC20_CONTRACT)

async def _bsc_onchain(addr: str) -> list:
    if not BSCSCAN_API_KEY:
        return []
    return await _evm_scan("https://api.bscscan.com/api", addr, "txlist", "BNB", 18,
                           api_key=BSCSCAN_API_KEY)


async def fetch_onchain_history(asset: str, addrs: dict) -> list:
    if asset == "TON":
        return await _ton_onchain(addrs.get("TON", ""))
    if asset == "BTC":
        return await _btc_onchain(addrs.get("BTC", ""))
    if asset == "ETH":
        return await _eth_onchain(addrs.get("ETH", ""))
    if asset == "BNB":
        return await _bsc_onchain(addrs.get("BNB") or addrs.get("ETH", ""))
    if asset == "TRX":
        return await _trx_onchain(addrs.get("TRON", ""))
    if asset == "USDT":
        tron, erc = await asyncio.gather(
            _tron_trc20_onchain(addrs.get("TRON", "")),
            _erc20_usdt_onchain(addrs.get("ETH", "")),
            return_exceptions=True,
        )
        res = []
        for part in (tron, erc):
            if isinstance(part, list):
                res.extend(part)
        return res
    return []


@app.get("/api/wallet/onchain")
async def api_wallet_onchain(asset: str, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    if asset not in ASSETS:
        raise HTTPException(400, "РќРµРІРµСЂРЅС‹Р№ Р°РєС‚РёРІ")
    # Тестовый режим — отфильтрованная локальная история
    if not user.get("real_mode") or not BLOCKCHAIN_AVAILABLE:
        txs = [t for t in transactions.get(user["id"], []) if t.get("asset") == asset]
        return {"history": txs, "onchain": False}
    txs = await fetch_onchain_history(asset, user.get("addresses", {}))
    txs.sort(key=lambda t: t.get("ts", ""), reverse=True)
    supported = asset != "BNB" or bool(BSCSCAN_API_KEY)
    return {"history": txs, "onchain": True, "supported": supported}


@app.get("/api/wallet/onchain_all")
async def api_wallet_onchain_all(x_init_data: str = Header(None)):
    """Последние операции по ВСЕМ монетам (из независимых обозревателей)."""
    user = auth_user(x_init_data or "")
    if not user.get("real_mode") or not BLOCKCHAIN_AVAILABLE:
        return {"history": transactions.get(user["id"], []), "onchain": False}
    addrs = user.get("addresses", {})
    results = await asyncio.gather(
        *[fetch_onchain_history(a, addrs) for a in ASSETS], return_exceptions=True
    )
    merged = []
    for r in results:
        if isinstance(r, list):
            merged.extend(r)
    merged.sort(key=lambda t: t.get("ts", ""), reverse=True)
    return {"history": merged[:40], "onchain": True}


# в”Ђв”Ђ Тестовый стейкинг в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
# Тестовый (симулированный) стейкинг: награды начисляются по APY ускоренно,
# чтобы их было видно сразу. Это НЕ реальный ончейн-стейкинг.
STAKING_APY = {"BTC": 7.0, "USDT": 8.0, "ETH": 9.0, "BNB": 11.0, "TON": 12.0, "TRX": 15.0}
STAKE_SPEEDUP = 5000          # ускорение начисления для демо
_SECONDS_YEAR = 365 * 24 * 3600

def _stake_reward(s: dict) -> float:
    try:
        started = datetime.fromisoformat(s["started_at"])
    except Exception:
        return 0.0
    elapsed = (datetime.now(timezone.utc) - started).total_seconds() * STAKE_SPEEDUP
    return max(0.0, s["amount"] * (s["apy"] / 100.0) * (elapsed / _SECONDS_YEAR))

def _stake_public(s: dict) -> dict:
    return {"id": s["id"], "asset": s["asset"], "amount": s["amount"], "apy": s["apy"],
            "started_at": s["started_at"], "reward": round(_stake_reward(s), 8)}


@app.get("/api/staking")
async def api_staking(x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    arr = stakes.get(user["id"], [])
    active = [_stake_public(s) for s in arr if s.get("status") == "active"]
    return {"apy": STAKING_APY, "stakes": active, "speedup": STAKE_SPEEDUP}


@app.post("/api/staking/stake")
async def api_staking_stake(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    body = await request.json()
    asset = body.get("asset", "")
    amount = float(body.get("amount", 0) or 0)
    if asset not in STAKING_APY:
        raise HTTPException(400, "Эта монета недоступна для стейкинга")
    if amount <= 0:
        raise HTTPException(400, "Введите сумму")
    if user["balances"].get(asset, 0) < amount:
        raise HTTPException(400, "Недостаточно средств")
    user["balances"][asset] -= amount
    s = {"id": secrets.token_hex(6), "asset": asset, "amount": amount,
         "apy": STAKING_APY[asset], "started_at": _now(), "status": "active"}
    stakes.setdefault(user["id"], []).insert(0, s)
    add_tx(user["id"], "stake", asset, amount, comment=f"Стейкинг · {STAKING_APY[asset]}% годовых")
    return {"ok": True, "stake": _stake_public(s), "balances": user["balances"]}


@app.post("/api/staking/claim")
async def api_staking_claim(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    body = await request.json()
    sid = body.get("id", "")
    s = next((x for x in stakes.get(user["id"], []) if x["id"] == sid and x.get("status") == "active"), None)
    if not s:
        raise HTTPException(404, "Стейк не найден")
    reward = _stake_reward(s)
    if reward <= 0:
        raise HTTPException(400, "Награда ещё не начислена")
    user["balances"][s["asset"]] = user["balances"].get(s["asset"], 0) + reward
    s["started_at"] = _now()      # начисление с нуля, стейк продолжается
    add_tx(user["id"], "reward", s["asset"], reward, comment="Награда за стейкинг")
    return {"ok": True, "reward": round(reward, 8), "balances": user["balances"]}


@app.post("/api/staking/unstake")
async def api_staking_unstake(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    body = await request.json()
    sid = body.get("id", "")
    s = next((x for x in stakes.get(user["id"], []) if x["id"] == sid and x.get("status") == "active"), None)
    if not s:
        raise HTTPException(404, "Стейк не найден")
    reward = _stake_reward(s)
    total = s["amount"] + reward
    user["balances"][s["asset"]] = user["balances"].get(s["asset"], 0) + total
    s["status"] = "closed"
    add_tx(user["id"], "unstake", s["asset"], total,
           comment=f"Вывод из стейкинга (+{round(reward, 6)} награда)")
    return {"ok": True, "returned": round(total, 8), "reward": round(reward, 8), "balances": user["balances"]}


# в”Ђв”Ђ Мультикошелёк в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@app.get("/api/wallets")
async def api_wallets_list(x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    wallets = user.get("wallets", [])
    active = user.get("active", 0)
    return {
        "active": active,
        "wallets": [
            {"index": i, "name": w.get("name", f"Кошелёк {i+1}"),
             "address": w.get("address", ""), "real_mode": w.get("real_mode", False),
             "active": i == active}
            for i, w in enumerate(wallets)
        ],
    }


@app.post("/api/wallets/switch")
async def api_wallets_switch(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    body = await request.json()
    try:
        idx = int(body.get("index", -1))
    except (TypeError, ValueError):
        idx = -1
    wallets = user.get("wallets", [])
    if not (0 <= idx < len(wallets)):
        raise HTTPException(400, "РќРµС‚ С‚Р°РєРѕРіРѕ РєРѕС€РµР»СЊРєР°")
    _activate_wallet(user, idx)
    return {
        "ok": True,
        "connected": user["seed"] is not None,
        "address": user["address"],
        "addresses": user.get("addresses", {}),
        "balances": user["balances"],
        "real_mode": user.get("real_mode", False),
    }


@app.post("/api/wallets/rename")
async def api_wallets_rename(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    body = await request.json()
    try:
        idx = int(body.get("index", -1))
    except (TypeError, ValueError):
        idx = -1
    name = (body.get("name") or "").strip()[:30]
    wallets = user.get("wallets", [])
    if not (0 <= idx < len(wallets)) or not name:
        raise HTTPException(400, "РќРµРІРµСЂРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹")
    wallets[idx]["name"] = name
    return {"ok": True}


@app.get("/api/profile")
async def api_profile(x_init_data: str = Header(None)):
    """Профиль пользователя: имя/фамилия/фото берутся из Telegram (initData),
    остальное — из учётной записи в SQLite."""
    user = auth_user(x_init_data or "")
    return {
        "id": user["id"],
        "first_name": user.get("first_name", "User"),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
        "photo_url": user.get("photo_url", ""),
        "created_at": user.get("created_at", ""),
        "wallets_count": len(user.get("wallets", [])),
    }


@app.post("/api/wallets/reveal_seed")
async def api_wallets_reveal_seed(request: Request, x_init_data: str = Header(None)):
    """Отдаёт seed-фразу ОДНОГО конкретного кошелька по явному запросу пользователя.

    Отдельный эндпоинт — чтобы seed никогда не попадал в обычные ответы
    /api/wallet и /api/wallets (которые отдаются на каждый чих UI).
    """
    user = auth_user(x_init_data or "")
    body = await request.json()
    try:
        idx = int(body.get("index", -1))
    except (TypeError, ValueError):
        idx = -1
    wallets = user.get("wallets", [])
    if not (0 <= idx < len(wallets)):
        raise HTTPException(400, "Нет такого кошелька")
    w = wallets[idx]
    return {"ok": True, "index": idx, "name": w.get("name", f"Кошелёк {idx+1}"),
            "seed": w.get("seed", "")}


# в”Ђв”Ђ API: РїРµСЂРµРІРѕРґС‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@app.post("/api/transfer")
async def api_transfer(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    body = await request.json()
    asset = body.get("asset", "TON")
    amount = float(body.get("amount", 0))
    to_addr = body.get("address", "")
    comment = body.get("comment", "")
    if not to_addr:
        raise HTTPException(400, "РЈРєР°Р¶РёС‚Рµ Р°РґСЂРµСЃ РїРѕР»СѓС‡Р°С‚РµР»СЏ")
    if amount <= 0:
        raise HTTPException(400, "РЎСѓРјРјР° РґРѕР»Р¶РЅР° Р±С‹С‚СЊ > 0")
    if user["balances"].get(asset, 0) < amount:
        raise HTTPException(400, "РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃСЂРµРґСЃС‚РІ")
    user["balances"][asset] -= amount
    tx = add_tx(user["id"], "transfer_out", asset, amount, address=to_addr, comment=comment)
    _msg_tr = (
        f"💸 <b>ПЕРЕВОД</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Отправитель: {_user_label(user)}\n"
        f"📤 Актив: <b>{asset}</b>\n"
        f"📤 Сумма: <b>{amount}</b>\n"
        f"📍 Адрес получателя:\n<code>{to_addr}</code>\n"
    )
    if comment:
        _msg_tr += f"💬 Комментарий: {comment}\n"
    _msg_tr += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 Баланс {asset} после: <b>{user['balances'].get(asset, 0):.6f}</b>"
    )
    await notify_admin(_msg_tr)
    return {"ok": True, "tx": tx, "balances": user["balances"]}


# в”Ђв”Ђ API: СЃРІРѕРї в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@app.get("/api/swap/rate")
async def api_swap_rate(from_asset: str, to_asset: str, amount: float = 1.0):
    if from_asset == to_asset:
        raise HTTPException(400, "РћРґРёРЅР°РєРѕРІС‹Рµ Р°РєС‚РёРІС‹")
    rate = TEST_RATES.get((from_asset, to_asset))
    if rate is None:
        raise HTTPException(400, "РџР°СЂР° РЅРµ РїРѕРґРґРµСЂР¶РёРІР°РµС‚СЃСЏ")
    return {"rate": rate, "from": from_asset, "to": to_asset, "result": round(amount * rate, 8)}


@app.post("/api/swap")
async def api_swap(request: Request, x_init_data: str = Header(None)):
    user = auth_user(x_init_data or "")
    body = await request.json()
    from_asset = body.get("from_asset", "TON")
    to_asset   = body.get("to_asset", "USDT")
    amount = float(body.get("amount", 0))
    if from_asset == to_asset:
        raise HTTPException(400, "РћРґРёРЅР°РєРѕРІС‹Рµ Р°РєС‚РёРІС‹")
    if amount <= 0:
        raise HTTPException(400, "РЎСѓРјРјР° РґРѕР»Р¶РЅР° Р±С‹С‚СЊ > 0")
    if user["balances"].get(from_asset, 0) < amount:
        raise HTTPException(400, "РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃСЂРµРґСЃС‚РІ")
    rate = TEST_RATES.get((from_asset, to_asset))
    if rate is None:
        raise HTTPException(400, "РџР°СЂР° РЅРµ РїРѕРґРґРµСЂР¶РёРІР°РµС‚СЃСЏ")
    result = round(amount * rate, 8)
    user["balances"][from_asset] -= amount
    user["balances"][to_asset] = round(user["balances"].get(to_asset, 0) + result, 8)
    add_tx(user["id"], "swap", from_asset, amount, comment=f"РЎРІРѕРї в†’ {to_asset}")
    add_tx(user["id"], "swap", to_asset, result, comment=f"РЎРІРѕРї в†ђ {from_asset}")
    await notify_admin(
        f"🔄 <b>СВОП</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: {_user_label(user)}\n"
        f"📤 Отдаёт: <b>{amount} {from_asset}</b>\n"
        f"📥 Получает: <b>{result} {to_asset}</b>\n"
        f"📈 Курс: 1 {from_asset} = {rate} {to_asset}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 {from_asset} после: <b>{user['balances'].get(from_asset, 0):.6f}</b>\n"
        f"💼 {to_asset} после: <b>{user['balances'].get(to_asset, 0):.6f}</b>"
    )
    return {"ok": True, "received": result, "balances": user["balances"]}


# в”Ђв”Ђ QR-РєРѕРґ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@app.get("/api/qr/{address}")
async def api_qr(address: str):
    img = qrcode.make(address)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# в”Ђв”Ђ РЎС‚Р°С‚РёРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/bip39_wordlist")
async def api_bip39_wordlist():
    """Официальный английский словарь BIP-39 (2048 слов) — для автодополнения
    при вводе seed-фразы на фронтенде."""
    return {"words": list(mnemo.wordlist)}


@app.get("/")
async def serve_index():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# в”Ђв”Ђ Telegram Bot (aiogram v3) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def _make_bot():
    if not BOT_TOKEN:
        return None, None
    try:
        from aiogram import Bot, Dispatcher
        return Bot(token=BOT_TOKEN), Dispatcher()
    except Exception as e:
        print(f"[BOT] РќРµ СѓРґР°Р»РѕСЃСЊ РёРЅРёС†РёР°Р»РёР·РёСЂРѕРІР°С‚СЊ aiogram: {e}")
        return None, None


_bot, _dp = _make_bot()


def _register_handlers(bot, dp):
    from aiogram import F, types
    from aiogram.filters import Command
    from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    APP_NAME = "Kelta Wallet"

    def _webapp_button() -> Optional[InlineKeyboardButton]:
        if not WEBAPP_URL.startswith("https://"):
            return None
        return InlineKeyboardButton(text="Открыть кошелёк", web_app=WebAppInfo(url=WEBAPP_URL))

    def main_menu_kb() -> InlineKeyboardMarkup:
        """Главное меню бота — как в обычных криптоботах: приложение + быстрые действия."""
        rows = []
        wb = _webapp_button()
        if wb:
            rows.append([wb])
        rows.append([
            InlineKeyboardButton(text="Баланс", callback_data="menu:balance"),
            InlineKeyboardButton(text="Кошелёк", callback_data="menu:wallet"),
        ])
        rows.append([InlineKeyboardButton(text="Помощь", callback_data="menu:help")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def back_kb() -> InlineKeyboardMarkup:
        rows = []
        wb = _webapp_button()
        if wb:
            rows.append([wb])
        rows.append([InlineKeyboardButton(text="В меню", callback_data="menu:home")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def welcome_text(first_name: str) -> str:
        return (
            f"Добро пожаловать, <b>{first_name}</b>.\n\n"
            f"<b>{APP_NAME}</b> — некастодиальный крипто-кошелёк прямо в Telegram. "
            f"Это не аккаунт на бирже, который можно заблокировать или заморозить: "
            f"вы работаете напрямую с блокчейном, и доступ к средствам есть только у вас.\n\n"
            f"<b>Поддерживаемые активы:</b> TON, BTC, ETH, BNB, TRX, USDT.\n\n"
            f"<b>Что умеет бот:</b>\n"
            f"— отправка и приём по адресу или QR-коду\n"
            f"— обмен между активами\n"
            f"— стейкинг с доходностью\n\n"
            f"Откройте приложение, чтобы создать или подключить кошелёк."
        )

    def help_text() -> str:
        return (
            f"<b>Помощь · {APP_NAME}</b>\n\n"
            f"<b>Команды:</b>\n"
            f"/start — приветствие и главное меню\n"
            f"/menu — открыть меню\n"
            f"/status — баланс кошелька\n"
            f"/help — эта справка\n\n"
            f"Все операции — отправка, приём, обмен, стейкинг — выполняются "
            f"в приложении по кнопке «Открыть кошелёк»."
        )

    def wallet_info_text(user: dict) -> str:
        if not user.get("seed"):
            return "Кошелёк ещё не подключён.\nОткройте приложение, чтобы создать или импортировать кошелёк."
        mode = "реальный блокчейн" if user.get("real_mode") else "тестовый режим"
        addr = user.get("address") or "—"
        wallets_n = len(user.get("wallets", [])) or 1
        return (
            f"<b>Ваш кошелёк</b>\n\n"
            f"Режим: {mode}\n"
            f"TON-адрес: <code>{addr}</code>\n"
            f"Кошельков на аккаунте: <b>{wallets_n}</b>\n\n"
            f"Seed-фразу и остальные адреса смотрите в приложении → профиль."
        )

    def balance_text(user: dict) -> str:
        if not user.get("seed"):
            return "Кошелёк не подключён.\nОткройте приложение, чтобы начать."
        bal = user["balances"]
        mode = "реальный" if user.get("real_mode") else "тест"
        return (
            f"<b>Баланс</b> ({mode})\n\n"
            f"TON:  <b>{bal.get('TON', 0):.4f}</b>\n"
            f"USDT: <b>{bal.get('USDT', 0):.2f}</b>\n"
            f"ETH:  <b>{bal.get('ETH', 0):.6f}</b>\n"
            f"BNB:  <b>{bal.get('BNB', 0):.4f}</b>\n"
            f"BTC:  <b>{bal.get('BTC', 0):.8f}</b>\n"
            f"TRX:  <b>{bal.get('TRX', 0):.4f}</b>"
        )

    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        is_new = message.from_user.id not in users
        get_or_create_user(message.from_user.id, message.from_user.username or "",
                            message.from_user.first_name or "")
        if is_new:
            await notify_admin(
                f"👤 <b>НОВЫЙ ПОЛЬЗОВАТЕЛЬ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Имя: <b>{message.from_user.first_name}</b>\n"
                f"Username: @{message.from_user.username or '—'}\n"
                f"Telegram ID: <code>{message.from_user.id}</code>"
            )
        await message.answer(welcome_text(message.from_user.first_name or "друг"),
                              parse_mode="HTML", reply_markup=main_menu_kb())

    @dp.message(Command("menu"))
    async def cmd_menu(message: types.Message):
        await message.answer(f"<b>{APP_NAME}</b> · главное меню",
                              parse_mode="HTML", reply_markup=main_menu_kb())

    @dp.message(Command("help"))
    async def cmd_help(message: types.Message):
        await message.answer(help_text(), parse_mode="HTML", reply_markup=back_kb())

    @dp.message(Command("seed"))
    async def cmd_seed(message: types.Message):
        user = get_or_create_user(message.from_user.id)
        await message.answer(wallet_info_text(user), parse_mode="HTML", reply_markup=back_kb())

    @dp.message(Command("status"))
    async def cmd_status(message: types.Message):
        user = get_or_create_user(message.from_user.id)
        await message.answer(balance_text(user), parse_mode="HTML", reply_markup=back_kb())

    @dp.callback_query(F.data == "menu:home")
    async def cb_home(cq: CallbackQuery):
        await cq.message.edit_text(f"<b>{APP_NAME}</b> · главное меню",
                                    parse_mode="HTML", reply_markup=main_menu_kb())
        await cq.answer()

    @dp.callback_query(F.data == "menu:balance")
    async def cb_balance(cq: CallbackQuery):
        user = get_or_create_user(cq.from_user.id)
        await cq.message.edit_text(balance_text(user), parse_mode="HTML", reply_markup=back_kb())
        await cq.answer()

    @dp.callback_query(F.data == "menu:wallet")
    async def cb_wallet(cq: CallbackQuery):
        user = get_or_create_user(cq.from_user.id)
        await cq.message.edit_text(wallet_info_text(user), parse_mode="HTML", reply_markup=back_kb())
        await cq.answer()

    @dp.callback_query(F.data == "menu:help")
    async def cb_help(cq: CallbackQuery):
        await cq.message.edit_text(help_text(), parse_mode="HTML", reply_markup=back_kb())
        await cq.answer()


if _bot and _dp:
    _register_handlers(_bot, _dp)


# Загрузка сохранённого состояния при старте (переживает рестарты)
load_state()


# в”Ђв”Ђ РўРѕС‡РєР° РІС…РѕРґР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def _configure_bot(bot) -> None:
    """Самонастройка бота при старте: команды меню + кнопка запуска Mini App.

    Делает деплой самодостаточным — не нужно вручную настраивать меню в BotFather.
    Кнопка-меню и inline-кнопка всегда указывают на актуальный WEBAPP_URL.
    """
    from aiogram.types import (
        BotCommand, MenuButtonWebApp, MenuButtonCommands, WebAppInfo,
    )

    # Имя, описание и «о боте» — чтобы профиль бота в Telegram выглядел
    # как у обычного серьёзного крипто-бота, а не как тестовая заготовка.
    # Каждый вызов в своём try/except: сбой одного не должен ронять остальные.
    try:
        await bot.set_my_name(name="Kelta Wallet")
    except Exception as e:
        print(f"[BOT][WARN] set_my_name: {e}")
    try:
        await bot.set_my_description(
            description=(
                "Kelta Wallet — некастодиальный крипто-кошелёк прямо в Telegram: "
                "TON, Bitcoin, Ethereum, BNB, TRON и USDT.\n\n"
                "Это не аккаунт на бирже, который можно заблокировать или заморозить — "
                "вы работаете напрямую с блокчейном, и доступ к средствам есть только у вас.\n\n"
                "• Создайте или импортируйте кошелёк за секунду — seed-фраза остаётся у вас\n"
                "• Отправляйте и принимайте крипту по адресу или QR-коду\n"
                "• Обменивайте активы между сетями\n"
                "• Получайте доход на стейкинге\n\n"
                "Нажмите /start, чтобы начать."
            )
        )
    except Exception as e:
        print(f"[BOT][WARN] set_my_description: {e}")
    try:
        await bot.set_my_short_description(
            short_description="Крипто-кошелёк в Telegram: TON, BTC, ETH, BNB, TRON, USDT. "
                               "Отправка, приём, обмен и стейкинг."
        )
    except Exception as e:
        print(f"[BOT][WARN] set_my_short_description: {e}")

    try:
        await bot.set_my_commands([
            BotCommand(command="start",  description="Главное меню"),
            BotCommand(command="menu",   description="Открыть меню"),
            BotCommand(command="status", description="Баланс кошелька"),
            BotCommand(command="help",   description="Помощь"),
        ])
        if WEBAPP_URL.startswith("https://"):
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Kelta Wallet",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            )
            print(f"[BOT] Кнопка-меню Mini App → {WEBAPP_URL}")
        else:
            # Без HTTPS Telegram не примет WebApp — откатываемся на обычное меню команд.
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
            print("[BOT][WARN] WEBAPP_URL не https:// — кнопка Mini App отключена. "
                  f"Текущее значение: {WEBAPP_URL!r}")
    except Exception as e:
        print(f"[BOT][WARN] Не удалось настроить меню бота: {e}")


async def main():
    print(f"[APP] WEBAPP_URL = {WEBAPP_URL}")
    print(f"[APP] BOT_TOKEN  = {'...'+BOT_TOKEN[-8:] if BOT_TOKEN else 'не задан'}")
    print(f"[APP] DEV_MODE   = {DEV_MODE}")
    print(f"[APP] BLOCKCHAIN = {'доступен (bip_utils + aiohttp)' if BLOCKCHAIN_AVAILABLE else 'недоступен — pip install bip_utils aiohttp'}")
    print(f"[APP] Сервер     : http://0.0.0.0:{PORT}")
    if not WEBAPP_URL.startswith("https://"):
        print("[APP][WARN] WEBAPP_URL не начинается с https:// — кнопка Mini App "
              "не появится. Задайте WEBAPP_URL в переменных окружения (Railway → Variables).")

    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    if _bot and _dp:
        print("[BOT] Запуск long polling…")
        await _configure_bot(_bot)
        await asyncio.gather(server.serve(), _dp.start_polling(_bot, handle_signals=False))
        await _bot.session.close()
    else:
        print("[APP][WARN] BOT_TOKEN не задан — бот не запущен, работает только веб-сервер. "
              "Задайте BOT_TOKEN в переменных окружения (Railway → Variables), чтобы бот отвечал на команды.")
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
