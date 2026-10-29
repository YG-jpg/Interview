import io

import qrcode


def make_qr_png(text):
    image = qrcode.make(text)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue()
