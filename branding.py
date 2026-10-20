"""Shared application identity and vector artwork for source and native builds."""

from pathlib import Path
import sys

APPLICATION_ID = "org.bellonelab.ethoscore"


def asset_path(filename: str) -> Path:
    """Resolve artwork independently of the launcher's working directory."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "assets" / "branding" / filename


def set_process_identity(setup: bool = False) -> None:
    """Give Windows a stable taskbar identity before any Qt window is created."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APPLICATION_ID + (".setup" if setup else ""))


def application_icon():
    """Use native multi-size artwork on Windows, and scalable artwork elsewhere.

    ICO supplies actual raster sizes to Windows' small and large HICON requests,
    including taskbar requests made before a vector icon has been painted by Qt.
    """
    from PySide6.QtGui import QIcon
    if sys.platform == "win32":
        icon = QIcon(str(asset_path("ethoscore-icon.ico")))
        if not icon.isNull():
            return icon
    icon = QIcon(str(asset_path("ethoscore-icon.svg")))
    if icon.isNull():
        icon = QIcon(str(asset_path("ethoscore-icon.png")))
    return icon


def set_windows_shortcut_identity(path: Path) -> None:
    """Associate a Windows shortcut with the application's explicit process ID.

    The stable launcher uses Windows Script Host. Its shortcut must therefore
    explicitly identify Ethoscore so Explorer groups it with the Qt application
    and uses the shortcut's Ethoscore icon rather than the host's default icon.
    Uses the documented IPropertyStore API without a pywin32 dependency.
    """
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("bytes", ctypes.c_ubyte * 16)]

        @classmethod
        def parse(cls, value):
            return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class CountedArray(ctypes.Structure):
        _fields_ = [("count", wintypes.ULONG), ("pointer", ctypes.c_void_p)]

    class VariantValue(ctypes.Union):
        _fields_ = [("text", ctypes.c_wchar_p), ("array", CountedArray),
                    ("integer", ctypes.c_longlong)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3),
                    ("value", VariantValue)]

    def check(result):
        """Convert failing signed HRESULT values into useful installer errors."""
        if result < 0:
            raise OSError(f"Windows shortcut identity failed: HRESULT 0x{result & 0xffffffff:08X}")

    # WinDLL leaves HRESULT handling to check(), including the acceptable
    # RPC_E_CHANGED_MODE result when Qt already initialized this thread's COM.
    ole32 = ctypes.WinDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
    # S_OK and S_FALSE both acquire a COM initialization reference. A thread
    # already initialized in another apartment can still use its current one.
    ole32.CoInitializeEx.restype = ctypes.c_long
    initialized = ole32.CoInitializeEx(None, 2)
    if initialized not in (0, 1, -2147417850):  # RPC_E_CHANGED_MODE
        check(initialized)
    store = ctypes.c_void_p()
    try:
        iid = GUID.parse("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")
        get_store = shell32.SHGetPropertyStoreFromParsingName
        get_store.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        get_store.restype = ctypes.c_long
        check(get_store(str(path.resolve()), None, 2, ctypes.byref(iid), ctypes.byref(store)))
        table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                      ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(table[6])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(table[7])
        key = PROPERTYKEY(GUID.parse("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"), 5)
        value = PROPVARIANT()
        value.vt = 31  # VT_LPWSTR; Python owns the buffer for this synchronous call.
        value.value.text = APPLICATION_ID
        check(set_value(store, ctypes.byref(key), ctypes.byref(value)))
        check(commit(store))
    finally:
        if store.value:
            table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])(store)
        if initialized in (0, 1):
            ole32.CoUninitialize()


def configure_application(app, setup: bool = False) -> None:
    """Apply a consistent identity and icon to every top-level application window."""
    app.setApplicationName("Ethoscore Setup" if setup else "Ethoscore")
    app.setOrganizationName("BelloneLab")
    app.setWindowIcon(application_icon())
    app.setDesktopFileName("ethoscore-setup" if setup else "ethoscore")
