from __future__ import print_function
import os
import base64
import logging
import sys


from six.moves import urllib, http_client
from six.moves.urllib.parse import urlparse, urlunparse


DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024
TUS_VERSION = '1.0.0'


class MethodRequest(urllib.request.Request):
    # See: https://gist.github.com/logic/2715756

    def __init__(self, *args, **kwargs):
        if 'method' in kwargs:
            self._method = kwargs['method']
            del kwargs['method']
        else:
            self._method = None
        urllib.request.Request.__init__(self, *args, **kwargs)

    def get_method(self, *args, **kwargs):
        # noinspection PyArgumentList
        return self._method if self._method is not None else urllib.request.Request.get_method(self, *args, **kwargs)


class TusError(Exception):
    def __init__(self, message, response=None, code=None):
        self.message = message  # python2 compatibility
        super(TusError, self).__init__(message)
        self.response = response
        self.code = code

    def __str__(self):
        if self.response is not None:
            text = self.response.text
            return "TusError('%s', response=(%s, '%s'))" % (
                    self.message,
                    self.response.status_code,
                    text.strip())
        else:
            return "TusError('%s')" % self.message or self.code


class _RequestsResponse(object):
    def __init__(self, resp, data):
        self.status_code = int(resp.code)
        self.headers = {k.title(): v for k, v in resp.info().items()}
        self.data = data


def _request(req):
    resp = urllib.request.urlopen(req)
    data = resp.read()
    resp.close()
    return _RequestsResponse(resp, data)


def _requests(endpoint, method, headers, data):
    # endpoint.encode("utf-8")
    req = MethodRequest(endpoint, data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        return _request(req)
    except urllib.error.HTTPError as e:
        raise TusError(e, code=e.code)
    except urllib.error.URLError:
        raise TusError('connection error')


def requests_post(endpoint, headers=None, data=None):
    return _requests(endpoint, 'POST', headers or {}, data)


def requests_patch(endpoint, headers=None, data=None):
    return _requests(endpoint, 'PATCH', headers or {}, data)


def requests_head(endpoint, headers=None, data=None):
    return _requests(endpoint, 'HEAD', headers or {}, data)


def requests_options(endpoint, headers=None, data=None):
    return _requests(endpoint, 'OPTIONS', headers or {}, data)


def upload(file_obj,
           tus_endpoint,
           chunk_size=DEFAULT_CHUNK_SIZE,
           file_name=None,
           headers=None,
           metadata=None):

    file_name = file_name or os.path.basename(file_obj.name)
    file_size = _get_file_size(file_obj)

    file_endpoint = create(
        tus_endpoint,
        file_name,
        file_size,
        headers=headers,
        metadata=metadata)

    resume(
        file_obj,
        file_endpoint,
        chunk_size=chunk_size,
        headers=headers,
        offset=0)


def _get_file_size(f):
    if not _is_seekable(f):
        return

    pos = f.tell()
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(pos)
    return size


def _is_seekable(f):
    if sys.version_info.major == 2:
        return hasattr(f, 'seek')
    else:
        return f.seekable()


def _absolute_file_location(tus_endpoint, file_endpoint):
    parsed_file_endpoint = urlparse(file_endpoint)
    if parsed_file_endpoint.netloc:
        return file_endpoint

    parsed_tus_endpoint = urlparse(tus_endpoint)
    return urlunparse((
        parsed_tus_endpoint.scheme,
        parsed_tus_endpoint.netloc,
    ) + parsed_file_endpoint[2:])


def create(tus_endpoint, file_name, file_size, headers=None, metadata=None, _log=None):
    _log.info("Creating file endpoint: %s" % tus_endpoint)

    h = {"Tus-Resumable": TUS_VERSION}

    if file_size is None:
        h['Upload-Defer-Length'] = '1'
    else:
        h['Upload-Length'] = str(file_size)
        _log.info('Setting upload length')

    if headers:
        h.update(headers)

    if metadata is None:
        metadata = {}

    metadata['filename'] = file_name

    pairs = [
        k + ' ' + base64.b64encode(v.encode('utf-8')).decode()
        for k, v in metadata.items()
    ]
    h["Upload-Metadata"] = ','.join(pairs)

    response = requests_post(tus_endpoint, headers=h)
    if response.status_code != 201:
        raise TusError("Create failed", response=response, code=response.status_code)

    location = response.headers["Location"]

    _log.info("Created: %s", location)

    return _absolute_file_location(tus_endpoint, location)


def resume(file_obj,
           file_endpoint,
           chunk_size=DEFAULT_CHUNK_SIZE,
           headers=None,
           offset=None,
           sent_cb=None,
           _log=None):

    if offset is None:
        offset = _get_offset(file_endpoint, headers=headers, _log=_log)

    if offset != 0:
        if not _is_seekable(file_obj):
            raise Exception("file is not seekable")

        file_obj.seek(offset)

    total_sent = 0
    data = file_obj.read(chunk_size)
    while data:
        upload_chunk(data, offset, file_endpoint, headers=headers, _log=_log)
        total_sent += len(data)

        if sent_cb is not None:
            sent_cb(total_sent)
        else:
            _log.info("Total bytes sent: %i", total_sent)

        offset += len(data)
        data = file_obj.read(chunk_size)

    if not _is_seekable(file_obj):
        if headers is None:
            headers = {}
        else:
            headers = dict(headers)

        set_final_size(file_endpoint, offset, headers, _log=_log)


def set_final_size(file_endpoint, size, headers, _log=None):
    _log.info('Setting upload length')

    headers['Upload-Length'] = str(size)
    upload_chunk(bytes(), size, file_endpoint, headers=headers, _log=_log)


def _get_offset(file_endpoint, headers=None, _log=None):
    _log.info("Getting offset")

    h = {"Tus-Resumable": TUS_VERSION}

    if headers:
        h.update(headers)

    response = requests_head(file_endpoint, headers=h)

    offset = int(response.headers["Upload-Offset"])
    _log.info("offset=%i", offset)
    return offset


def upload_chunk(data, offset, file_endpoint, headers=None, _log=None):
    _log.info("Uploading %d bytes chunk from offset: %i", len(data), offset)

    h = {
        'Content-Type': 'application/offset+octet-stream',
        'Upload-Offset': str(offset),
        'Tus-Resumable': TUS_VERSION,
    }

    if headers:
        h.update(headers)

    response = requests_patch(file_endpoint, headers=h, data=data)
    if response.status_code != 204:
        raise TusError("Upload chunk failed", response=response, code=response.status_code)



