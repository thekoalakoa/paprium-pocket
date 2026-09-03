#!/usr/bin/env python3
"""Stand-in for `zip -r`, for machines without Info-ZIP.

    python scripts/_zip_fallback.py <out.zip> <dir-or-file> [...]

Run from the directory the archive paths should be relative to, exactly as the
`zip -r` call in package_release.sh does. Skips `.gitkeep` so the empty-directory
markers do not ship, while still creating the directories that hold them - which
is what `-x '*/.gitkeep'` did.

Exists because Git for Windows ships no `zip`, and a release should not depend on
which shell the maintainer happens to have.
"""
import os
import sys
import zipfile

def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    out, roots = sys.argv[1], sys.argv[2:]
    n = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for root in roots:
            if os.path.isfile(root):
                z.write(root, root.replace(os.sep, '/'))
                n += 1
                continue
            for dirpath, _dirnames, filenames in os.walk(root):
                keep = [f for f in filenames if f != '.gitkeep']
                if not keep:
                    # preserve the directory itself, as zip -r does
                    z.writestr(dirpath.replace(os.sep, '/').rstrip('/') + '/', '')
                for f in keep:
                    p = os.path.join(dirpath, f)
                    z.write(p, p.replace(os.sep, '/'))
                    n += 1
    print("%s: %d files" % (out, n), file=sys.stderr)

if __name__ == '__main__':
    main()
