from __future__ import annotations

import ctypes
import sys
from dataclasses import asdict, dataclass
from typing import Protocol


MAX_WINDOWS_PID = (1 << 32) - 1


class ResourceProbeError(RuntimeError):
    """A stable, safe error that never includes operating-system details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProcessResourceSample:
    pid: int
    private_bytes: int
    working_set_bytes: int
    handle_count: int
    thread_count: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class ResourceAdapter(Protocol):
    def sample(self, pid: int) -> ProcessResourceSample: ...


def validate_pid(pid: object) -> int:
    if isinstance(pid, bool) or not isinstance(pid, int):
        raise ResourceProbeError("invalid_pid")
    if pid < 1 or pid > MAX_WINDOWS_PID:
        raise ResourceProbeError("invalid_pid")
    return pid


def sample_process(
    pid: object,
    *,
    adapter: ResourceAdapter | None = None,
    platform: str | None = None,
) -> ProcessResourceSample:
    validated_pid = validate_pid(pid)
    current_platform = sys.platform if platform is None else platform
    if current_platform != "win32":
        raise ResourceProbeError("unsupported_platform")

    try:
        result = (adapter or WindowsResourceAdapter()).sample(validated_pid)
        _validate_sample(result, validated_pid)
        return result
    except Exception:
        raise ResourceProbeError("resource_sample_failed") from None


def _validate_sample(sample: object, expected_pid: int) -> None:
    if not isinstance(sample, ProcessResourceSample) or sample.pid != expected_pid:
        raise ResourceProbeError("resource_sample_failed")
    values = (
        sample.private_bytes,
        sample.working_set_bytes,
        sample.handle_count,
        sample.thread_count,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ResourceProbeError("resource_sample_failed")


class WindowsResourceAdapter:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_VM_READ = 0x0010
    TH32CS_SNAPTHREAD = 0x00000004
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows APIs are unavailable")

        from ctypes import wintypes

        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._ThreadEntry32 = self._make_thread_entry_type()
        self._ProcessMemoryCountersEx = self._make_process_memory_counters_type()
        self._configure_functions()

    def sample(self, pid: int) -> ProcessResourceSample:
        process = self._kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION | self.PROCESS_VM_READ,
            False,
            pid,
        )
        if not process:
            raise OSError("OpenProcess failed")

        try:
            counters = self._ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            if not self._psapi.GetProcessMemoryInfo(
                process,
                ctypes.byref(counters),
                counters.cb,
            ):
                raise OSError("GetProcessMemoryInfo failed")

            handle_count = self._wintypes.DWORD()
            if not self._kernel32.GetProcessHandleCount(process, ctypes.byref(handle_count)):
                raise OSError("GetProcessHandleCount failed")

            return ProcessResourceSample(
                pid=pid,
                private_bytes=int(counters.PrivateUsage),
                working_set_bytes=int(counters.WorkingSetSize),
                handle_count=int(handle_count.value),
                thread_count=self._count_threads(pid),
            )
        finally:
            self._kernel32.CloseHandle(process)

    def _count_threads(self, pid: int) -> int:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(self.TH32CS_SNAPTHREAD, 0)
        if snapshot == self.INVALID_HANDLE_VALUE:
            raise OSError("CreateToolhelp32Snapshot failed")

        try:
            entry = self._ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            ctypes.set_last_error(0)
            success = self._kernel32.Thread32First(snapshot, ctypes.byref(entry))
            if not success:
                error = ctypes.get_last_error()
                if error == 18:  # ERROR_NO_MORE_FILES
                    return 0
                raise OSError("Thread32First failed")

            count = 0
            while success:
                if int(entry.th32OwnerProcessID) == pid:
                    count += 1
                ctypes.set_last_error(0)
                success = self._kernel32.Thread32Next(snapshot, ctypes.byref(entry))
            if ctypes.get_last_error() not in (0, 18):
                raise OSError("Thread32Next failed")
            return count
        finally:
            self._kernel32.CloseHandle(snapshot)

    def _configure_functions(self) -> None:
        wintypes = self._wintypes
        kernel32 = self._kernel32

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetProcessHandleCount.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetProcessHandleCount.restype = wintypes.BOOL
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

        thread_entry = self._ThreadEntry32
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(thread_entry)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(thread_entry)]
        kernel32.Thread32Next.restype = wintypes.BOOL

        counters = self._ProcessMemoryCountersEx
        self._psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(counters),
            wintypes.DWORD,
        ]
        self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    def _make_thread_entry_type(self) -> type[ctypes.Structure]:
        wintypes = self._wintypes

        class ThreadEntry32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        return ThreadEntry32

    def _make_process_memory_counters_type(self) -> type[ctypes.Structure]:
        wintypes = self._wintypes

        class ProcessMemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        return ProcessMemoryCountersEx
