import os.path
import threading
import logging

from six.moves import tkinter as tk
from six.moves import tkinter_ttk as ttk
from six.moves import tkinter_tkfiledialog as tkfiledialog

from loopyupload import LoopyTusUploader
from tuspy import requests_options


class GUI(object):

    def __init__(self):
        self._root = tk.Tk()
        self._root.title('Loopy Upload Client')

        #self._root.geometry('500x300')
        self._root.resizable(width=False, height=False)

        self._root.grid_columnconfigure(0, weight=1)
        self._root.grid_rowconfigure(0, weight=1)

        self._frame = ttk.Frame(self._root)
        self._frame.columnconfigure(1, weight=1)
        self._frame.columnconfigure(1, weight=3)

        self._u_thread = None

        self._auth_ok = False
        self._progress = 0

        def _label_entry(_lbl, _txt, _row, is_password=False, width=None, **gridpos):
            l = ttk.Label(self._frame, text=_lbl)
            l.grid(column=0, row=_row, sticky='W', padx=5, pady=5, **gridpos)

            sv = tk.StringVar()
            sv.set(_txt or '')
            sve = ttk.Entry(self._frame, textvariable=sv, show="*" if is_password else None, width=width)
            sve.grid(column=1, row=_row, padx=5, pady=5, sticky="EW", **gridpos)

            return sv, sve

        self._url, self._urle = _label_entry('Loopy URL', 'https://app.loopb.io/file-upload', 1)
        self._api_key, self._api_keye = _label_entry('API Key', '', 2, width=32)
        self._email, self._emaile = _label_entry('Email (optional)', '', 3)

        self._c_button = ttk.Button(self._frame, text='Connect', state='enabled')
        self._c_button.grid(column=1, row=4, sticky='E', padx=5, pady=5)
        self._c_button.configure(command=self._connect_button_clicked)

        self._u_button = ttk.Button(self._frame, text='Select & Upload', state='disabled')
        self._u_button.grid(column=1, row=5, sticky='E', padx=5, pady=5)
        self._u_button.configure(command=self._upload_button_clicked)

        self._result_label = ttk.Label(self._frame)
        self._result_label.grid(row=6, columnspan=3, padx=5, pady=5)

        self._frame.grid(padx=10, pady=10, sticky='NSEW')

    def _connect_button_clicked(self, *args):
        url = self._url.get() or ''
        auth = self.get_auth_data_from_gui()

        def _connect():
            resp = requests_options(url, headers=auth)
            ms = int(resp.headers['Tus-Max-Size'])
            if int(ms) > 0:
                self._auth_ok = True

        t = threading.Thread(target=_connect)
        t.daemon = True
        t.start()

    def _upload_button_clicked(self, *args):
        name = tkfiledialog.askopenfilename(filetypes = (("Image Stores", "metadata.yaml"),
                                                         ("Videos", "*.mp4 *.MP4 *.mpg *.mpeg *.MPG *.MPEG *.avi *.AVI")))
        if name and os.path.isfile(name):
            self.start_upload(name)

    def update_status(self):
        status = 'Initializing'
        offer_upload = False

        url = self._url.get() or ''
        auth = self.get_auth_data_from_gui()

        if self._auth_ok:
            for e in (self._urle, self._api_keye, self._emaile):
                e.config(state='disabled')
            self._c_button.configure(state='disabled')

            try:
                uploading = self._u_thread.is_alive()
            except:
                uploading = False

            if uploading:
                status = 'Uploading %.1f %%' % float(self._progress or 0.)
            elif (self._progress == 100.0):
                status = 'Upload Finished'
                offer_upload = True
            else:
                status = 'Ready'
                offer_upload = True

        else:
            if auth.get('X-API-Key') and url:
                status = 'Wrong Credentials'
            else:
                status = 'Missing Credentials'

        if offer_upload:
            self._u_button.configure(state='normal')
        else:
            self._u_button.configure(state='disabled')

        msg = 'Status: %s' % status
        self._result_label.configure(text=msg)
        self._root.after(1000, self.update_status)


    def get_auth_data_from_gui(self):
        auth = {}

        api = self._api_key.get() or ''
        if api:
            auth['X-API-Key'] = api

        email = self._email.get() or ''
        if email:
            auth['X-API-User'] = email

        return auth

    def start_upload(self, path):

        url = self._url.get()
        auth = self.get_auth_data_from_gui()

        def _upload():
            self._progress = 0.

            def _log_progress(_p):
                self._progress = _p * 100.
                logging.debug('progress: %s' % self._progress)

            uploader = LoopyTusUploader(url, auth)
            uploader.upload(path, progress_callback=_log_progress)

        self._u_thread = threading.Thread(target=_upload)
        self._u_thread.daemon = True
        self._u_thread.start()

    def run(self):
        self.update_status()
        self._root.mainloop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    GUI().run()

