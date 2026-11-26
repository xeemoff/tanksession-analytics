import contextlib
from http.client import IncompleteRead
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import release_ref


REPO = 'owner/repository'
TAG = 'v1.0.0-rc2'
TOKEN = 'test-token-never-print'
SHA = 'a' * 40
OTHER_SHA = 'b' * 40
TAG_SHA = 'c' * 40
BASE = 'https://api.github.com/repos/' + REPO
REF_URL = BASE + '/git/ref/tags/' + TAG


class Response(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode('utf-8'))
        self.status = status

    def getcode(self):
        return self.status


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError('Unexpected extra HTTP request')
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def ref(sha=SHA, kind='commit', name=TAG):
    return {'ref': 'refs/tags/' + name, 'object': {'type': kind, 'sha': sha}}


def http_error(status):
    # Realistic gh error JSON must never leak onto stdout as a supposed SHA.
    return HTTPError(REF_URL, status, 'error ' + TOKEN, {},
                     io.BytesIO(b'{"message":"Not Found","status":"404"}'))


class ReleaseRefTests(unittest.TestCase):
    def resolve(self, *responses, tag=TAG):
        opener = FakeOpener(*responses)
        result = release_ref.resolve_tag_commit(REPO, tag, TOKEN, opener=opener)
        self.assertFalse(opener.responses, 'All expected requests must be made')
        return result, opener

    def test_exact_404_with_error_json_means_absent_and_stops_reading(self):
        result, opener = self.resolve(http_error(404))
        self.assertIsNone(result)
        self.assertEqual([r.full_url for r, _ in opener.requests], [REF_URL])

    def test_lightweight_ref_is_resolved_and_sha_verified(self):
        result, opener = self.resolve(Response(ref()), Response({'sha': SHA}))
        self.assertEqual(result, SHA)
        self.assertEqual([r.full_url for r, _ in opener.requests],
                         [REF_URL, BASE + '/git/commits/' + SHA])
        for request, timeout in opener.requests:
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('Authorization'), 'Bearer ' + TOKEN)
            self.assertEqual(timeout, 20)

    def test_existing_other_commit_is_returned_for_immutable_tag_guard(self):
        result, _ = self.resolve(Response(ref(OTHER_SHA)), Response({'sha': OTHER_SHA}))
        self.assertEqual(result, OTHER_SHA)
        self.assertNotEqual(result, SHA)

    def test_annotated_tag_is_dereferenced_using_immutable_object_sha(self):
        result, opener = self.resolve(
            Response(ref(TAG_SHA, 'tag')),
            Response({'sha': TAG_SHA, 'object': {'type': 'commit', 'sha': SHA},
                      'url': 'https://not-github.invalid/private'}),
            Response({'sha': SHA}))
        self.assertEqual(result, SHA)
        self.assertEqual([r.full_url for r, _ in opener.requests],
                         [REF_URL, BASE + '/git/tags/' + TAG_SHA,
                          BASE + '/git/commits/' + SHA])

    def test_nested_annotated_tags_are_resolved(self):
        result, _ = self.resolve(
            Response(ref(TAG_SHA, 'tag')),
            Response({'sha': TAG_SHA, 'object': {'type': 'tag', 'sha': OTHER_SHA}}),
            Response({'sha': OTHER_SHA, 'object': {'type': 'commit', 'sha': SHA}}),
            Response({'sha': SHA}))
        self.assertEqual(result, SHA)

    def test_tag_name_is_one_encoded_path_and_exact_name_is_checked(self):
        tag = 'release/v1.0.0'
        result, opener = self.resolve(Response(ref(name=tag)), Response({'sha': SHA}), tag=tag)
        self.assertEqual(result, SHA)
        self.assertEqual(opener.requests[0][0].full_url,
                         BASE + '/git/ref/tags/release%2Fv1.0.0')
        for body in (ref(name=TAG + '-different'), {'ref': 'refs/heads/' + TAG,
                                                  'object': {'type': 'commit', 'sha': SHA}}):
            with self.subTest(body=body), self.assertRaisesRegex(release_ref.ReleaseRefError,
                                                                'different tag reference'):
                self.resolve(Response(body))

    def test_http_and_transport_errors_never_mean_absent(self):
        for error in (http_error(401), http_error(403), http_error(409), http_error(429),
                      http_error(500), http_error(302), URLError(TOKEN), TimeoutError(TOKEN),
                      IncompleteRead(TOKEN.encode('ascii'))):
            with self.subTest(error=type(error).__name__), self.assertRaises(release_ref.ReleaseRefError) as caught:
                self.resolve(error)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_404_after_existing_ref_is_an_error_not_absence(self):
        for responses in (
            (Response(ref()), http_error(404)),
            (Response(ref(TAG_SHA, 'tag')), http_error(404)),
        ):
            with self.subTest(), self.assertRaisesRegex(release_ref.ReleaseRefError, 'HTTP error 404'):
                self.resolve(*responses)

    def test_success_status_with_error_body_or_malformed_json_is_rejected(self):
        for body in (b'not json', b'\xff', b'[]', b'null', b'{}',
                     b'{"message":"Not Found","status":"404"}',
                     b'{"ref":NaN}', b'{"ref":"first","ref":"second"}'):
            with self.subTest(body=body), self.assertRaises(release_ref.ReleaseRefError):
                self.resolve(Response(body))

    def test_response_http_status_must_be_exact_and_typed(self):
        result, _ = self.resolve(Response(b'{"message":"Not Found"}', status=404))
        self.assertIsNone(result)
        for status in ('200', 404.0, True, None, 201, 302, 500):
            with self.subTest(status=status), self.assertRaises(release_ref.ReleaseRefError):
                self.resolve(Response(ref(), status=status))

    def test_oversized_response_stops_resolution(self):
        with mock.patch.object(release_ref, 'MAX_BODY', 32):
            with self.assertRaisesRegex(release_ref.ReleaseRefError, 'too large'):
                self.resolve(Response(ref()))

    def test_only_full_sha_and_known_git_types_are_accepted(self):
        for sha in (None, 7, True, 'a' * 39, 'a' * 41, 'g' * 40, SHA + '\n', 'short'):
            with self.subTest(sha=sha), self.assertRaisesRegex(release_ref.ReleaseRefError, 'full commit/object SHA'):
                self.resolve(Response(ref(sha)))
        for kind in ('blob', 'tree', None):
            with self.subTest(kind=kind), self.assertRaisesRegex(release_ref.ReleaseRefError, 'Tag target'):
                self.resolve(Response(ref(kind=kind)))

    def test_mismatched_and_malformed_resolved_objects_fail_closed(self):
        for responses in (
            (Response(ref()), Response({'sha': OTHER_SHA})),
            (Response(ref()), Response({'sha': 'short'})),
            (Response(ref(TAG_SHA, 'tag')),
             Response({'sha': OTHER_SHA, 'object': {'type': 'commit', 'sha': SHA}})),
        ):
            with self.subTest(), self.assertRaises(release_ref.ReleaseRefError):
                self.resolve(*responses)

    def test_tag_cycles_and_excessive_depth_stop_before_extra_requests(self):
        with self.assertRaisesRegex(release_ref.ReleaseRefError, 'cycle'):
            self.resolve(Response(ref(TAG_SHA, 'tag')),
                         Response({'sha': TAG_SHA, 'object': {'type': 'tag', 'sha': TAG_SHA}}))
        with mock.patch.object(release_ref, 'MAX_TAG_DEPTH', 1):
            with self.assertRaisesRegex(release_ref.ReleaseRefError, 'depth'):
                self.resolve(Response(ref(TAG_SHA, 'tag')),
                             Response({'sha': TAG_SHA, 'object': {'type': 'tag', 'sha': OTHER_SHA}}))

    def test_redirect_handler_refuses_to_forward_credentials(self):
        self.assertIsNone(release_ref._NoRedirect().redirect_request(
            None, None, 302, 'redirect', {}, 'https://not-github.invalid/'))

    def test_cli_stdout_is_empty_or_only_sha_and_errors_cannot_print_token(self):
        environment = {'GITHUB_REPOSITORY': REPO, 'RELEASE_TAG': TAG, 'GH_TOKEN': TOKEN}
        cases = (
            ([http_error(404)], 0, ''),
            ([Response(ref()), Response({'sha': SHA})], 0, SHA + '\n'),
            ([http_error(500)], 1, ''),
            ([RuntimeError(TOKEN)], 1, ''),
        )
        for responses, expected_code, expected_stdout in cases:
            opener = FakeOpener(*responses)
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(code=expected_code), mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(release_ref, 'build_opener') as factory, \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                factory.return_value.open = opener
                self.assertEqual(release_ref.main(), expected_code)
            self.assertEqual(stdout.getvalue(), expected_stdout)
            self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())
            if expected_code:
                self.assertIn('Release tag lookup failed:', stderr.getvalue())

    def test_missing_or_invalid_configuration_stops_before_network(self):
        for repository, tag, token in (
            (None, TAG, TOKEN), ('owner/../repo', TAG, TOKEN),
            (REPO, '', TOKEN), (REPO, TAG + '\n', TOKEN),
            (REPO, TAG, None), (REPO, TAG, TOKEN + '\n'),
        ):
            opener = FakeOpener()
            with self.subTest(), self.assertRaises(release_ref.ReleaseRefError):
                release_ref.resolve_tag_commit(repository, tag, token, opener=opener)
            self.assertEqual(opener.requests, [])


if __name__ == '__main__':
    unittest.main()
