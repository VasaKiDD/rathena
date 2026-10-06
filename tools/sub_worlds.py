#!/usr/bin/env python3
"""Sub-worlds: closed regions of the Pre-renewal world.

A sub-world is a set of maps that players (not GMs) cannot leave: the portals at
its edge are disabled, and any other way out (a Kafra teleport, a boat, a wing, a
quest warp, an old save point) brings the player back. Agents launched in the same
sub-world share a hub town and a short list of hunting grounds, so they meet.

setup-macos.sh loads one with `start --sub-world NAME`. This tool writes the NPC
scripts it loads (npc/custom/sub_worlds/) and checks them against the scripts the
server loads.

  python3 tools/sub_worlds.py list              the worlds, one line each
  python3 tools/sub_worlds.py generate          write npc/custom/sub_worlds/
  python3 tools/sub_worlds.py check [NAME ...]  exits, reachability, level ladder,
                                                job quests and start cell of each world

Standard library only. Paths are relative to the rAthena root (the parent of tools/).
"""

import collections
import os
import re
import statistics
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join("npc", "custom", "sub_worlds")
SCRIPTS_MAIN = os.path.join("npc", "pre-re", "scripts_main.conf")
MAPS_CONF = os.path.join("conf", "maps_athena.conf")
MOB_DB = os.path.join("db", "pre-re", "mob_db.yml")
# The pre-re cache holds the maps that differ in Pre-renewal; the main one, the rest.
MAP_CACHES = [os.path.join("db", "pre-re", "map_cache.dat"), os.path.join("db", "map_cache.dat")]


def maps(prefix, first, last, skip=(), width=2):
	return [f"{prefix}{i:0{width}d}" for i in range(first, last + 1) if i not in skip]


class World:
	def __init__(self, name, title, start, maps, extra=()):
		self.name = name
		self.title = title
		self.start = start  # (map, x, y): new characters, and anyone with no way back
		self.maps = list(dict.fromkeys(maps))
		self.extra = list(extra)  # (NPC to copy, map, x, y, name of the copy): NPCs added to this world


WORLDS = {
	"prontera": World(
		"prontera",
		"Prontera and Izlude",
		("prontera", 156, 191),
		["prontera", "prt_in", "prt_church", "prt_castle", "izlude", "izlude_in"]
		+ maps("prt_fild", 0, 11)
		+ [f"prt_sewb{i}" for i in range(1, 5)]
		+ ["izlu2dun"]
		+ maps("iz_dun", 0, 4)
		+ maps("prt_maze", 1, 3)
		+ ["prt_monk", "monk_in", "monk_test"]
		# Job tests.
		+ ["job_sword1", "job_knt", "job_prist", "job_cru", "job_monk"],
		# The Acolyte pilgrimage picks one of three hermits; one lives near Morroc, outside
		# this world. A copy of her stands where the road to Morroc used to be.
		[("Ascetic#2aco", "prt_fild09", 246, 30, "Ascetic#sw2aco")],
	),
	"morroc": World(
		"morroc",
		"Morroc and the Sograt Desert",
		("morocc", 156, 46),
		# moc_fild01-03 and 13 connect to Morroc only through Prontera and Payon fields,
		# and moc_fild20 (the Dimensional Gorge) is left only by a guard's dialogue.
		["morocc", "morocc_in", "moc_ruins", "moc_fild07", "moc_fild11", "moc_fild12"]
		+ maps("moc_fild", 16, 19)
		+ ["cmd_fild08", "cmd_fild09", "anthell01", "anthell02"]
		+ maps("moc_pryd", 1, 6)
		+ ["moc_prydb1"]
		+ [f"in_sphinx{i}" for i in range(1, 6)]
		# Thief, Assassin and Rogue guilds and tests.
		+ ["job_thief1", "in_moc_16", "que_job01", "in_rogue"],
	),
	"geffen": World(
		"geffen",
		"Geffen and the Orc lands",
		("geffen", 119, 40),
		["geffen", "geffen_in", "gef_tower"]
		+ maps("gef_fild", 0, 14)
		+ maps("gef_dun", 0, 3)
		+ ["in_orcs01", "orcsdun01", "orcsdun02"]
		# Wizard test.
		+ ["job_wiz"],
	),
	"payon": World(
		"payon",
		"Payon and Alberta",
		("payon", 160, 58),
		["payon", "payon_in01", "payon_in02", "payon_in03", "pay_arche", "alberta", "alberta_in", "alb_ship"]
		+ maps("pay_fild", 1, 11, skip=(4,))
		+ maps("pay_dun", 0, 4)
		+ ["alb2trea", "treasure01", "treasure02"],
	),
	"aldebaran": World(
		"aldebaran",
		"Al De Baran, Mt. Mjolnir and Lutie",
		("aldebaran", 143, 109),
		["aldebaran", "aldeba_in", "alde_alche"]
		+ [f"mjolnir_{i:02d}" for i in range(1, 13)]
		+ maps("mjo_dun", 1, 3)
		+ [f"c_tower{i}" for i in range(1, 5)]
		+ maps("alde_dun", 1, 4)
		+ ["xmas", "xmas_in", "xmas_fild01", "xmas_dun01", "xmas_dun02"],
	),
}

# Not maps players stand on: floating NPCs, script functions, and the maps where
# scripts park hidden NPCs.
NEUTRAL_MAPS = {"-", "function", "sec_in02", "sec_pri"}


def path(*parts):
	return os.path.join(ROOT, *parts)


def read(rel):
	with open(path(rel), encoding="latin-1") as f:
		return f.read()


# ---------------------------------------------------------------- server data


def loaded_npc_files():
	"""Every NPC file the Pre-renewal map server loads, in order."""
	files, deleted = [], set()

	def walk(conf):
		for line in read(conf).split("\n"):
			line = line.strip()
			m = re.match(r"(npc|import|delnpc):\s*(\S+)", line)
			if not m or line.startswith("//"):
				continue
			kind, rel = m.groups()
			if kind == "import":
				if os.path.exists(path(rel)):
					walk(rel)
			elif kind == "npc":
				files.append(rel)
			else:
				deleted.add(rel)

	walk(SCRIPTS_MAIN)
	return [f for f in dict.fromkeys(files) if f not in deleted and os.path.exists(path(f))]


def all_maps():
	return re.findall(r"^map:\s*(\S+)", read(MAPS_CONF), re.M)


HEADER = re.compile(
	r"^([a-z0-9_@\-]+)(?:,(\d+),(\d+)(?:,\d+)?)?\t(script|duplicate\(([^)]*)\)|shop|cashshop|trader|warp2?)\t([^\t]*)\t?(.*)$",
	re.I,
)


class Npc:
	def __init__(self, file, map, x, y, kind, name, rest, template):
		self.file, self.map, self.x, self.y = file, map, x, y
		self.kind, self.name, self.rest, self.template = kind, name, rest, template
		self.body = ""

	@property
	def unique(self):
		"""The name disablenpc and duplicate() use: the part after '::', or the whole name."""
		return self.name.split("::", 1)[1] if "::" in self.name else self.name


def parse_npcs(files):
	npcs = []
	for rel in files:
		lines = read(rel).split("\n")
		i = 0
		while i < len(lines):
			line = lines[i]
			m = HEADER.match(line)
			if m:
				mp, x, y, kind, template, name, rest = m.groups()
				npc = Npc(rel, mp, int(x or 0), int(y or 0), kind.split("(")[0].lower(), name, rest, template)
				if npc.kind == "script" and "{" in line:
					depth, j, body = line.count("{") - line.count("}"), i + 1, []
					while depth > 0 and j < len(lines):
						code = re.sub(r'"[^"]*"', '""', re.sub(r"//.*", "", lines[j]))
						depth += code.count("{") - code.count("}")
						body.append(lines[j])
						j += 1
					npc.body = "\n".join(body)
					i = j - 1
				npcs.append(npc)
			i += 1
	return npcs


def edges(npcs):
	"""(source map, destination map) -> list of (how, NPC unique name, NPC) for every way to travel."""
	known_maps = set(all_maps())
	by_name = {}
	for n in npcs:
		by_name.setdefault(n.unique, n)
		by_name.setdefault(n.name, n)
	out = collections.defaultdict(list)
	for n in npcs:
		if n.map in NEUTRAL_MAPS:
			continue
		if n.kind.startswith("warp"):
			a = n.rest.split(",")
			if len(a) >= 3:
				out[(n.map, a[2].strip())].append(("warp", n.unique, n))
			continue
		body = n.body
		if n.kind == "duplicate" and n.template in by_name:
			body = by_name[n.template].body
		dests = re.findall(r'\bwarp\s+"([a-z0-9_@\-]+)"', body)
		# Gates written as functions take the destination as an argument, e.g.
		# callfunc "F_ClockTowerGate","4th",7026,"c_tower4",185,44;
		for args in re.findall(r'\bcallfunc\s+"[^"]+"\s*,([^;]*);', body):
			dests += [a for a in re.findall(r'"([a-z0-9_@\-]+)"', args) if a in known_maps]
		for dest in dests:
			out[(n.map, dest)].append(("npc", n.unique, n))
	return out


def mob_db():
	mobs, cur = {}, None
	for line in read(MOB_DB).split("\n"):
		m = re.match(r"\s+- Id: (\d+)", line)
		if m:
			cur = mobs[int(m.group(1))] = {}
			continue
		m = re.match(r"\s+(Name|Level|BaseExp|MvpExp):\s*(.+)", line)
		if cur is not None and m and m.group(1) not in cur:
			cur[m.group(1)] = m.group(2).strip()
	return mobs


def spawns(files, mobs):
	"""map -> Counter(mob id -> amount) of the ordinary spawns (no MVPs, no long respawns)."""
	out = collections.defaultdict(collections.Counter)
	for rel in files:
		if "/mobs/" not in rel:
			continue
		for line in read(rel).split("\n"):
			p = line.split("\t")
			if line.startswith("//") or len(p) < 4 or p[1].strip() not in ("monster", "boss_monster"):
				continue
			a = p[3].split(",")
			try:
				mid, amount, delay = int(a[0]), int(a[1]), int(a[2]) if len(a) > 2 else 0
			except ValueError:
				continue
			if "MvpExp" in mobs.get(mid, {}) or delay >= 600000:
				continue
			out[p[0].split(",")[0]][mid] += amount
	return out


class MapCache:
	"""Walkability from db/(pre-re/)map_cache.dat (cell types 1 and 5 are not walkable)."""

	def __init__(self):
		self.maps = {}
		for rel in reversed(MAP_CACHES):  # later files override earlier ones
			data = open(path(rel), "rb").read()
			count = struct.unpack_from("<H", data, 4)[0]
			off = 8
			for _ in range(count):
				name, xs, ys, size = struct.unpack_from("<12shhi", data, off)
				off += 20
				self.maps[name.split(b"\0")[0].decode()] = (xs, ys, data[off : off + size])
				off += size

	def walkable(self, mp, x, y):
		if mp not in self.maps:
			return False
		xs, ys, blob = self.maps[mp]
		if not (0 <= x < xs and 0 <= y < ys):
			return False
		if isinstance(blob, bytes) and len(blob) != xs * ys:
			blob = zlib.decompress(blob)
			self.maps[mp] = (xs, ys, blob)
		return blob[x + y * xs] not in (1, 5)

	def nearest_walkable(self, mp, x, y, radius=12):
		for r in range(radius + 1):
			for dy in range(-r, r + 1):
				for dx in range(-r, r + 1):
					if max(abs(dx), abs(dy)) == r and self.walkable(mp, x + dx, y + dy):
						return x + dx, y + dy
		raise SystemExit(f"error: no walkable cell within {radius} of {mp},{x},{y}")


# ---------------------------------------------------------------- generation


def boundary_warps(world, graph):
	inside = set(world.maps)
	names = set()
	for (src, dst), ways in graph.items():
		if src in inside and dst not in inside:
			names.update(name for how, name, _ in ways if how == "warp")
	return sorted(names)


def world_script(world, graph, cache):
	start_map, start_x, start_y = world.start
	if not cache.walkable(start_map, start_x, start_y):
		raise SystemExit(f"error: the start cell {start_map},{start_x},{start_y} of {world.name} is not walkable")
	quoted = [f'"{m}"' for m in world.maps]
	rows = [", ".join(quoted[i : i + 6]) for i in range(0, len(quoted), 6)]
	maps_lines = ",\n\t\t".join(rows)
	disable = "\n".join(f'\tdisablenpc "{name}";' for name in boundary_warps(world, graph))
	# Copies are made at OnInit: this file loads before the scripts that define the originals.
	extra = []
	for original, mp, x, y, copy in world.extra:
		x, y = cache.nearest_walkable(mp, x, y)
		extra.append(f'\tduplicate "{original}", "{mp}", {x}, {y}, "{copy}";')
	extra_block = ("\t// Added to this world.\n" + "\n".join(extra) + "\n") if extra else ""
	return f"""//===== rAthena Script =======================================
//= Sub-world: {world.title}
//===== Description: =========================================
//= Players cannot leave these {len(world.maps)} maps. The portals at the edge
//= are disabled. Any other way out (a Kafra teleport, a boat, a wing, a quest
//= warp, an old save point) brings them back to where they last arrived in
//= this world, or to the start. A save point outside moves to the start.
//= GMs (group 99) travel freely.
//=
//= Loaded with loadevent.txt by: setup-macos.sh start --sub-world {world.name}
//= Generated by tools/sub_worlds.py: edit the tool, not this file.
//===== Settings read by setup-macos.sh: =====================
//= start_point: {start_map},{start_x},{start_y}
//============================================================

-	script	SubWorld#{world.name}	-1,{{
OnInit:
	setarray .maps$[0],
		{maps_lines};
	.start$ = "{start_map}";
	.start_x = {start_x};
	.start_y = {start_y};
	// The portals at the edge of the world.
{disable}
{extra_block}	end;

OnPCLoadMapEvent:
	if (getgroupid() >= 99)
		end;
	getmapxy(.@map$, .@x, .@y);
	if (inarray(.maps$[0], .@map$) >= 0) {{
		@sub_world_map$ = .@map$;
		@sub_world_x = .@x;
		@sub_world_y = .@y;
		if (inarray(.maps$[0], getsavepoint(0)) < 0)
			savepoint .start$, .start_x, .start_y;
		end;
	}}
	dispbottom "The way beyond is closed. You are taken back.";
	if (@sub_world_map$ == "")
		warp .start$, .start_x, .start_y;
	else
		warp @sub_world_map$, @sub_world_x, @sub_world_y;
	end;
}}
"""


def loadevent_script():
	lines = "\n".join(f"{m}\tmapflag\tloadevent" for m in all_maps())
	return f"""//===== rAthena Script =======================================
//= Sub-worlds: the loadevent mapflag on every map
//===== Description: =========================================
//= Lets the loaded sub-world script see every map change
//= (OnPCLoadMapEvent). Loaded together with one world file.
//= Generated by tools/sub_worlds.py from conf/maps_athena.conf.
//============================================================

{lines}
"""


def write(rel, text):
	full = path(rel)
	os.makedirs(os.path.dirname(full), exist_ok=True)
	with open(full, "w", encoding="latin-1", newline="\n") as f:
		f.write(text)
	print(f"wrote {rel}")


def cmd_generate():
	npcs = parse_npcs(loaded_npc_files())
	graph, cache = edges(npcs), MapCache()
	known = set(all_maps())
	for world in WORLDS.values():
		missing = [m for m in world.maps if m not in known]
		if missing:
			raise SystemExit(f"error: {world.name}: not in {MAPS_CONF}: {', '.join(missing)}")
		write(os.path.join(OUT_DIR, f"{world.name}.txt"), world_script(world, graph, cache))
		write(os.path.join(OUT_DIR, f"{world.name}.maps"), "\n".join(world.maps) + "\n")
	write(os.path.join(OUT_DIR, "loadevent.txt"), loadevent_script())


# ---------------------------------------------------------------- checks


def reachable(world, graph):
	inside = set(world.maps)
	nxt = collections.defaultdict(set)
	for (src, dst) in graph:
		if src in inside and dst in inside:
			nxt[src].add(dst)
	seen, todo = {world.start[0]}, [world.start[0]]
	while todo:
		for dst in nxt[todo.pop()]:
			if dst not in seen:
				seen.add(dst)
				todo.append(dst)
	return seen


def cmd_check(names):
	files = loaded_npc_files()
	npcs = parse_npcs(files)
	graph, cache, mobs = edges(npcs), MapCache(), mob_db()
	spawn = spawns(files, mobs)
	known = set(all_maps())
	problems = 0
	for name in names or list(WORLDS):
		world = WORLDS[name]
		inside = set(world.maps)
		print(f"===== {world.name}: {world.title} ({len(world.maps)} maps, start {','.join(map(str, world.start))})")
		missing = [m for m in world.maps if m not in known]
		if missing:
			problems += 1
			print(f"  ERROR not in {MAPS_CONF}: {', '.join(missing)}")
		if not cache.walkable(*world.start):
			problems += 1
			print("  ERROR the start cell is not walkable")
		for original, mp, x, y, copy in world.extra:
			print(f"  added NPC: {copy} (a copy of {original}) on {mp} at {cache.nearest_walkable(mp, x, y)}")

		unreached = sorted(inside - reachable(world, graph))
		print(f"  unreachable from the start without leaving: {', '.join(unreached) or 'none'}")

		warps, bounced = [], collections.defaultdict(set)
		for (src, dst), ways in sorted(graph.items()):
			if src not in inside or dst in inside:
				continue
			for how, unique, _ in ways:
				if how == "warp":
					warps.append(f"{src}->{dst}")
				else:
					bounced[dst].add(f"{src}:{unique}")
		print(f"  disabled edge portals ({len(boundary_warps(world, graph))} warps): {', '.join(sorted(set(warps)))}")
		print(f"  scripted exits, bounced back ({sum(len(v) for v in bounced.values())}):")
		for dst in sorted(bounced):
			print(f"    -> {dst}: {', '.join(sorted(bounced[dst]))}")

		print("  level ladder (median level of the ordinary spawns; top monsters):")
		ladder = []
		for mp in world.maps:
			c = spawn.get(mp)
			if not c:
				continue
			levels = sorted(int(mobs[i]["Level"]) for i, n in c.items() for _ in range(n) if mobs[i].get("BaseExp", "0") != "0")
			if not levels:
				continue
			top = ", ".join(f"{mobs[i]['Name']} {mobs[i]['Level']}" for i, _ in c.most_common(3))
			ladder.append((statistics.median(levels), mp, top))
		for med, mp, top in sorted(ladder):
			print(f"    {med:>5.1f}  {mp:<12} {top}")

		jobs = collections.defaultdict(set)
		for n in npcs:
			kind = "job" if "/jobs/" in n.file else "skill" if "/skills/" in n.file else None
			if kind and n.map not in NEUTRAL_MAPS and not re.search(r"2-[12]a/|valkyrie", n.file):
				jobs[(kind, os.path.basename(n.file)[:-4])].add(n.map)
		for kind in ("job", "skill"):
			full = sorted(q for (k, q), m in jobs.items() if k == kind and m <= inside)
			part = sorted(f"{q} (also {', '.join(sorted(m - inside))})" for (k, q), m in jobs.items() if k == kind and m & inside and not m <= inside)
			print(f"  {kind} quests inside: {', '.join(full) or 'none'}")
			if part:
				print(f"  {kind} quests partly outside: {'; '.join(part)}")
		print()
	if problems:
		raise SystemExit(f"{problems} problem(s)")


def cmd_list():
	for world in WORLDS.values():
		print(f"{world.name:<10} {world.title} ({len(world.maps)} maps, start {','.join(map(str, world.start))})")


def main(argv):
	os.chdir(ROOT)
	cmd = argv[1] if len(argv) > 1 else "check"
	if cmd == "list":
		cmd_list()
	elif cmd == "generate":
		cmd_generate()
	elif cmd == "check":
		unknown = [n for n in argv[2:] if n not in WORLDS]
		if unknown:
			raise SystemExit(f"error: unknown world {', '.join(unknown)}; worlds: {', '.join(WORLDS)}")
		cmd_check(argv[2:])
	else:
		raise SystemExit(__doc__)


if __name__ == "__main__":
	main(sys.argv)