# loopy-upload-tuspy-client
Pure python implementation of TUS resumable upload protocol compatible and suitable for video uploads to
http://app.loopb.io. The `tuspy` file may also be used with other compatible TUS servers.

The `loopyupload` file implements loopy-specific authentication and can be used to upload files and
imgstores to your loopy account.

For non-loopy uses, or if you require any additional features not present in this python implmentation,
please check out the official upstream client https://github.com/tus/tus-py-client/

This 2-file library/implementation may be copy-pasted into your project.


## Example

```python
from loopyupload import LoopyTusUploader

uploader = LoopyTusUploader('https://your-loopy-onsite-server.com/file-upload',
                            headers={'X-API-Key': '123456abcdef123456abcdef123456ab'})
uploader.upload('/path/to/video.mp4')

```

## LICENSE
MIT, based on https://github.com/cenkalti/tus.py


