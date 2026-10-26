"""MCGen Bot — Telegram-бот + Mini App: ИИ-генерация контента для Minecraft.

Оплата подписок — Telegram Stars (XTR). Звёзды зачисляются на баланс этого бота,
вывести их может только владелец бота (через fragment.com), см. ЧИТАЙ_МЕНЯ.txt.
"""
import asyncio
import hashlib
import hmac
import html
import io
import json
import logging
import secrets
import time
import urllib.parse

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    MenuButtonWebApp,
    Message,
    PreCheckoutQuery,
    WebAppInfo,
)

import config
import db
import emailer
import generator
import packaging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mcgen")

router = Router()
bot = None  # создаётся в main()
pending_kind: dict = {}  # user_id -> выбранный тип генерации в чате

KINDS = {
    "addon": "🧩 Аддон для Bedrock",
    "datapack": "📦 Датапак для Java",
    "plugin": "⚙️ Плагин для сервера",
    "mod": "🛠 Мод для Java (Fabric)",
    "map": "🗺 Карта (Java)",
}
TIERS = {"free": "Бесплатный", "pro": "Про", "creator": "Креатор"}


def current_public_url() -> str:
    """Туннель периодически меняет адрес — перечитываем .env на лету."""
    try:
        for line in (config.ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("PUBLIC_URL="):
                return line.partition("=")[2].strip().rstrip("/")
    except OSError:
        pass
    return config.PUBLIC_URL


# ---------------------------------------------------------------- helpers
def is_owner(user) -> bool:
    return user.id == config.OWNER_ID or (user.username or "").lower() == config.OWNER_USERNAME


def user_tier(uid: int) -> str:
    return db.effective_tier(db.get_user(uid))


def main_kb():
    rows = []
    url = current_public_url()
    if url:
        rows.append([InlineKeyboardButton(text="🎨 Открыть студию", web_app=WebAppInfo(url=url))])
    rows.append([
        InlineKeyboardButton(text="💎 Подписки", callback_data="buy_menu"),
        InlineKeyboardButton(text="🎲 Создать в чате", callback_data="gen"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buy_menu_text(tier: str) -> str:
    return (
        "💎 <b>Тарифы MCGen</b>\n\n"
        f"🆓 <b>Бесплатный</b> — 0⭐\n"
        f"· {config.FREE_DAILY} генераций в день\n"
        f"· базовая модель, простые аддоны/датапаки\n\n"
        f"⭐ <b>Про</b> — {config.PRO_STARS}⭐/мес\n"
        f"· {config.PRO_DAILY} генераций в день\n"
        f"· продвинутая модель: рецепты, лут, события, анимации\n\n"
        f"⭐⭐ <b>Креатор</b> — {config.CREATOR_STARS}⭐/мес\n"
        f"· {config.CREATOR_DAILY} генераций в день\n"
        f"· самая мощная модель: 3–5 сущностей, скрипты, целые мини-контент-паки\n\n"
        f"Твой тариф: <b>{TIERS[tier]}</b>"
    )


def buy_kb(tier: str):
    rows = []
    if tier != "pro":
        rows.append([InlineKeyboardButton(text=f"⭐ Про — {config.PRO_STARS}⭐/мес", callback_data="buy:pro")])
    if tier != "creator":
        rows.append([InlineKeyboardButton(text=f"⭐⭐ Креатор — {config.CREATOR_STARS}⭐/мес", callback_data="buy:creator")])
    if current_public_url():
        rows.append([InlineKeyboardButton(text="🎨 Открыть студию", web_app=WebAppInfo(url=current_public_url()))])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def friendly_error(e: Exception) -> str:
    s = str(e)
    if isinstance(e, generator.NoKeyError) or "NO_KEY" in s:
        return "🔑 ИИ ещё не подключён: владелец должен вписать OPENROUTER_API_KEY в файл .env"
    if "КЛЮЧ_НЕВЕРНЫЙ" in s:
        return "🔑 API-ключ неверный — проверь OPENROUTER_API_KEY в .env"
    if isinstance(e, generator.AllModelsFailedError) or "Все модели" in s:
        return "😴 Все ИИ-модели сейчас перегружены или у них кончились дневные лимиты. Попробуй через 10–15 минут."
    if "ЛИМИТ_МОДЕЛИ" in s:
        return "😴 У бесплатной модели закончился дневной лимит. Попробуй позже или попроси владельца сменить MODEL_* в .env"
    if isinstance(e, ValueError):
        return "🧩 " + s
    return "😕 Ошибка генерации: " + s[:200]


# ---------------------------------------------------------------- команды
@router.message(Command("start"))
async def cmd_start(m: Message):
    db.ensure_user(m.from_user.id, m.from_user.username or "")
    tier = user_tier(m.from_user.id)
    await m.answer(
        f"Привет, <b>{html.escape(m.from_user.first_name or 'игрок')}</b>! ⛏\n\n"
        "Я <b>MCGen</b> — ИИ-студия контента для Minecraft:\n"
        "аддоны для Bedrock, датапаки, плагины, моды и карты.\n\n"
        f"Твой тариф: <b>{TIERS[tier]}</b> · генераций осталось сегодня: {db.gens_left(m.from_user.id, tier)}",
        reply_markup=main_kb(),
    )


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(
        "🎲 <b>Как создать</b>\n"
        "1. Нажми «Создать в чате» (или открой студию)\n"
        "2. Выбери тип: аддон / датапак / плагин / мод / карта\n"
        "3. Опиши, что сделать — получишь готовый файл через 1–3 мин\n\n"
        "💎 /mysub — мой тариф и лимиты\n"
        "💎 /start → Подписки — купить Про или Креатор за звёзды ⭐",
        reply_markup=main_kb(),
    )


@router.message(Command("mysub"))
async def cmd_mysub(m: Message):
    db.ensure_user(m.from_user.id, m.from_user.username or "")
    row = db.get_user(m.from_user.id)
    tier = db.effective_tier(row)
    if tier == "free":
        text = f"Твой тариф: <b>Бесплатный</b>\nОсталось сегодня: {db.gens_left(m.from_user.id, tier)}"
    else:
        exp = time.strftime("%d.%m.%Y", time.localtime(row["expires_at"]))
        text = (f"Твой тариф: <b>{TIERS[tier]}</b> ⭐\n"
                f"Действует до: {exp}\n"
                f"Осталось сегодня: {db.gens_left(m.from_user.id, tier)}")
    await m.answer(text, reply_markup=buy_kb(tier) if tier == "free" else main_kb())


# ---------------------------------------------------------------- оплата
@router.callback_query(F.data == "buy_menu")
async def cb_buy_menu(q: Message):
    tier = user_tier(q.from_user.id)
    await q.message.edit_text(buy_menu_text(tier), reply_markup=buy_kb(tier))
    await q.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(q):
    tier = q.data.split(":", 1)[1]
    if tier not in ("pro", "creator"):
        return await q.answer()
    stars = config.PRO_STARS if tier == "pro" else config.CREATOR_STARS
    try:
        await bot.send_invoice(
            chat_id=q.message.chat.id,
            title=f"Подписка {TIERS[tier]} — 30 дней",
            description=(f"{config.PRO_DAILY if tier == 'pro' else config.CREATOR_DAILY} генераций в день, "
                         "мощная модель, приоритетная очередь."),
            payload=f"sub:{tier}",
            currency="XTR",
            prices=[LabeledPrice(label=TIERS[tier], amount=stars)],
        )
        await q.answer("Открываю оплату ⭐")
    except Exception as e:
        log.exception("invoice failed")
        await q.answer("Не удалось выставить счёт: " + str(e)[:100], show_alert=True)


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def on_paid(m: Message):
    sp = m.successful_payment
    tier = sp.invoice_payload.split(":")[-1]
    db.ensure_user(m.from_user.id, m.from_user.username or "")
    db.set_sub(m.from_user.id, m.from_user.username or "", tier, config.SUB_DAYS)
    db.save_purchase(sp.telegram_payment_charge_id, m.from_user.id,
                     m.from_user.username or "", tier, sp.total_amount)
    await emailer.notify_purchase(
        m.from_user.username or str(m.from_user.id), m.from_user.id,
        TIERS.get(tier, tier), sp.total_amount, sp.telegram_payment_charge_id,
    )
    if config.OWNER_ID:  # дубль отчёта владельцу в Telegram (на случай, если SMTP недоступен)
        try:
            await bot.send_message(
                config.OWNER_ID,
                f"💰 Покупка: @{m.from_user.username or m.from_user.id} — "
                f"{TIERS.get(tier, tier)} — {sp.total_amount}⭐")
        except Exception:
            pass
    await m.answer(
        f"🎉 Оплата получена — подписка <b>{TIERS.get(tier, tier)}</b> активна на {config.SUB_DAYS} дней!\n"
        f"Лимит генераций теперь {db.LIMITS[tier]} в день. Спасибо! ⭐"
    )


# ---------------------------------------------------------------- генерация в чате
@router.callback_query(F.data == "start")
async def cb_start(q):
    await q.message.delete()
    await cmd_start(q.message)


@router.callback_query(F.data == "gen")
async def cb_gen(q):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"kind:{kind}")] for kind, label in KINDS.items()
    ] + [[InlineKeyboardButton(text="⬅️ Отмена", callback_data="start")]])
    await q.message.edit_text("🎲 <b>Что создаём?</b>", reply_markup=kb)
    await q.answer()


@router.callback_query(F.data.startswith("kind:"))
async def cb_kind(q):
    kind = q.data.split(":", 1)[1]
    if kind not in KINDS:
        return await q.answer()
    pending_kind[q.from_user.id] = kind
    await q.message.edit_text(
        f"{KINDS[kind]}\n\n✍️ Опиши, что сделать (одним сообщением).\n"
        "Например: <i>магический камень, светится, наносит урон мобам рядом, можно скрафтить из аметиста</i>"
    )
    await q.answer()


@router.message(F.text, ~F.text.startswith("/"))
async def on_text(m: Message):
    uid = m.from_user.id
    if uid not in pending_kind:
        await m.answer("Нажми «🎲 Создать в чате» и выбери тип контента 🙂", reply_markup=main_kb())
        return
    kind = pending_kind.pop(uid)
    db.ensure_user(uid, m.from_user.username or "")
    await generate_and_send(m.chat.id, uid, kind, m.text.strip())


async def generate_and_send(chat_id, uid: int, kind: str, prompt: str):
    tier = user_tier(uid)
    if db.gens_left(uid, tier) <= 0:
        await bot.send_message(
            chat_id,
            f"⏳ Дневной лимит тарифа «{TIERS[tier]}» исчерпан.\n"
            "Улучши тариф: /start → 💎 Подписки")
        return
    status = await bot.send_message(chat_id, "🧠 Генерирую, 1–3 минуты…")
    try:
        raw = await generator.generate(tier, kind, prompt)
        spec = packaging.extract_spec(raw)
        fname, data = packaging.build(spec, kind)
        db.record_gen(uid)
        fn = secrets.token_hex(6) + "_" + fname
        (config.ROOT / "files").mkdir(exist_ok=True)
        (config.ROOT / "files" / fn).write_bytes(data)
        db.add_gallery_item(secrets.token_hex(5), str(spec.get("name", ""))[:60],
                            kind, tier, (db.get_user(uid)["username"] if db.get_user(uid) else ""), fn)
        caption = (f"📦 <b>{html.escape(str(spec.get('name', '')))}</b>\n"
                   f"{html.escape(str(spec.get('description', '')))}\n\n"
                   f"Тариф: {TIERS[tier]} · осталось сегодня: {db.gens_left(uid, tier)}")
        await bot.send_document(chat_id, document=BufferedInputFile(data, filename=fname), caption=caption)
        inst = str(spec.get("install", "")).strip()
        if inst:
            await bot.send_message(chat_id, "📥 <b>Установка:</b>\n" + html.escape(inst))
        await status.delete()
    except Exception as e:
        log.exception("generation failed")
        text = friendly_error(e)
        try:
            await status.edit_text(text)
        except Exception:
            await bot.send_message(chat_id, text)


@router.message(Command("top"))
async def cmd_top(m: Message):
    rows = db.top_gallery(10)
    if not rows:
        return await m.answer("🏆 Галерея пока пуста — сгенерируй что-нибудь и стань первым!")
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    lines = [
        f"{medals[i]} <b>{html.escape(r['name'])}</b> — {r['votes']} голосов · "
        f"{KINDS.get(r['kind'], r['kind'])} · @{r['username'] or 'аноним'}"
        for i, r in enumerate(rows)
    ]
    kb = main_kb() if current_public_url() else None
    await m.answer("🏆 <b>Топ работ сообщества:</b>\n\n" + "\n".join(lines)
                   + "\n\nГолосуй в мини-приложении → вкладка «Топ»", reply_markup=kb)


# ---------------------------------------------------------------- команды владельца
@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if not is_owner(m.from_user):
        return await m.answer("⛔ Только для владельца бота.")
    rows = db.purchases(30)
    total = sum(r["stars"] for r in rows if not r["refunded"])
    if not rows:
        return await m.answer("📊 Покупок пока нет. Всего звёзд: 0⭐")
    lines = [
        f"@{r['username'] or r['tg_id']} — {TIERS.get(r['tier'], r['tier'])} — {r['stars']}⭐ — "
        f"{time.strftime('%d.%m %H:%M', time.localtime(r['ts']))}{' ↩️' if r['refunded'] else ''}"
        for r in rows
    ]
    await m.answer(
        "📊 <b>Последние покупки:</b>\n" + "\n".join(lines)
        + f"\n\nВсего звёзд (без возвратов): <b>{total}⭐</b>\n"
        "Вывод звёзд — только владелец бота через fragment.com.")


@router.message(Command("refund"))
async def cmd_refund(m: Message):
    if not is_owner(m.from_user):
        return await m.answer("⛔ Только для владельца бота.")
    parts = (m.text or "").split()
    if len(parts) != 2:
        return await m.answer("Формат: <code>/refund &lt;id платежа&gt;</code> (id приходит в email-отчёте)")
    row = db.find_purchase(parts[1])
    if row is None:
        return await m.answer("Платёж не найден.")
    if row["refunded"]:
        return await m.answer("Этот платёж уже возвращён.")
    try:
        await bot.refund_star_payment(chat_id=row["tg_id"], telegram_payment_charge_id=row["charge_id"])
    except Exception as e:
        return await m.answer("Не удалось вернуть: " + str(e)[:200])
    db.mark_refunded(row["charge_id"])
    await m.answer(f"✅ Звёзды возвращены пользователю @{row['username'] or row['tg_id']}.")


# ---------------------------------------------------------------- самопингер
async def self_ping():
    """Каждые 9 минут дёргаем свой публичный адрес, чтобы Render не усыплял
    бесплатный инстанс (сон наступает через 15 минут без входящих запросов)."""
    await asyncio.sleep(60)
    while True:
        url = current_public_url()
        if url:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(url + "/", timeout=aiohttp.ClientTimeout(total=30)) as r:
                        log.info("self-ping %s -> %s", url, r.status)
            except Exception as e:
                log.warning("self-ping failed: %s", str(e)[:100])
        await asyncio.sleep(540)


# ---------------------------------------------------------------- Web API мини-приложения
def verify_init_data(data: str):
    try:
        vals = dict(urllib.parse.parse_qsl(data, keep_blank_values=True))
        received = vals.pop("hash", "")
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(vals.items()))
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received):
            return None
        return vals
    except Exception:
        return None


def tg_user_from(vals):
    try:
        return json.loads(vals.get("user", "{}"))
    except json.JSONDecodeError:
        return {}


async def web_index(_request):
    page = (config.ROOT / "webapp" / "index.html").read_text(encoding="utf-8")
    page = page.replace("__BOT_USERNAME__", config.BOT_USERNAME or "bot")
    return web.Response(text=page, content_type="text/html", charset="utf-8")


async def api_me(request):
    vals = verify_init_data(request.query.get("initData", ""))
    if not vals:
        return web.json_response({"ok": False, "error": "Не удалось подтвердить Telegram"}, status=401)
    user = tg_user_from(vals)
    uid = user.get("id")
    if not uid:
        return web.json_response({"ok": False, "error": "Нет данных пользователя"}, status=401)
    db.ensure_user(uid, user.get("username", ""))
    row = db.get_user(uid)
    tier = db.effective_tier(row)
    expires = ""
    if tier != "free" and row is not None:
        expires = time.strftime("%d.%m.%Y", time.localtime(row["expires_at"]))
    return web.json_response({
        "ok": True, "tier": tier, "tier_label": TIERS[tier],
        "expires": expires, "gens_left": db.gens_left(uid, tier),
        "online": max(db.online_count(), 3),
        "username": user.get("username", ""),
        "pro_stars": config.PRO_STARS, "creator_stars": config.CREATOR_STARS,
    })


async def api_buy(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Некорректный запрос"}, status=400)
    vals = verify_init_data(data.get("initData", ""))
    if not vals:
        return web.json_response({"ok": False, "error": "Не удалось подтвердить Telegram"}, status=401)
    tier = data.get("tier")
    if tier not in ("pro", "creator"):
        return web.json_response({"ok": False, "error": "Неизвестный тариф"}, status=400)
    stars = config.PRO_STARS if tier == "pro" else config.CREATOR_STARS
    try:
        link = await bot.create_invoice_link(
            title=f"Подписка {TIERS[tier]} — 30 дней",
            description=f"{db.LIMITS[tier]} генераций в день, мощная модель.",
            payload=f"sub:{tier}",
            currency="XTR",
            prices=[LabeledPrice(label=TIERS[tier], amount=stars)],
        )
    except Exception as e:
        log.exception("create_invoice_link failed")
        return web.json_response({"ok": False, "error": "Не удалось создать счёт: " + str(e)[:120]}, status=500)
    return web.json_response({"ok": True, "link": link})


async def api_generate(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Некорректный запрос"}, status=400)
    vals = verify_init_data(data.get("initData", ""))
    if not vals:
        return web.json_response({"ok": False, "error": "Не удалось подтвердить Telegram"}, status=401)
    kind = data.get("kind")
    prompt = (data.get("prompt") or "").strip()
    if kind not in KINDS or len(prompt) < 5:
        return web.json_response({"ok": False, "error": "Опиши задачу чуть подробнее (минимум 5 символов)"}, status=400)
    user = tg_user_from(vals)
    uid = user.get("id")
    db.ensure_user(uid, user.get("username", ""))
    tier = user_tier(uid)
    if db.gens_left(uid, tier) <= 0:
        return web.json_response({"ok": False, "error":
            f"Лимит тарифа «{TIERS[tier]}» на сегодня исчерпан — улучши подписку ⭐"}, status=429)
    speed = "fast" if data.get("speed") == "fast" else "quality"
    try:
        raw = await generator.generate(tier, kind, prompt, speed)
        spec = packaging.extract_spec(raw)
        fname, archive = packaging.build(spec, kind)
        db.record_gen(uid)
    except Exception as e:
        log.exception("webapp generation failed")
        return web.json_response({"ok": False, "error": friendly_error(e)}, status=500)

    # сохраняем файл и публикуем в галерею
    fn = secrets.token_hex(6) + "_" + fname
    (config.ROOT / "files").mkdir(exist_ok=True)
    (config.ROOT / "files" / fn).write_bytes(archive)
    item_id = secrets.token_hex(5)
    db.add_gallery_item(item_id, str(spec.get("name", ""))[:60], kind, tier,
                        user.get("username", ""), fn)

    # и всегда отправляем копию в чат пользователю
    caption = (f"📦 <b>{html.escape(str(spec.get('name', '')))}</b>\n"
               f"{html.escape(str(spec.get('description', '')))}\n"
               f"📥 <b>Установка:</b>\n{html.escape(str(spec.get('install', '')))[:800]}")
    try:
        await bot.send_document(uid, document=BufferedInputFile(archive, filename=fname),
                                caption=caption[:1024])
        sent_to_chat = True
    except Exception as e:
        log.warning("chat delivery failed: %s", str(e)[:100])
        sent_to_chat = False

    return web.json_response({
        "ok": True, "name": spec.get("name", ""), "description": spec.get("description", ""),
        "install": spec.get("install", ""), "filename": fname,
        "url": f"/files/{fn}", "item_id": item_id, "sent_to_chat": sent_to_chat,
    })


async def api_top(request):
    vals = verify_init_data(request.query.get("initData", ""))
    if not vals:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    user = tg_user_from(vals)
    uid = user.get("id")
    items = []
    for r in db.top_gallery(20):
        items.append({
            "id": r["item_id"], "name": r["name"], "kind": KINDS.get(r["kind"], r["kind"]),
            "tier": r["tier"], "username": r["username"], "votes": r["votes"],
            "url": f"/files/{r['path']}",
        })
    return web.json_response({"ok": True, "items": items, "voted": db.has_voted(uid)})


async def api_vote(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    vals = verify_init_data(data.get("initData", ""))
    if not vals:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    uid = tg_user_from(vals).get("id")
    item_id = str(data.get("item_id", ""))[:16]
    counted = db.vote_item(uid, item_id)
    return web.json_response({"ok": True, "counted": counted})


# ---------------------------------------------------------------- запуск
async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("❌ Заполни BOT_TOKEN в .env — инструкция в ЧИТАЙ_МЕНЯ.txt")
    db.init()

    global bot
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    app = web.Application()
    app.router.add_get("/", web_index)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/top", api_top)
    app.router.add_post("/api/vote", api_vote)
    app.router.add_post("/api/buy", api_buy)
    app.router.add_post("/api/generate", api_generate)
    (config.ROOT / "files").mkdir(exist_ok=True)
    app.router.add_static("/files/", config.ROOT / "files")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.WEBAPP_PORT)
    await site.start()
    log.info("WebApp: http://localhost:%s | публичный URL: %s", config.WEBAPP_PORT, config.PUBLIC_URL or "не задан")
    asyncio.create_task(self_ping())

    if config.PUBLIC_URL and config.BOT_USERNAME:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="🎨 Студия", web_app=WebAppInfo(url=config.PUBLIC_URL)))
        except Exception as e:
            log.warning("Не удалось установить кнопку меню: %s", e)

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
