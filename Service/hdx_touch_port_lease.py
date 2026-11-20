"""Host-side initialization lease for the positively identified HDX touch TTY.

Keeps one nonblocking descriptor open without reading or writing touch data.
Wine remains the sole data consumer. Restores terminal settings after Wine exits.
"""
import os
import termios
from hdx_touch_probe import resolve_touch


class TouchPortLease:
    def __enter__(self):
        self.node = resolve_touch()
        self.fd = os.open(self.node, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            self.original = termios.tcgetattr(self.fd)
            attrs = termios.tcgetattr(self.fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = (attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | termios.HUPCL)) | termios.CS8 | termios.CREAD | termios.CLOCAL
            if hasattr(termios, 'CRTSCTS'):
                attrs[2] &= ~termios.CRTSCTS
            attrs[4] = attrs[5] = termios.B9600
            attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        except BaseException:
            os.close(self.fd)
            raise
        return self

    def __exit__(self, *_):
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.original)
        except (OSError, termios.error):
            pass  # Device removal invalidates the old descriptor, not a new port.
        finally:
            os.close(self.fd)

