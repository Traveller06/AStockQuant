"""Create or verify an immutable release tag before uploading matching binaries."""

import json
import os
import re
import subprocess


def ensure_release_tag(repository: str, tag: str, commit: str, *, run=subprocess.run) -> None:
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected full tested commit SHA')
    endpoint = f'repos/{repository}/commits/{tag}'

    def invoke(*args):
        return run(['gh', 'api', *args], capture_output=True, text=True, check=False)

    result = invoke(endpoint)
    if result.returncode:
        if '(HTTP 404)' not in result.stderr:
            raise RuntimeError('Cannot verify release tag: ' + result.stderr)
        created = invoke('--method', 'POST', f'repos/{repository}/git/refs',
                         '-f', f'ref=refs/tags/{tag}', '-f', f'sha={commit}')
        if created.returncode:
            raise RuntimeError('Cannot create release tag: ' + created.stderr)
        result = invoke(endpoint)
        if result.returncode:
            raise RuntimeError('Cannot resolve created release tag: ' + result.stderr)
    if json.loads(result.stdout).get('sha') != commit:
        raise RuntimeError('Release tag points to a different commit; refusing publication')


if __name__ == '__main__':
    ensure_release_tag(os.environ['GITHUB_REPOSITORY'], os.environ['RELEASE_TAG'], os.environ['GITHUB_SHA'])
