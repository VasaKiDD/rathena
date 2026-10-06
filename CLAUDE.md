# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

rAthena: a C++ Ragnarok Online server emulator (login, char, map, and web servers, backed by MySQL/MariaDB). This checkout is a fork (`origin` = `VasaKiDD/rathena`, `upstream` = `rathena/rathena`) and is the server half of the `TronProject` workspace. See `../CLAUDE.md` for how it connects to the roBrowserLegacy and OpenKore clients, and for the PACKETVER rule shared across all three.

## Build and run

```bash
./configure [--enable-packetver=YYYYMMDD] [--enable-prere=yes] [--enable-vip=yes]
make clean && make server        # login, char, map, web; or one of: make login|char|map|web
make tools                       # mapcache, csv2yaml, yaml2sql, yamlupgrade, map-server-generator
make import                      # fills conf/import, conf/msg_conf/import, db/import from *-tmpl (never overwrites)
./athena-start start|stop|restart
```

CMake (`CMakeLists.txt`) and Visual Studio (`rAthena.sln`) builds also exist.

**Local server on macOS:** `./setup-macos.sh` does everything. It installs MariaDB and PCRE with Homebrew, creates and imports the `ragnarok` database, builds Renewal, writes a managed block into `conf/import/*.txt`, and starts the four servers on 127.0.0.1. Subcommands: `deps`, `db`, `build`, `config`, `start`, `stop`, `restart`, `status`, `logs <server>`, `check` (`map-server --run-once`), `reset-db`, `sub-world` (the configured world), and `sub-worlds` (the list). Env vars such as `PACKETVER`, `BIND_IP` and `GM_USER` override the defaults. Build logs go to `build/macos/`. PACKETVER and `MODE` (`renewal` or `prere`) both stick: if they're not set, the script reuses the values from `build/macos/configure.args`, falling back to `20130618` and `renewal`. 20130618 matches the public roBrowser assets that `../play-ro.command` uses. Each mode has its own database, `ragnarok` or `ragnarok_prere`: `start` creates it on first use and points `conf/import/inter_conf.txt` at it. The Pre-renewal `start_point_pre` is set to `prontera,156,191`, because the public assets lack the `new_1-1` to `new_5-1` novice grounds. `../switch_to_2025_protocol.md` covers moving to 20250618.

**Sub-worlds:** `--sub-world NAME` (`all`, `config`, `start`, `restart`, `check`) adds `npc/custom/sub_worlds/loadevent.txt` and `NAME.txt` to the managed block of `conf/import/map_conf.txt`, and sets `start_point_pre` from the world file's `//= start_point:` line. That world's script disables the edge warps and bounces players (not group 99) who land outside it. Without the option, the world is `full`. Sub-worlds are Pre-renewal only. The files are generated: edit `WORLDS` in `tools/sub_worlds.py`, then run `python3 tools/sub_worlds.py generate` and `check`, then `./setup-macos.sh check --sub-world NAME`. `../sub_worlds.md` describes the worlds.

There is no unit test suite. To check a change:
- **Compile it.** CI builds with `CXXFLAGS='-Werror ...'` on gcc and clang, so warnings count as failures.
- **Load the data.** `./map-server --run-once` loads every db file and NPC script, then exits. CI uses this (`npc_db_validation.yml`) after appending `npc/custom` and `npc/test` to `npc/scripts_custom.conf` via `tools/ci/npc.sh`. It needs a database: `tools/ci/sql.sh` shows the import order from `sql-files/`.
- **Mind the build variants.** CI builds pre-renewal and renewal, several PACKETVERs, and VIP builds. Guard code with the right `#ifdef RENEWAL`, `#if PACKETVER >= ...`, or `PACKETVER_MAIN_NUM`/`PACKETVER_RE_NUM`/`PACKETVER_ZERO_NUM` checks.

## Layout

- `src/common/`: shared core (sockets, timers, `ers`, SQL wrapper, YAML `TypesafeYamlDatabase` base in `database.hpp`, `showmsg`).
- `src/login`, `src/char`, `src/web`: the other servers. Inter-server traffic goes map ↔ char (`chrif.cpp`, `intif.cpp`) and char ↔ login. Packet layouts are in `doc/packet_interserv.txt`.
- `src/map/`: nearly all game logic. The central files are `clif.cpp` (client packets; structs in `packets.hpp`, `packets_struct.hpp`, `clif_packetdb.hpp`; see `doc/packet_client.txt`), `battle.cpp` (damage), `skill.cpp`, `status.cpp` (status changes, stat calc), `pc.cpp`, `mob.cpp`, `script.cpp` (NPC script engine), and `atcommand.cpp`.
- `src/config/`: compile-time toggles. `renewal.hpp` defines `RENEWAL` and its sub-flags unless `PRERE` is set. `packets.hpp` holds the default `PACKETVER`. `core.hpp` has general flags, `secure.hpp` security options, and `classes/` class-specific settings.
- `src/custom/`: hook points for server-specific code without touching core files: `defines_pre/post.hpp`, `atcommand*.inc`, `script*.inc`, `battle_config_*.inc`.
- `db/`: YAML game data. Shared files sit at the top level and mode-specific ones in `db/re/` and `db/pre-re/`. Each YAML file has a `Header: Type/Version`. A version bump needs matching handling in `src/tool/yamlupgrade.cpp`/`csv2yaml.cpp`.
- `conf/`: runtime config (`conf/battle/*.conf` for battle_config values).
- `npc/`: NPC scripts, loaded through `npc/scripts_*.conf`. `npc/re/` and `npc/pre-re/` hold the mode-specific ones.
- `doc/`: reference docs. The most useful are `script_commands.txt`, `atcommands.txt`, `item_bonus.txt`, `status_change.txt`, `packet_client.txt`, and `yaml/` (db field docs).

## Skill implementation system (`src/map/skills/`)

Skill behavior is moving out of the giant `switch` statements in `skill.cpp` and `battle.cpp` into one class per skill:

- `skill_impl.hpp` defines `SkillImpl`, with virtual hooks that replace those switches: `castendDamageId`, `castendNoDamageId`, `castendPos2`, `calculateSkillRatio`, `modifyHitRate`, `applyAdditionalEffects`, `applyCounterAdditionalEffects`, `modifyDamageData`, and `modifyElement`. Reusable bases: `StatusSkillImpl` (just applies the skill's status), `WeaponSkillImpl`, and `SkillImplRecursiveDamageSplash`.
- Skills are grouped by job-line directory (`acolyte/`, `merchant/`, `custom/`, ...). Each skill has a `<name>.hpp`/`<name>.cpp` pair, and the class is conventionally named `Skill<Name>`.
- Each directory has a `skill_factory_<job>.cpp`. It maps `e_skill` IDs to impls in a `switch`, and it **`#include`s every skill `.cpp` in that directory** (a unity build). Individual skill `.cpp` files are never compiled on their own. `skill_factory.cpp` tries the job factories in order, with `SkillFactoryCustom` first so it can override stock skills.
- `skill.cpp` calls `skill->impl->...` when an impl exists and otherwise falls back to the legacy switch code.
- **Adding a skill file:**
  1. Create the `.hpp`/`.cpp` pair.
  2. Add `#include "<name>.cpp"` and a `case` to the job's factory.
  3. Add the files to `src/map/map-server.vcxproj` and `.vcxproj.filters` for MSBuild.

  Make and CMake pick up the factory TUs by glob, so they need no changes.
- `MAP_GENERATOR` builds (`map-server-generator`) compile the factory with no concrete impls.

Typical upstream balance commits touch `db/re/skill_db.yml`, `db/re/status.yml`, the skill's impl file, and sometimes `script_constants.hpp` or `db/status_disabled.txt`. `git show --stat` on a recent "6th rebalance" commit shows the pattern.

## Conventions

- **Local overrides go in `conf/import/` and `db/import/`**, not in base files (`conf/readme.md`).
- `.editorconfig` sets tabs for C++, Makefiles, and `npc/**.txt`, 4 spaces for YAML, and a final newline.
- New script commands go in `script.cpp` (`BUILDIN_FUNC` plus a `BUILDIN_DEF` entry) and are documented in `doc/script_commands.txt`. New constants exposed to scripts go in `script_constants.hpp`. New atcommands go in `atcommand.cpp` and are documented in `doc/atcommands.txt`. New battle_config options go in `battle.cpp`/`battle.hpp` plus a `conf/battle/*.conf` entry.
- Upstream PRs follow `.github/PULL_REQUEST_TEMPLATE.md`. Behavior changes should be sourced from official kRO behavior, not iRO Wiki (`.github/CONTRIBUTING.md`).
