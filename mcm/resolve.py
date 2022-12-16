from dataclasses import dataclass, field
from .utils import Field, Fields, Styles, Subfields, Syms
from .modpakyml import BuildType, ModConf, ModpakYml
from .infomanager import ModInfoManager
from .common import Source, SourceType, Loader, McVerMatch, VerMatch, Type
from .modinfo import ModInfo, ModVerPair, ModVerMatch
from rich.text import Text

__all__ = ('resolve', 'ResolveResult', 'ResolvedMod')

@dataclass(slots=True)
class ResolvedMod:
    mod: ModInfo
    ver: ModVerPair
    source: Source

    conf: ModConf|None = None
    dependents: list = field(default_factory = list)

    @property
    def name(self): return self.mod.name
    @property
    def type(self): return self.mod.type
    @property
    def dependent_names(self): return {d.name for d in self.dependents}
    @property
    def is_explicit(self): return self.conf is not None
    def has_dependents(self): return bool(self.dependents)

    def __and__(self, other):
        if other.__class__ is not ResolvedMod: return NotImplemented
        if self.mod is not other.mod: raise ValueError
        return ResolvedMod(self.mod, self.ver if self.ver.version >= other.ver.version else other.ver,
                           self.source, self.conf or other.conf, self.dependents + other.dependents)
        

    FIELDS = Fields(
        Field('Name', 'name', 'n', Styles.yellow_bold),
        Field('Explicit', 'is_explicit', 'explicit', 'e'),
        Field('Dependents', 'dependent_names', 'd'),
        Subfields(ModVerPair, 'ver', 'v.'))

class Warnings(dict):
    def add(self, mod: str, warning: str):
        if d := self.get(mod):
            d.append(warning)
        else:
            self[mod] = [warning]

    def __rich__(self):
        lines = []
        for mod, warnings in self.items():
            header = Syms.warn + Text.styled(f' {mod}: ', Styles.magenta_bold)
            for w in warnings:
                lines.append(header + Text.styled(w, Styles.yellow))
                header = Text(' ' * header.cell_len)
        return Syms.nl.join(lines)

@dataclass(slots=True)
class ResolveResult:
    downloaded: list[ResolvedMod]
    local: list[ModConf]
    warnings: Warnings

async def find_version(manager: ModInfoManager, name: str, type: Type, source: SourceType, mvm: ModVerMatch, *, warnings: Warnings):
    print(f"Finding version for {name}")
    info = await manager.get_modinfo(source, type, name)
    latest = info.get_latest_version(mvm)
    vers = sorted(info.get_versions(mvm), key=lambda x: x.published, reverse=True)
    if latest.published != vers[0].published:
        warnings.add(name, 'version {latest.version} is older than {vers[0].version}')
    pair = await manager.get_version_info(source, info, latest)
    return info, pair

async def resolve(manager: ModInfoManager, modpak: ModpakYml, build_type: BuildType|str):
    local = []
    resolved = {}
    deps = []
    warnings = Warnings()
    for mod in modpak.build_type_mods(build_type):
        if mod.source.islocal:
            local.append(mod)
            continue
        mvm = ModVerMatch(mod.version, modpak.loader if mod.type is Type.MOD else None,
                          mod.mcver, mod.fallback_mcver, mod.match)
        info, pair = await find_version(manager, mod.name, mod.type, mod.source.type, mvm, warnings=warnings)
        r = ResolvedMod(info, pair, mod.source.type, mod, [])
        resolved[mod.name] = r
        for dep in pair.dependencies:
            if dep.is_required:
                deps.append((dep.id, r))

    mcver = modpak.default_mcver_match
    mcver_fallback = modpak.default_mcver_fallback_match
    mvm = ModVerMatch(VerMatch.ANY, modpak.loader, mcver, mcver_fallback, None)
    while deps:
        name, dependent = deps.pop()
        if dep := resolved.get(name):
            dep.dependents.append(dependent)
            continue

        info, pair = await find_version(manager, name, Type.MOD, dependent.source, mvm, warnings=warnings)
        r = ResolvedMod(info, pair, dependent.source, None, [dependent])
        resolved[name] = r
        for dep in pair.dependencies:
            if dep.is_required:
                deps.append((dep.id, r))
    return ResolveResult(list(resolved.values()), local, warnings)









