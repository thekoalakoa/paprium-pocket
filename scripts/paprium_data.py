"""Locate the two game-derived inputs the analysis tools need.

NEITHER IS IN THIS REPOSITORY and neither may be committed. Point these at your
own copies:

    PAPRIUM_ROM         the Mega Drive ROM
    PAPRIUM_ANIM_BLOB   ROM 0x0C0000 decompressed - the animation table, 241
                        objects. Produced by unpacking the type-0x80 container at
                        0x0C0000; see docs/PORT_PLAN.md.

Everything here is a script that reads them, which is the line this project draws:
tools go in the repo, game data does not.
"""
import os

ENV_ROM = 'PAPRIUM_ROM'
ENV_BLOB = 'PAPRIUM_ANIM_BLOB'


def _resolve(env, what, hint):
    p = os.environ.get(env)
    if not p:
        raise SystemExit(
            "%s is not set.\n"
            "  It must point at %s.\n"
            "  %s" % (env, what, hint))
    if not os.path.exists(p):
        raise SystemExit("%s=%s does not exist" % (env, p))
    return p


def rom_path():
    return _resolve(ENV_ROM, 'the Paprium Mega Drive ROM',
                    'e.g. export PAPRIUM_ROM=/path/to/Paprium.md')


def anim_blob_path():
    return _resolve(ENV_BLOB, 'ROM 0x0C0000 decompressed (the animation table)',
                    'the unpacker writes it as c010000_0001_00_0C0000_80.bin')


def rom():
    return open(rom_path(), 'rb').read()


def anim_blob():
    return open(anim_blob_path(), 'rb').read()
