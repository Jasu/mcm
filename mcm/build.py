from .infomanager import ModInfoManager
from .common import Type
from .utils import ensure_empty_dir
from .modpakyml import TargetDirs, ModpakYml, BuildType, ModConf
from .modconfs import ModConfType
from .resolve import ResolveResult
from shutil import copyfile
from glob import iglob
from zipfile import ZipFile
import os.path

async def build(manager: ModInfoManager, modpak: ModpakYml, build_type: BuildType|str,
          resolutions: ResolveResult, source_dir: str, target_dir: str):
    build_type = modpak.get_build_type(build_type)
    target_dir = os.path.join(target_dir, build_type.name)
    target_dirs = modpak.get_target_dirs(target_dir)

    ensure_empty_dir(target_dirs.config, recursive=True)
    if build_type.has_server:
        ensure_empty_dir(target_dirs.defaultconfig, recursive=True)
    ensure_empty_dir(target_dirs.get_dir(Type.MOD), delglob='*.jar', recursive=False)
    ensure_empty_dir(target_dirs.get_dir(Type.SHADERPACK), recursive=False)
    ensure_empty_dir(target_dirs.get_dir(Type.DATAPACK), delglob='*.zip', recursive=False)
    ensure_empty_dir(target_dirs.get_dir(Type.RESOURCEPACK), delglob='*.zip', recursive=False)

    def apply_config(entry: ModConf):
        nonlocal source_dir, target_dirs, build_type
        if entry.common_conf:
            entry.common_conf.apply(ModConfType.COMMON, source_dir, target_dirs)
        if entry.client_conf and build_type.has_client:
            entry.client_conf.apply(ModConfType.CLIENT, source_dir, target_dirs)
        if entry.server_conf and build_type.has_server:
            entry.server_conf.apply(ModConfType.SERVER, source_dir, target_dirs)

    for local in resolutions.local:
        to = os.path.join(target_dirs.get_dir(local.type), os.path.basename(local.source.path))
        if local.type in (Type.RESOURCEPACK, Type.DATAPACK) and os.path.isdir(local.source.path):
            with ZipFile(to + '.zip', 'w') as f:
                for path in iglob('**', root_dir=local.source.path, recursive=True):
                    f.write(os.path.join(local.source.path, path), arcname=path)
        else:
            copyfile(os.path.expanduser(local.source.path), to)
        apply_config(local)

    for resolved in resolutions.downloaded:
        to = os.path.join(target_dirs.get_dir(resolved.type), resolved.ver.filename)
        await manager.copy_file(to, resolved.source, resolved.mod, resolved.ver)
        if resolved.is_explicit: apply_config(resolved.conf)


async def check(modpak: ModpakYml, build_type: BuildType|str,
          resolutions: ResolveResult, source_dir: str, target_dir: str):
    build_type = modpak.get_build_type(build_type)
    target_dir = os.path.join(target_dir, build_type.name)
    target_dirs = modpak.get_target_dirs(target_dir)
    errors = []
    for resolved in resolutions.downloaded:
        to = os.path.join(target_dirs.get_dir(resolved.type), resolved.ver.filename)
        h = resolved.ver.file.hash
        with open(to, 'rb') as f: b = f.read()
        v = h.hash(b)
        if v != h.value:
            errors.append(f'File {resolved.ver.filename} of {resolved.mod.name} is invalid.')
    return errors





