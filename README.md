# Minecraft modpack package manager

Manage minecraft packages via [Modrinth](https://modrinth.com/) API and
automated downloads from a certain Minecraft modding site.

## Example

Example of `modpak.yml` for building a mod pack:

```yml
mc: 1.19.2

target_dirs:
  # Datapack and resource pack output locations can be customized,
  # to support automatic datapack/resourcepack loaders like Paxi.
  datapacks: config/paxi/datapacks
  resourcepacks: config/paxi/resourcepacks

# Different builds can be specified.
# E.g. server-side builds don't need (and don't work with) client
# side mods, and only admins need server utility mods etc.
build_types:
  client: { side: client }
  admin:  { side: client }
  server: { side: server }
  # Single-player build
  combo:  { side: both }

# Root of mods
mods:
  # Mods can be separated into named categories
  - name: Tech and Magic
    mods:
      # You know what to replace the stars with - this might stay
      # longer on GitHub if it's not Google-optimized.
      - name: *****forge/spirit
      - name: *****forge/ars-nouveau
        # Configuration can be overridden - there are commands that copy the
        # default config from a newly-built server/client/single-player instance,'
        # and only changes/deletions/additions need to be listed.
        common_conf:
          ars_nouveau-common.toml:
            general.spawnBook: false
      # By default uses Modrinth - for modrinth mods, client/server-sidedness
      # need not be specified (but can be overridden)
      - create

  - name: Implementation
    # Categories can have descriptions, though they are only comments at this point
    desc: Non-gameplay modules for configuration etc.
      - name: curseforge/jaopca
        desc: Merges different ores ores 
        # If only a glob pattern is specified, configuration is copied rather than edited
        common_conf:
         - jaopca/custom_forms.json
         - jaopca/*/*.toml
         - jaopca/modules/storage_blocks.toml:
             general.materialBlacklist: ['*']
         - jaopca/main.toml:
             materialLocalization.checkL10nUpdates: false
             # concat here is an operator which appends the values to the list in the toml file.
             itemSelection.preferredMods: { concat: ['create', 'immersiveengineering'] }
      # Mods can also be copied from local disk
      - name: purkka
        source: ~/purkka/build/libs/purkka-1.0.jar
        # For local mods, sides must be specified
        side: both
```

## Features

  - Check for mod updates
  - Resolves mod dependencies and downloads them (naively - no SAT solvers here)
  - Custom distributions, e.g. the distribution for server admins can have a
    distribution with CrashUtils and single-player instances do not need Connectivity.
  - Commands to build packages for client, server, and single player.
  - Command to search for mods on Modrinth
  - Commands and related configuration to install the built distributions to a
    local Minecraft instance
  - Generates a lock file, though it is currently always updated. Versions can
    be specified in modpak.yml though.

## Implementation

  - Async communivation with Modrinth API (using `aiohttp`)
  - WebDriver control of Firefox for downloading mods from `*****Forge`
  - Dependencies are resolved iteratively - mods generally have few dedependencies,
    so cross-dependency problems requiring SAT solver are not present.
  - Configuration patching by specifying path and an edit - comments and
    formatting are mostly preserved (including custom diff renderer):
  - Caches mods locally, so it only downloads a version once
  - Checksum checks for downloaded mods
