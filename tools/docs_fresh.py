#!/usr/bin/env python3
"""Check that the generated reports docs/xref.txt and docs/unknown.txt match the current sources.

Both are produced by tools that are not part of `disasm.py --build`, so they silently go stale after a rename or a
reclassification. This runs the tools into a temporary directory and compares (line endings ignored).
Exit code 1 and the fix command when a report is out of date.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

REPORTS = (('xref.py', 'docs/xref.txt'), ('unknown_report.py', 'docs/unknown.txt'))


def norm(path):
    with open(path, 'rb') as f:
        return f.read().replace(b'\r\n', b'\n')


def main():
    stale = []
    with tempfile.TemporaryDirectory() as tmp:
        for tool, report in REPORTS:
            out = os.path.join(tmp, os.path.basename(report))
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            r = subprocess.run([sys.executable, os.path.join(HERE, tool), '--out', out], cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if r.returncode:
                sys.exit('%s failed: %s' % (tool, r.stderr.decode('utf-8', 'replace')[-300:]))
            if norm(out) != norm(os.path.join(ROOT, report)):
                stale.append(report)
    if stale:
        print('docs: out of date: %s (run: make docs)' % ', '.join(stale))
        sys.exit(1)
    print('docs: xref.txt and unknown.txt are up to date')


if __name__ == '__main__':
    main()
