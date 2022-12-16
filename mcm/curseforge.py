from .browser import Browser
from dataclasses import dataclass, field
from datetime import datetime
from .common import *
from .modinfo import *
from typing import ClassVar
import asyncio

LICENSE_MATCHERS = {
  'All Rights':    License.STD['Closed'],
  'Public Domain': License.STD['PD'],
  'Apache':        License.STD['Apache'],
  'Creative':      License.STD['CC'],
  'Mozilla':       License.STD['MPL'],
  'MIT':           License.STD['MIT'],
  'BSD':           License.STD['BSD'],
  'ISC':           License.STD['ISC'],
  'zlib':          License.STD['zlib'],
  'GNU Affero':    License.STD['AGPL'],
  'GNU Lesser':    License.STD['LGPL'],
  'GNU General':   License.STD['GPL'],
}
def parse_license(val: str, href: str|None):
    for k,v in LICENSE_MATCHERS.items():
        if val.startswith(k): return v
    return License(LicenseType.CUSTOM, href)

@dataclass(slots=True)
class CurseForge:
    browser: Browser
    privacy_checked: bool
    BASE_URL: ClassVar[str] = 'https://www.curseforge.com/'

    def modpath(self, type: Type, name: str, path: str = ''):
        if path: path = '/' + path.lstrip('/')
        match type:
            case Type.MOD: return f'minecraft/mc-mods/{name}{path}'
            case Type.RESOURCEPACK|Type.DATAPACK: return f'minecraft/texture-packs/{name}{path}'
            case Type.SHADERPACK: return f'minecraft/customization/{name}{path}'
            case _: raise TypeError(type)

    async def navigate(self, path: str):
        self.browser.navigate(path)
        while self.browser.title.startswith('Attention'):
            await asyncio.sleep(0.5)
        if not self.privacy_checked:
            consent_frame = (await self.browser.maybe_wait("iframe[title='SP Consent Message']", timeout=10000)).maybe_one()
            if consent_frame:
                self.browser.select_frame(consent_frame)
                (await self.browser.wait("button[title=Accept]")).one().click()
                self.browser.select_frame(None)
                await asyncio.sleep(1.5)
            self.privacy_checked = True
    def get_tabhref(self, name):
        a = self.browser.find(f'nav > ul > li[id^="nav-{name}"] > a').maybe_one();
        return None if not a else a.href

    async def get_moddesc(self, type: Type, name: str) -> ModDesc:
        await self.navigate(self.modpath(type, name))
        sidebar = await self.browser.wait('aside.w-full div.flex-col.mb-3 > div.w-full.flex.justify-between')
        header = await self.browser.wait('header div.flex > div.flex-col.flex')

        license = None
        created = None
        updated = None
        for row in sidebar:
            title = row.children()[0]
            if title.text == 'License':
                a = row.find('a').one()
                license = parse_license(a.text, a.href)
            elif title.text == 'Created':
                created = datetime.fromtimestamp(int(row.find('abbr').one().attr('data-epoch')))
            elif title.text == 'Updated':
                updated = datetime.fromtimestamp(int(row.find('abbr').one().attr('data-epoch')))
        return ModDesc(name, type, name, header.find('h2').one().text,
            updated, created, license,
            self.browser.meta('twitter:description'),
            None, None, None,
            self.get_tabhref('issues'), self.get_tabhref('source'), self.get_tabhref('wiki'))

    async def get_versions(self, desc: ModDesc):
        await self.navigate(self.modpath(desc.type, desc.name))
        files_path = self.modpath(desc.type, desc.name, 'files')
        file_link = await self.browser.wait(f"a[href='/{files_path}']")
        file_link.one().click()
        await asyncio.sleep(1.819)
        file_link = await self.browser.wait(f"a.button[href='/{files_path}/all']")
        file_link.one().click()
        await asyncio.sleep(1.12)
        rows = self.browser.find('table.listing-project-file tbody > tr')
        versions = []
        for row in rows:
            file_link = row.find("td:nth-child(2) a[data-action='file-link']").one()
            link_text = file_link.text
            loaders = []
            for loader in Loader:
                if loader.value in link_text.lower():
                    loaders.append(loader)
            mcver = McVer.deserialize(row.find('td:nth-child(5) div.mr-2').one().text)
            versions.append(
                ModVer(
                    file_link.raw_href,
                    file_link.text,
                    VerType.deserialize(row.find('td:first-child span').one().text),
                    link_text,
                    frozenset(loaders),
                    datetime.fromtimestamp(int(row.find('td:nth-child(4) abbr').one().attr('data-epoch'))),
                    frozenset({mcver})))
        return versions, None

    async def get_version_info(self, desc: ModDesc, ver: ModVer):
        await self.navigate(ver.id)
        cols = await self.browser.wait('article.box.p-4.flex-col > div.flex-col.justify-between > div.flex-row.mr-2.justify-between > span.text-sm:nth-child(2)')
        filename = cols[0].text.replace(' ', '+')
        md5 = cols[-1].text
        deps = []
        sections = self.browser.find('section.flex-col > section.flex-col > section.flex-col.items-start')
        for section in sections:
            match section.find('h4').one().text:
                case 'Optional Dependency': is_required = False
                case 'Required Dependency': is_required = True
                case s:
                    print(f'Unknown header {s}')
                    continue
            for dep in section.find('div.project-avatar > a'):
                modname = dep.raw_href.replace('/minecraft/mc-mods/', '')
                deps.append(Dep(is_required, modname))
        return ModVerInfo(ModFile(filename, None, Hash(HashType.MD5, md5), None), deps)

    async def get_file(self, to: str, ver_pair: ModVerPair):
        await self.navigate(ver_pair.id)
        (await self.browser.wait('section > article a.button--hollow[data-tooltip="Download file"]')).one().click()
        await self.browser.wait_download(ver_pair.filename, to, ver_pair.file.hash.check_file)

    def __init__(self):
        self.browser = Browser(CurseForge.BASE_URL)
        self.privacy_checked = False

    async def __aenter__(self):
        self.browser.__enter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.browser.__exit__(exc_type, exc_value, traceback)
