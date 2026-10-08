# -*- coding: utf8 -*-

import datetime
import io
import urllib.error

import pytest

from models import s3
from models.s3 import S3Error, S3Object, sign

# The examples of the S3 documentation, with their expected signatures:
# https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html
ACCESS_KEY = 'AKIAIOSFODNN7EXAMPLE'
SECRET_KEY = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
NOW = datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc)


def signature(headers):
    return headers['Authorization'].rsplit('Signature=', 1)[1]


def test_sign_get_object():
    headers = sign(
        'GET', 'https://examplebucket.s3.amazonaws.com/test.txt',
        {'Range': 'bytes=0-9'}, b'',
        ACCESS_KEY, SECRET_KEY, 'us-east-1', NOW,
        )

    assert headers['Authorization'] == (
        'AWS4-HMAC-SHA256 '
        'Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, '
        'SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, '
        'Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41'
        )


def test_sign_put_object():
    headers = sign(
        'PUT', 'https://examplebucket.s3.amazonaws.com/test$file.text',
        {
            'Date': 'Fri, 24 May 2013 00:00:00 GMT',
            'x-amz-storage-class': 'REDUCED_REDUNDANCY',
        },
        b'Welcome to Amazon S3.',
        ACCESS_KEY, SECRET_KEY, 'us-east-1', NOW,
        )

    # Key with a character to encode ($)
    assert signature(headers) == (
        '98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd'
        )


def test_sign_keeps_the_given_headers():
    headers = sign(
        'PUT', 'https://examplebucket.s3.amazonaws.com/test.txt',
        {'Content-Type': 'application/json'}, b'{}',
        ACCESS_KEY, SECRET_KEY, 'us-east-1', NOW,
        )

    assert headers['Content-Type'] == 'application/json'
    assert headers['Host'] == 'examplebucket.s3.amazonaws.com'
    assert headers['x-amz-date'] == '20130524T000000Z'


ENV = {'AWS_ACCESS_KEY_ID': ACCESS_KEY, 'AWS_SECRET_ACCESS_KEY': SECRET_KEY}


def test_object_url_on_aws():
    s3 = S3Object('bucket', 'dpe/counters.json', {**ENV, 'AWS_REGION': 'eu-west-3'})

    assert s3.url == 'https://bucket.s3.eu-west-3.amazonaws.com/dpe/counters.json'
    assert s3.region == 'eu-west-3'


def test_object_url_on_another_storage():
    s3 = S3Object('bucket', 'counters.json', {
        **ENV,
        'AWS_ENDPOINT_URL': 'https://s3.gra.io.cloud.ovh.net/',
        'AWS_DEFAULT_REGION': 'gra',
    })

    # Path-style
    assert s3.url == 'https://s3.gra.io.cloud.ovh.net/bucket/counters.json'
    assert s3.region == 'gra'


def test_object_default_region():
    assert S3Object('bucket', 'key', ENV).region == 'us-east-1'


def test_object_needs_credentials():
    with pytest.raises(ValueError):
        S3Object('bucket', 'key', {})


def s3_error(status, code):
    """Make urlopen fail like S3 does, with this error code."""
    def urlopen(request, timeout):
        body = f'<Error><Code>{code}</Code><Message>Some details.</Message></Error>'.encode()
        raise urllib.error.HTTPError(request.full_url, status, 'Error', {}, io.BytesIO(body))
    return urlopen


def test_get_missing_object(monkeypatch):
    monkeypatch.setattr(s3.urllib.request, 'urlopen', s3_error(404, 'NoSuchKey'))

    # Not created yet: nothing to load
    assert S3Object('bucket', 'key', ENV).get() is None


def test_get_missing_bucket(monkeypatch):
    monkeypatch.setattr(s3.urllib.request, 'urlopen', s3_error(404, 'NoSuchBucket'))

    # A misconfiguration, not an empty state
    with pytest.raises(S3Error):
        S3Object('bucket', 'key', ENV).get()


def test_errors_tell_the_s3_reason(monkeypatch):
    monkeypatch.setattr(s3.urllib.request, 'urlopen', s3_error(403, 'InvalidAccessKeyId'))

    with pytest.raises(S3Error) as exc:
        S3Object('bucket', 'key', ENV).put(b'{}')

    assert str(exc.value) == 'HTTP 403 InvalidAccessKeyId: Some details.'
    assert exc.value.code == 'InvalidAccessKeyId'
