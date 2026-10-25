"""Запрос к ИИ через OpenRouter (OpenAI-совместимый API, бесплатные модели)."""
import httpx

import config
import prompts

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Запасные бесплатные модели: если основная тарифа перегружена/молчит,
# пробуем их по очереди — пользователь просто дольше ждёт, а не ловит ошибку.
FALLBACKS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "dots-studio/dots-3-note-preview:free",
    "nvidia/nemotron-3.5-lightning:free",
]


class NoKeyError(RuntimeError):
    pass


class AllModelsFailedError(RuntimeError):
    pass


async def _call(model: str, tier: str, kind: str, user_prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompts.build_system(kind, tier)},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.6,
        "max_tokens": config.MAX_TOKENS[tier],
        # у многих бесплатных моделей включены «размышления» — без этого
        # лимит токенов уходит в reasoning, а сам ответ не рождается
        "reasoning": {"exclude": True},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(config.LLM_TIMEOUT)) as client:
        resp = await client.post(API_URL, headers=headers, json=payload)
    if resp.status_code == 401:
        raise RuntimeError("КЛЮЧ_НЕВЕРНЫЙ (401): проверь OPENROUTER_API_KEY в .env")
    if resp.status_code in (402, 429):
        raise RuntimeError(f"ЛИМИТ_МОДЕЛИ {model}: " + resp.text[:150])
    if resp.status_code == 404:
        raise RuntimeError(f"МОДЕЛЬ_УДАЛЕНА {model}: модели на OpenRouter периодически "
                           "меняются — цепочка фолбэков попробует следующую")
    if resp.status_code != 200:
        raise RuntimeError(f"ОШИБКА_ПРОВАЙДЕРА {model}: HTTP {resp.status_code} " + resp.text[:120])
    data = resp.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
    if not content or not content.strip():
        raise RuntimeError(f"ПУСТОЙ_ОТВЕТ {model}")
    return content


async def generate(tier: str, kind: str, user_prompt: str) -> str:
    if not config.OPENROUTER_API_KEY:
        raise NoKeyError()
    chain = [config.MODELS[tier]] + [m for m in FALLBACKS if m != config.MODELS[tier]]
    errors = []
    for model in chain:
        try:
            return await _call(model, tier, kind, user_prompt)
        except NoKeyError:
            raise
        except RuntimeError as e:
            text = str(e)
            if "КЛЮЧ_НЕВЕРНЫЙ" in text:
                raise
            errors.append(text[:120])
        except Exception as e:  # сетевые сбои и прочее — тоже идём к следующей модели
            errors.append(f"{model}: {str(e)[:100]}")
    raise AllModelsFailedError(
        "Все модели сейчас недоступны (лимиты/перегрузка). Попробуй через 10-15 минут. "
        "Детали: " + " | ".join(errors[:3])
    )
