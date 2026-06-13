from __future__ import annotations

import ctypes
from ctypes import wintypes


SOUND_ASYNC = 0x0001
SOUND_NODEFAULT = 0x0002
SOUND_MEMORY = 0x0004
SOUND_LOOP = 0x0008
SOUND_PURGE = 0x0040


class WinMemoryAudioPlayer:
    def __init__(self):
        self.buffer = None
        self.available = True
        try:
            self.winmm = ctypes.WinDLL("winmm", use_last_error=True)
            self.play_sound = self.winmm.PlaySoundW
            self.play_sound.argtypes = [ctypes.c_void_p, wintypes.HMODULE, wintypes.DWORD]
            self.play_sound.restype = wintypes.BOOL
        except Exception:
            self.available = False
            self.winmm = None
            self.play_sound = None

    def play_loop_bytes(self, wav_bytes: bytes) -> bool:
        if not self.available or not wav_bytes:
            return False
        if not (len(wav_bytes) >= 12 and wav_bytes[:4] == b"RIFF" and wav_bytes[8:12] == b"WAVE"):
            return False

        self.stop()
        self.buffer = ctypes.create_string_buffer(wav_bytes)
        pointer = ctypes.cast(self.buffer, ctypes.c_void_p)
        result = self.play_sound(
            pointer,
            None,
            SOUND_MEMORY | SOUND_ASYNC | SOUND_LOOP | SOUND_NODEFAULT,
        )
        return bool(result)

    def stop(self):
        if self.available and self.play_sound:
            self.play_sound(None, None, SOUND_PURGE)
        self.buffer = None
