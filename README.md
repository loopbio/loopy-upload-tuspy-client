# loopy-upload-tuspy-client
Pure python implementation of TUS resumable upload protocol compatible and suitable for video uploads to http://app.loopb.io. The
library may also be used with other compatible TUS servers.

This single file library/implementation may be copy-pasted into your project.

For non-loopy uses, or if you require any additional features not present in this python implmentation,
please check out the official upstream client https://github.com/tus/tus-py-client/


## Example

```python
import os.path

from tuspy import create, resume, requests_options

class LoopyTusUploader(object):
    def __init__(self, url, headers=None, metadata=None, chunk_size=4*1024*1024):
        self._url = url
        self._headers = headers or {}
        self._metadata = metadata or {}
        self._chunk_size = chunk_size

    def _check_size(self, size):
        resp = requests_options(self._url, headers=dict(self._headers))
        ms = int(resp.headers['Tus-Max-Size'])
        if (ms > 0) and (size > ms):
            raise ValueError('too large')

    def upload_video(self, path, progress_callback=None):
        if not os.path.isfile(path):
            raise ValueError('must be file')

        file_size = os.path.getsize(path)
        file_name = os.path.basename(path)

        def _size_cb(_total_sent):
            if progress_callback is not None:
                progress_callback(_total_sent / float(file_size))

        print('upload video: %r' % path)
        self._check_size(file_size)

        with open(path, 'rb') as file_obj:

            headers = dict(self._headers)

            file_endpoint = create(self._url,
                                   file_name,
                                   os.path.getsize(path),
                                   headers=headers,
                                   metadata=self._metadata)

            print('file endpoint: %s' % file_endpoint)

            resume(file_obj,
                   file_endpoint,
                   chunk_size=self._chunk_size,
                   headers=headers,
                   offset=0,
                   sent_cb=_size_cb)


uploader = LoopyTusUploader('https://you-looopy-onsite-server.com/file-upload',
                            headers={'X-API-Key': '123456abcdef123456abcdef123456ab'})
uploader.upload('/path/to/video.mp4')


```

## LICENSE
MIT, based on https://github.com/cenkalti/tus.py


