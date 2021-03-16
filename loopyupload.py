import shutil
import tarfile
import os.path
import logging

import six

from tuspy import create, resume, upload_chunk, set_final_size, TusError, requests_options


class _Devnull(object):
    def write(self, *_):
        pass


def get_directory_size(start_path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    return total_size


def get_store_files(store_dir):
    out = []  # [(rel, abs),...]

    base = os.path.abspath(store_dir)
    for dirpath, dirnames, filenames in os.walk(base):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            rel = os.path.relpath(fp, base)
            out.append((rel, fp))

    return out


class LazyTarImgstore(object):

    def __init__(self, path):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise ValueError('not an imgstore metadata.yaml')

        fn = os.path.basename(path)
        if fn != 'metadata.yaml':
            raise ValueError('not an imgstore')

        self._dirpath = os.path.dirname(path)
        self._size = get_directory_size(self._dirpath)

    @classmethod
    def new_from_directory(cls, path):
        return cls(os.path.join(path, 'metadata.yaml'))

    @property
    def size(self):
        return self._size

    def iter_chunks_or_files(self, progress_callback):
        written = 0

        for path, buf, sz in self.iter_directory_chunks_or_files(self._dirpath):

            yield (path, buf)

            if progress_callback is not None:
                # only count the progress of writing the files, disregard the headers
                written += (sz if path is not None else 0)
                progress_callback(written / float(self._size))

    @staticmethod
    def iter_directory_chunks_or_files(path):

        # this is a fake tar file just so we can use the gettarinfo() machinery and
        # API in a comfortable way to generate tar headers for each file in the archive
        t = tarfile.open(name=None,
                         mode='w|',
                         fileobj=_Devnull())

        with t:

            for rel, abs_ in get_store_files(path):

                inf = t.gettarinfo(name=abs_, arcname=rel)
                buf = inf.tobuf(t.format, t.encoding, t.errors)

                # the tar header for the file
                yield (None, buf, len(buf))

                # the file path
                yield (abs_, None, inf.size)

                blocks, remainder = divmod(inf.size, tarfile.BLOCKSIZE)
                if remainder > 0:
                    # any necessary padding due to the file size
                    l = tarfile.BLOCKSIZE - remainder
                    if six.PY3:
                        pad = bytes(0 for _ in range(l))
                    else:
                        pad = "\0" * l

                    yield (None, pad, l)


class LoopyTusUploader(object):
    def __init__(self, url, headers=None, metadata=None, chunk_size=4*1024*1024):
        self._url = url
        self._log = logging.getLogger('uploader')
        self._headers = headers or {}
        self._metadata = metadata or {}
        self._chunk_size = chunk_size

    def _check_size(self, size):
        resp = requests_options(self._url, headers=dict(self._headers))
        ms = int(resp.headers['Tus-Max-Size'])
        self._log.info('upload size: %s, max size: %s' % (size, ms))
        if (ms > 0) and (size > ms):
            raise TusError('too large')

    @property
    def api_key(self):
        return self._headers.get('X-API-Key', '')

    def upload_video(self, path, progress_callback=None):
        if not os.path.isfile(path):
            raise ValueError('must be file')

        file_size = os.path.getsize(path)
        file_name = os.path.basename(path)

        def _size_cb(_total_sent):
            if progress_callback is not None:
                progress_callback(_total_sent / float(file_size))

        self._log.info('upload video: %r' % path)
        self._check_size(file_size)

        with open(path, 'rb') as file_obj:

            headers = dict(self._headers)

            file_endpoint = create(self._url,
                                   file_name,
                                   os.path.getsize(path),
                                   headers=headers,
                                   metadata=self._metadata,
                                   _log=self._log)

            self._log.info('file endpoint: %s' % file_endpoint)

            resume(file_obj,
                   file_endpoint,
                   chunk_size=self._chunk_size,
                   headers=headers,
                   offset=0,
                   sent_cb=_size_cb,
                   _log=self._log)

    def upload_directory(self, path, title='unknown-title', progress_callback=None):

        self._log.info('upload directory: %r (title: %r)' % (path, title))

        laxy = LazyTarImgstore.new_from_directory(path)
        self._check_size(laxy.size)

        def _maybe_progress(_offset):
            _progress = min(100., _offset / float(laxy.size))
            if progress_callback:
                progress_callback(_progress)
            else:
                self._log.debug('progress: %.1f%%' % (_progress * 100))

        headers = dict(self._headers)

        self._log.debug('headers: %r' % (self._headers,))
        self._log.debug('metadata: %r' % (self._metadata,))

        file_endpoint = create(self._url,
                               title,
                               file_size=None,
                               headers=headers,
                               metadata=self._metadata,
                               _log=self._log)

        offset = 0
        for path, buf in laxy.iter_chunks_or_files(progress_callback=None):
            if path is not None:
                self._log.debug('file chunk')
                with open(path, 'rb') as file_obj:
                    data = file_obj.read(self._chunk_size)
                    while data:
                        upload_chunk(data, offset, file_endpoint, headers=headers, _log=self._log)

                        offset += len(data)
                        _maybe_progress(offset)

                        data = file_obj.read(self._chunk_size)

            if buf is not None:
                self._log.debug('raw chunk')
                upload_chunk(buf, offset, file_endpoint, headers=headers, _log=self._log)

                offset += len(buf)
                _maybe_progress(offset)

        set_final_size(file_endpoint, offset, headers, _log=self._log)

    def upload_imgstore(self, path, progress_callback=None):
        path = os.path.abspath(path)
        if os.path.isfile(path) and (os.path.basename(path) == 'metadata.yaml'):
            return self.upload_directory(os.path.dirname(path), 'imgstore.tar',
                                         progress_callback=progress_callback)
        raise ValueError('not an imgstore')

    def upload(self, path, progress_callback=None):
        path = os.path.abspath(path)

        if os.path.isfile(path):
            if os.path.basename(path) == 'metadata.yaml':
                return self.upload_imgstore(path, progress_callback=progress_callback)
            else:
                return self.upload_video(path, progress_callback=progress_callback)
        elif os.path.isdir(path):
            return self.upload_imgstore(os.path.join(path, 'metadata.yaml'),
                                        progress_callback=progress_callback)
        else:
            raise NotImplementedError

