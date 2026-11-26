#!/usr/bin/env python3
"""Resolve an exact GitHub release tag without treating API errors as absence.

This read-only helper prints a full commit SHA, or nothing when the exact tag
reference returns HTTP 404. Every other failure stops publication. It is a CI
tool and is not included in the game package.
"""
import json
from http.client import HTTPException
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_ROOT = 'https://api.github.com'
MAX_BODY = 1024 * 1024
MAX_TAG_DEPTH = 16
FULL_SHA = re.compile(r'[0-9a-fA-F]{40}')
REPOSITORY = re.compile(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+')


class ReleaseRefError(Exception):
    """A tag lookup did not establish a trustworthy publication target."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # Do not forward the bearer token to a redirected endpoint.
        return None


def _sha(value):
    if not isinstance(value, str) or FULL_SHA.fullmatch(value) is None:
        raise ReleaseRefError('GitHub returned an invalid full commit/object SHA')
    return value.lower()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON member')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Invalid JSON constant')


def _get_json(url, token, opener, allow_missing=False):
    request = Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'Authorization': 'Bearer ' + token,
        'User-Agent': 'TankSession-Release-Ref',
        'X-GitHub-Api-Version': '2026-03-10',
    }, method='GET')
    try:
        with opener(request, timeout=20) as response:
            status = response.getcode()
            if type(status) is not int:
                raise ReleaseRefError('Invalid GitHub HTTP status')
            if status == 404 and allow_missing:
                return None
            if status != 200:
                raise ReleaseRefError('Unexpected GitHub HTTP status')
            raw = response.read(MAX_BODY + 1)
    except HTTPError as error:
        status = error.code
        error.close()
        if type(status) is not int:
            raise ReleaseRefError('Invalid GitHub HTTP error status') from None
        if status == 404 and allow_missing:
            return None
        # Never echo response bodies, request headers or exception strings.
        raise ReleaseRefError('GitHub HTTP error %s' % status) from None
    except (URLError, OSError, HTTPException):
        raise ReleaseRefError('GitHub network or response-read error') from None
    if len(raw) > MAX_BODY:
        raise ReleaseRefError('GitHub JSON response is too large')
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                            parse_constant=_invalid_constant)
    except (UnicodeError, ValueError):
        raise ReleaseRefError('Malformed GitHub JSON response') from None
    if not isinstance(result, dict):
        raise ReleaseRefError('GitHub response must be one JSON object')
    return result


def _target(body):
    target = body.get('object')
    if not isinstance(target, dict) or target.get('type') not in ('commit', 'tag'):
        raise ReleaseRefError('Tag target is not a commit or annotated tag')
    return target['type'], _sha(target.get('sha'))


def resolve_tag_commit(repository, tag, token, opener=None):
    """Return a verified commit SHA, or None only for an absent exact tag ref.

    ``opener`` follows urllib's ``open(request, timeout=...)`` interface so tests
    can exercise HTTP status and transport failures without external requests.
    Response-provided URLs are never followed.
    """
    if (not isinstance(repository, str) or REPOSITORY.fullmatch(repository) is None
            or repository.rsplit('/', 1)[-1] in ('.', '..')):
        raise ReleaseRefError('A valid GITHUB_REPOSITORY is required')
    if (not isinstance(tag, str) or not tag or len(tag) > 1024
            or any(ord(char) < 33 or ord(char) == 127 for char in tag)):
        raise ReleaseRefError('A valid RELEASE_TAG is required')
    if (not isinstance(token, str) or not token
            or any(ord(char) < 33 or ord(char) > 126 for char in token)):
        raise ReleaseRefError('GH_TOKEN is required and must be valid')
    if opener is None:
        opener = build_opener(_NoRedirect()).open
    base = API_ROOT + '/repos/' + repository
    ref = _get_json(base + '/git/ref/tags/' + quote(tag, safe=''), token, opener,
                    allow_missing=True)
    if ref is None:
        return None
    if ref.get('ref') != 'refs/tags/' + tag:
        raise ReleaseRefError('GitHub returned a different tag reference')
    kind, sha = _target(ref)
    seen = set()
    while kind == 'tag':
        if sha in seen or len(seen) >= MAX_TAG_DEPTH:
            raise ReleaseRefError('Annotated tag cycle or excessive depth')
        seen.add(sha)
        annotation = _get_json(base + '/git/tags/' + sha, token, opener)
        if _sha(annotation.get('sha')) != sha:
            raise ReleaseRefError('Annotated tag object SHA does not match')
        kind, sha = _target(annotation)
    commit = _get_json(base + '/git/commits/' + sha, token, opener)
    if _sha(commit.get('sha')) != sha:
        raise ReleaseRefError('Resolved commit SHA does not match')
    return sha


def main():
    try:
        commit = resolve_tag_commit(os.environ.get('GITHUB_REPOSITORY'),
                                    os.environ.get('RELEASE_TAG'),
                                    os.environ.get('GH_TOKEN'))
    except ReleaseRefError as error:
        print('Release tag lookup failed: ' + str(error), file=sys.stderr)
        return 1
    except Exception:
        # An unexpected transport/library exception may include private headers.
        print('Release tag lookup failed: unexpected lookup error', file=sys.stderr)
        return 1
    if commit is not None:
        print(commit)
    return 0


if __name__ == '__main__':
    sys.exit(main())
