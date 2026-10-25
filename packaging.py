"""Разбор ответа модели и сборка готового архива (mcaddon/zip)."""
import io
import json
import re
import zipfile

KIND_EXT = {"addon": ".mcaddon", "datapack": ".zip", "plugin": ".zip", "mod": ".zip", "map": ".zip"}


def _try_load(t: str):
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # модели иногда вставляют «сырые» эскейпы — чиним и пробуем строже->мягче
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', t)
        return json.loads(fixed, strict=False)


def extract_spec(text: str) -> dict:
    t = (text or "").strip()
    fence = re.match(r"^\s*```[a-zA-Z]*\s*\n([\s\S]*?)\n?\s*```\s*$", t)
    if fence:
        t = fence.group(1).strip()
    obj = None
    try:
        obj = _try_load(t)
    except (json.JSONDecodeError, ValueError):
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = _try_load(t[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                obj = None
    if not isinstance(obj, dict) or not isinstance(obj.get("files"), dict) or not obj["files"]:
        raise ValueError("Модель вернула ответ не в нужном формате — нажми «Сгенерировать» ещё раз.")
    obj["files"] = {str(p): str(c) for p, c in obj["files"].items() if str(p).strip()}
    return obj


def build(spec: dict, kind: str):
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(spec.get("name") or "mcgen")).strip("_")[:40] or "mcgen"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in spec["files"].items():
            zf.writestr(path.replace("\\", "/").lstrip("/"), content)
    return name + KIND_EXT.get(kind, ".zip"), buf.getvalue()


def self_test():
    spec = {
        "name": "Test Pack",
        "description": "тест",
        "install": "-",
        "files": {
            "pack.mcmeta": '{"pack":{"pack_format":48,"description":"test"}}',
            "data/x/a.mcfunction": "say hi",
        },
    }
    fname, data = build(spec, "datapack")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert "data/x/a.mcfunction" in zf.namelist() and "pack.mcmeta" in zf.namelist()
    assert extract_spec('```json\n{"name":"A","files":{"f":"1"}}\n```')["files"]["f"] == "1"
    print(f"packaging self-test OK: {fname}, {len(data)} bytes")
