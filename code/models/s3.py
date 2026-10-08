# -*- coding: utf8 -*-

import datetime
import hashlib
import hmac
import os
import re
import urllib.error
import urllib.parse
import urllib.request

# A minimal S3 client, standard library only: the persistence only needs to
# read and write one object, and boto3 would add ~35MB to the image.
# Requests are signed with AWS Signature Version 4:
# https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-authenticating-requests.html

TIMEOUT = 30


def _hmac(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def sign(method, url, headers, payload, access_key, secret_key, region, now):
    """
    Headers to send for this request: the given ones, plus the signed ones.

    Every header given is signed, Host included (it must be sent as is).
    """
    parts = urllib.parse.urlsplit(url)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    day = now.strftime('%Y%m%d')

    headers = dict(headers)
    headers['Host'] = parts.netloc
    headers['x-amz-date'] = amz_date
    headers['x-amz-content-sha256'] = hashlib.sha256(payload).hexdigest()

    # Header names lowercased and sorted, values trimmed
    canonical = sorted((name.lower(), ' '.join(str(value).split()))
                       for name, value in headers.items())
    signed_headers = ';'.join(name for name, _ in canonical)
    canonical_request = '\n'.join([
        method,
        # S3 encodes the path once (not twice like other AWS services)
        urllib.parse.quote(parts.path or '/', safe='/~'),
        # Query parameters sorted by name, encoded (unused by get and put)
        '&'.join(
            f"{urllib.parse.quote(k, safe='~')}={urllib.parse.quote(v, safe='~')}"
            for k, v in sorted(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
            ),
        ''.join(f'{name}:{value}\n' for name, value in canonical),
        signed_headers,
        headers['x-amz-content-sha256'],
        ])

    scope = f'{day}/{region}/s3/aws4_request'
    string_to_sign = '\n'.join([
        'AWS4-HMAC-SHA256',
        amz_date,
        scope,
        hashlib.sha256(canonical_request.encode('utf-8')).hexdigest(),
        ])

    key = _hmac(f'AWS4{secret_key}'.encode('utf-8'), day)
    for part in (region, 's3', 'aws4_request'):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    headers['Authorization'] = (
        f'AWS4-HMAC-SHA256 Credential={access_key}/{scope}, '
        f'SignedHeaders={signed_headers}, Signature={signature}'
        )
    return headers


class S3Error(Exception):
    """An error answered by S3, with its error code (NoSuchKey, AccessDenied...)."""

    def __init__(self, status, code, message):
        super().__init__(f'HTTP {status} {code}: {message}')
        self.status = status
        self.code = code


class S3Object:
    """
    One object in an S3 bucket (AWS, or any S3 compatible storage).

    Settings come from the usual AWS ENV vars:
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN (optional),
    AWS_REGION (or AWS_DEFAULT_REGION, default us-east-1), and AWS_ENDPOINT_URL
    for a storage other than AWS (path-style URLs, the most widely supported).
    """

    def __init__(self, bucket, key, environ=os.environ):
        self.bucket = bucket
        self.key = key
        self.access_key = environ.get('AWS_ACCESS_KEY_ID')
        self.secret_key = environ.get('AWS_SECRET_ACCESS_KEY')
        self.session_token = environ.get('AWS_SESSION_TOKEN')
        self.region = (environ.get('AWS_REGION')
                       or environ.get('AWS_DEFAULT_REGION')
                       or 'us-east-1')
        endpoint = environ.get('AWS_ENDPOINT_URL')
        if endpoint:
            self.url = f"{endpoint.rstrip('/')}/{bucket}/{key}"
        else:
            self.url = f'https://{bucket}.s3.{self.region}.amazonaws.com/{key}'
        if not (self.access_key and self.secret_key):
            raise ValueError('AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are needed')

    def __str__(self):
        return f's3://{self.bucket}/{self.key}'

    def _request(self, method, payload=b'', headers=None):
        headers = dict(headers or {})
        if self.session_token:
            headers['x-amz-security-token'] = self.session_token
        headers = sign(
            method, self.url, headers, payload,
            self.access_key, self.secret_key, self.region,
            datetime.datetime.now(datetime.timezone.utc),
            )
        # The URL is encoded like it was signed
        parts = urllib.parse.urlsplit(self.url)
        url = parts._replace(path=urllib.parse.quote(parts.path, safe='/~')).geturl()
        request = urllib.request.Request(
            url, data=payload if method == 'PUT' else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            # The reason is in the body, like <Code>InvalidAccessKeyId</Code>
            body = e.read().decode('utf-8', 'replace')
            code = re.search(r'<Code>(.*?)</Code>', body)
            message = re.search(r'<Message>(.*?)</Message>', body)
            raise S3Error(
                e.code,
                code.group(1) if code else 'Unknown',
                message.group(1) if message else e.reason,
                ) from e

    def get(self):
        """The object's content, None if it doesn't exist. Raises on any other error."""
        try:
            return self._request('GET')
        except S3Error as e:
            # Only a missing object: a missing bucket (NoSuchBucket) is an error
            if e.code == 'NoSuchKey':
                return None
            raise

    def put(self, payload):
        """Replace the object's content (a single PUT: never half written)."""
        self._request('PUT', payload, {'Content-Type': 'application/json'})
