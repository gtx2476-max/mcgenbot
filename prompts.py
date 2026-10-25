"""Экспертные системные промпты — «натаскивание» модели на форматы Minecraft."""
import json

CONTRACT = """
OUTPUT CONTRACT (mandatory):
Reply with ONE valid JSON object only. No markdown fences, no comments, no text outside JSON:
{"name": "short-ascii-name<=40", "description": "короткое описание на русском <=200 символов",
 "install": "инструкция по установке на русском, 2-4 строки",
 "files": {"relative/path/file.ext": "full file content as a plain string"}}
Rules:
- Max 15 files. Every file must be complete and valid, never truncated.
- Where the format requires UUIDs, invent random UUIDv4 strings.
- Properly escape newlines and quotes inside JSON strings.
- Contents of "description" and "install" must be in Russian.
"""

QUALITY = {
    "free": "QUALITY LEVEL: BASIC. Keep it compact but guaranteed-working: one entity/item/feature, "
            "simple robust logic, only well-known stable components. Aim for correctness over ambition.",
    "pro": "QUALITY LEVEL: ADVANCED. Rich gameplay logic: component groups with events "
           "(minecraft:entity_spawned, minecraft:entity_hurt, minecraft:on_target_acquired), animations, "
           "custom crafting recipes and loot tables, a couple of interacting entities, balanced stats.",
    "creator": "QUALITY LEVEL: MAXIMUM. Build a polished mini-content-pack: 3-5 entities/items that form a "
               "gameplay loop, custom recipes, loot tables, spawn rules, RP animations and particles, "
               "and (for Bedrock) a behavior script scripts/main.js using @minecraft/server APIs "
               "(world.afterEvents, system.runInterval) with the script module declared in the manifest. "
               "Everything must tie together into one coherent theme.",
}

BEDROCK_SPEC = """
TARGET: Minecraft Bedrock addon (.mcaddon). Structure (both packs at zip root):
behavior_packs/bp_<name>/manifest.json, ...entities/*.json, optional scripts/main.js, recipes/*.json, loot_tables/*.json, spawn_rules/*.json
resource_packs/rp_<name>/manifest.json, entity/*.entity.json (client entities), optional texts/en_US.lang
Behavior manifest (format_version 2): header{name,description,uuid,version[1,0,0],min_engine_version[1,20,0]},
modules[{type:"data",uuid,version[1,0,0]}], dependencies[{uuid:"<RP header uuid>",version[1,0,0]}].
If you add scripts, also add module {type:"script",language:"javascript",entry:"scripts/main.js",uuid,version} and a
dependency {"module_name":"@minecraft/server","version":"1.9.0-beta"}.
Resource manifest similar, modules[{type:"resources",...}].
BP entity format_version "1.16.0": minecraft:entity{description{identifier:"<ns>:<name>",is_spawnable,is_summonable},
components{...}}. Use only stable well-known components: minecraft:type_family, health, movement, attack,
collision_box, navigation.walk, movement.basic, jump.static, physics, pushable, loot, minecraft:behavior.random_stroll,
behavior.look_at_player, behavior.random_look_around, behavior.nearest_attackable_target,
behavior.hurt_by_target, behavior.melee_box_attack, behavior.panic, behavior.float. Component groups +
"minecraft:entity_spawned"/"minecraft:entity_hurt" events to switch groups are welcome.
RP client entity (format_version "1.10.0"): description{identifier, materials{default:"entity_alphatest"},
textures{default:"textures/entity/<vanilla-path>"}, geometry{default:"geometry.<vanilla_geo>"},
animations + scripts{scale, animate[]} optional, spawn_egg{base_color:"#hex",overlay_color:"#hex"}}.
CRITICAL: do NOT invent custom geometry or custom texture files (no image generation possible).
Reuse VANILLA geometry and textures (e.g. geometry.zombie + textures/entity/zombie/zombie,
geometry.iron_golem + textures/entity/iron_golem, geometry.husk, geometry.pig, geometry.blaze...) so the addon
looks correct in-game immediately.
Namespace: use the addon name transliterated to latin, lowercase, no spaces (e.g. "magirocks").
"""

DATAPACK_SPEC = """
TARGET: Minecraft Java datapack (.zip). Structure: pack.mcmeta at root, data/<namespace>/function/*.mcfunction,
data/<namespace>/recipe or advancement or loot_table as needed, data/minecraft/tags/function/tick.json to run tick logic.
pack.mcmeta: {"pack":{"pack_format":48,"description":"<name>"}} (48 = MC 1.21.x).
Commands: only stable vanilla commands (summon, give, setblock, fill, execute if/unless, scoreboard, tellraw, loot, particle, playsound, title).
No experimental features. Namespace = ascii slug of the name.
"""

PLUGIN_SPEC = """
TARGET: Spigot/Paper server plugin (Java). Structure:
plugin.yml {name, version:"1.0.0", main:"<pkg>.Main", api-version:"1.20", commands: {...}}
src/main/java/<pkg path>/Main.java and other classes (must compile with Spigot API 1.20+):
correct package declarations, imports (org.bukkit.*, org.bukkit.event.*, org.bukkit.plugin.java.JavaPlugin),
onEnable/onDisable, Listener classes with @EventHandler, schedulers via Bukkit.getScheduler().
pom.xml with spigot-repo (https://hub.spigotmc.org/nexus/content/repositories/snapshots) and
spigot-api 1.20.4-R0.1-SNAPSHOT provided scope.
Also include BUILD.txt telling the user to run "mvn package" and copy the jar from target/.
"""

MOD_SPEC = """
TARGET: Fabric mod for Minecraft Java 1.21. Structure:
src/main/resources/fabric.mod.json {schemaVersion:1, id, version:"1.0.0", name, entrypoints{main:["<pkg>.MainMod"]},
depends{fabricloader:">=0.15", minecraft:"~1.21", java:">=21"}}
src/main/java/<pkg path>/MainMod.java implementing ModInitializer; register items with
Registry.register(Registries.ITEM, Identifier.of("<modid>","<name>"), new Item(new Item.Settings()));
item models under assets/<modid>/models/item/*.json and textures must reference EXISTING vanilla textures
(e.g. layer0: "minecraft:item/amethyst_shard") — do NOT invent png files.
Also include BUILD.txt pointing to https://fabricmc.net/develop/template/ for the gradle template.
"""

MAP_SPEC = """
TARGET: playable Minecraft Java map delivered as a datapack that BUILDS the map in any world.
Structure: pack.mcmeta, data/<ns>/function/build.mcfunction (the main builder: terrain with fill layers,
plateau/valley shapes, water/lava, paths, structures with setblock, lighting), plus start.mcfunction
(welcome via tellraw + title) and optionally themed mobs via summon.
Constraints: total <= 2500 command lines, all coordinates relative to a documented origin (assume builder
runs at the world spawn), build area roughly within a 200x200 region. Make it look intentional and pretty:
symmetry, materials palette variation, depth (slabs/stairs via block states), hidden details.
The "install" field must explain: drop the zip into world datapacks folder, then run /function <ns>:build.
"""


SPECS = {
    "addon": BEDROCK_SPEC,
    "datapack": DATAPACK_SPEC,
    "plugin": PLUGIN_SPEC,
    "mod": MOD_SPEC,
    "map": MAP_SPEC,
}


def build_system(kind: str, tier: str) -> str:
    return (
        "You are a senior Minecraft content engineer with deep knowledge of Bedrock addon formats, "
        "Java datapacks, Spigot plugins, Fabric mods and vanilla mechanics.\n"
        + SPECS[kind]
        + QUALITY[tier]
        + CONTRACT
    )
