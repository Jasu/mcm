from .backend import *
from .common import *
from .modinfo import *
from .utils import print
from dataclasses import dataclass, field
from typing import Any, ClassVar
from time import time
from aiohttp import ClientSession
from asyncio import create_task
from urllib.parse import quote
from os import rename
from dateutil.parser import isoparse
import json
__all__ = ('Modrinth')

def parse_license(license: dict):
    match license['id']:
        case 'arr': return License.STD['Closed']
        case 'mpl-2': return License.STD['MPL']
        case 'mit': return License.STD['MIT']
        case 'isc': return License.STD['ISC']
        case 'bsd-2-clause'|'bsd-3-clause': return License.STD['BSD']
        case 'unlicense': return License.STD['Unlicense']
        case 'zlib': return License.STD['zlib']
        case 'apache': return License.STD['Apache']
        case 'lgpl-2.1'|'lgpl-3': return License.STD['LGPL']
        case 'cc0': return License.STD['CC0']
        case 'gpl-2'|'gpl-3': return License.STD['GPL']
        case 'custom': return License(LicenseType.CUSTOM, license['url'])
        case _: raise ValueError(f'Unknown license {license!r}')

def parse_project(type: Type, project: dict):
    return ModDesc(
        project['id'],
        type,
        project['slug'],
        project['title'],
        isoparse(project['updated']),
        isoparse(project['published']),
        parse_license(project['license']),
        project['description'],
        project['body'],
        SideSupport(project['client_side']),
        SideSupport(project['server_side']),
        project['issues_url'],
        project['source_url'],
        project['wiki_url'],
        project['discord_url'])

def parse_file(file: dict):
    return ModFile(file['filename'], file['size'],
                   Hash(HashType.SHA512, file['hashes']['sha512']),
                   file['url'])

def parse_version(version: dict):
    loaders = []
    for loader in version['loaders']:
        try:
            loaders.append(Loader(loader))
        except: pass
    return ModVer(
        version['id'],
        version['version_number'],
        VerType.deserialize(version['version_type']),
        None,
        frozenset(loaders),
        isoparse(version['date_published']),
        frozenset(map(McVer.deserialize, version['game_versions'])))

@dataclass(slots=True)
class Modrinth:
    session: ClientSession|None = field(default=None, init=False)
    active_requests: dict = field(default_factory=dict, init=False)
    USER_AGENT: ClassVar[str] = 'mcm/0.0.1'
    BASE_URL: ClassVar[str] = 'https://api.modrinth.com'
    MOD_BASE_URL: ClassVar[str] = 'https://modrinth.com/mod/'

    async def parse_dependency(self, dep: dict):
        if dep['project_id'] is None and dep['version_id'] is None: return None
        project_id = dep['project_id']
        if project_id is None:
            json = await self.get_json(f"version/{dep['version_id']}")
            project_id = json['project_id']
        json = await self.get_json(f"project/{project_id}")
        return Dep(dep['dependency_type'] == 'required', json['slug'], dep['version_id'])

    async def _get_json(self, path: str):
        async with self.session.get(path) as res:
            return await res.json()

    async def _get_file(self, url: str, to: str):
        async with ClientSession(headers={'User-Agent': Modrinth.USER_AGENT}) as session:
            async with session.get(url) as res:
                with open(to + '.part', 'wb') as f:
                    async for c, _ in res.content.iter_chunks():
                        f.write(c)
        rename(to + '.part', to)

    async def get_json(self, path: str, **kwargs):
        is_first = True
        for k, v in kwargs.items():
            match v:
                case None: continue
                case str(): v = quote(v)
                case int(): v = str(v)
                case frozenset()|set()|tuple(): v = quote(json.dumps(list(v)))
                case _: v = quote(json.dumps(v))
            path += '?' if is_first else '&'
            path += f'{k}={v}'
            is_first = False
        path = f'/v2/{path}'
        if not (task := self.active_requests.get(path)):
            task = create_task(self._get_json(path))
            self.active_requests[path] = task
        return await task

    async def get_categories(self, type: Type):
        categories = await self.get_json('tag/category')
        type = type.value
        return {c['name']: Category(c['name']) for c in categories if c['project_type'] == type}

    async def search(self, criteria: SearchCriteria) -> SearchResults:
        facets = [[f'project_type:{criteria.type.value}']]
        if criteria.loader: facets.append([f'categories:{criteria.loader.value}'])
        if criteria.categories is not None: facets.append([f'categories:{c}' for c in criteria.categories])
        if criteria.mcver: facets.append([f'versions:{v}' for v in criteria.mcver.versions])
        results = []
        offset = 0
        while True:
            limit = min(20, criteria.limit - offset)
            subresults = await self.get_json('search', query=criteria.query, facets=facets or None, limit=limit, offset=offset,
                                             index=criteria.sort.value)
            offset += 20
            for r in subresults['hits']:
                results.append(SearchResult(r['project_id'], r['slug'], r['downloads'], isoparse(r['date_modified']),
                                            r['title'],
                                            r['description'], Type(r['project_type']),
                                            Modrinth.MOD_BASE_URL + r['slug']))
            if min(criteria.limit, subresults['total_hits']) <= offset:
                return SearchResults(results, subresults['total_hits'])

    async def get_moddesc(self, type: Type, id_or_name: str) -> ModDesc:
        return parse_project(type, await self.get_json(f'project/{id_or_name}'))

    async def parse_version_info(self, version: dict, name: str):
        deps = []
        for dep in version['dependencies']:
            dep = await self.parse_dependency(dep)
            if dep is None:
                print(f'WARN: Version {version["id"]} for {name} had an invaild dependency')
                continue
            deps.append(dep)
        return ModVerInfo(parse_file(next(filter(lambda f: f['primary'], version['files']), version['files'][0])),
                          deps, version['changelog'])

    async def get_versions(self, desc: ModDesc):
        json = await self.get_json(f'project/{desc.id}/version')
        version_info = {}
        for item in json:
            version_info[item['id']] = await self.parse_version_info(item, desc.name)
        return list(map(parse_version, json)), version_info

    async def get_version_info(self, desc: ModDesc, ver: ModVer):
        raise ValueError('Version info not supported')

    async def get_file(self, to: str, ver_pair: ModVerPair):
        await self._get_file(ver_pair.file.url, to)

    async def __aenter__(self):
        if self.session: raise Exception('Modrinth already open')
        self.session = ClientSession(Modrinth.BASE_URL, headers={'User-Agent': Modrinth.USER_AGENT})
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_value:
            print('Exception when closing Modrinth', exc_value)
            print(traceback)
        if not self.session:
            if exc_value: return
            raise Exception('Modrinth already open')
        session = self.session
        self.session = None
        await session.close()

    @classmethod
    def project_url(cls, name_or_id: str): return f'{cls.BASE_URL}project/{name_or_id}'

    @classmethod
    def versions_url(cls, name_or_id: str): return f'{cls.BASE_URL}project/{name_or_id}/version'
    
