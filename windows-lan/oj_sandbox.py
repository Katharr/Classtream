"""Launch OJ processes in capability-free Windows AppContainers and bounded jobs."""
import ctypes as ct
from ctypes import wintypes as win
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import subprocess
import tempfile
import time


class Startup(ct.Structure):
    _fields_ = [('size', win.DWORD), ('reserved', win.LPWSTR), ('desktop', win.LPWSTR), ('title', win.LPWSTR),
                ('dimensions', win.DWORD * 8), ('show', win.WORD), ('reserved_size', win.WORD),
                ('reserved_bytes', ct.c_void_p), ('stdin', win.HANDLE), ('stdout', win.HANDLE), ('stderr', win.HANDLE),
                ('attributes', ct.c_void_p)]


class Process(ct.Structure):
    _fields_ = [('process', win.HANDLE), ('thread', win.HANDLE), ('pid', win.DWORD), ('tid', win.DWORD)]


class Capabilities(ct.Structure):
    _fields_ = [('sid', ct.c_void_p), ('capabilities', ct.c_void_p), ('count', win.DWORD), ('reserved', win.DWORD)]


class JobBasic(ct.Structure):
    _fields_ = [('process_time', ct.c_longlong), ('job_time', ct.c_longlong), ('flags', win.DWORD),
                ('min_working_set', ct.c_size_t), ('max_working_set', ct.c_size_t), ('active', win.DWORD),
                ('affinity', ct.c_size_t), ('priority', win.DWORD), ('scheduling', win.DWORD)]


class JobLimits(ct.Structure):
    _fields_ = [('basic', JobBasic), ('io', ct.c_ulonglong * 6), ('process_memory', ct.c_size_t),
                ('job_memory', ct.c_size_t), ('peak_process', ct.c_size_t), ('peak_job', ct.c_size_t)]


class CompletionPort(ct.Structure):
    _fields_ = [('key', ct.c_void_p), ('port', win.HANDLE)]


def require(result):
    if not result:
        raise ct.WinError(ct.get_last_error())
    return result


class WindowsSandbox:
    def __init__(self):
        self.kernel = ct.WinDLL('kernel32', use_last_error=True)
        self.userenv = ct.WinDLL('userenv', use_last_error=True)
        self.security = ct.WinDLL('advapi32', use_last_error=True)
        self.system = Path(os.environ['SystemRoot'])
        pointer = ct.c_void_p
        size = ct.c_size_t
        handle = win.HANDLE
        dword = win.DWORD
        boolean = win.BOOL
        text = win.LPCWSTR
        for library, restype, name, args in (
            (self.userenv, ct.c_long, 'CreateAppContainerProfile', (text, text, text, pointer, dword, pointer)),
            (self.userenv, ct.c_long, 'DeriveAppContainerSidFromAppContainerName', (text, pointer)),
            (self.userenv, ct.c_long, 'GetAppContainerFolderPath', (text, pointer)),
            (self.security, pointer, 'FreeSid', (pointer,)),
            (self.security, boolean, 'ConvertSidToStringSidW', (pointer, pointer)),
            (self.kernel, pointer, 'LocalFree', (pointer,)),
            (self.kernel, boolean, 'InitializeProcThreadAttributeList', (pointer, dword, dword, pointer)),
            (self.kernel, boolean, 'UpdateProcThreadAttribute', (pointer, dword, size, pointer, size, pointer, pointer)),
            (self.kernel, None, 'DeleteProcThreadAttributeList', (pointer,)),
            (self.kernel, boolean, 'CreateProcessW', (text, win.LPWSTR, pointer, pointer, boolean,
                                                    dword, pointer, text, pointer, pointer)),
            (self.kernel, handle, 'CreateJobObjectW', (pointer, text)),
            (self.kernel, boolean, 'SetInformationJobObject', (handle, ct.c_int, pointer, dword)),
            (self.kernel, boolean, 'AssignProcessToJobObject', (handle, handle)),
            (self.kernel, boolean, 'TerminateJobObject', (handle, win.UINT)),
            (self.kernel, boolean, 'TerminateProcess', (handle, win.UINT)),
            (self.kernel, dword, 'ResumeThread', (handle,)),
            (self.kernel, dword, 'WaitForSingleObject', (handle, dword)),
            (self.kernel, boolean, 'GetExitCodeProcess', (handle, pointer)),
            (self.kernel, boolean, 'CloseHandle', (handle,)),
            (self.kernel, boolean, 'PeekNamedPipe', (handle, pointer, dword, pointer, pointer, pointer)),
            (self.kernel, handle, 'CreateIoCompletionPort', (handle, handle, size, dword)),
            (self.kernel, boolean, 'GetQueuedCompletionStatus', (handle, pointer, pointer, pointer, dword)),
        ):
            function = getattr(library, name)
            function.restype = restype
            function.argtypes = args

    @contextmanager
    def profile(self, name):
        sid = ct.c_void_p()
        result = self.userenv.CreateAppContainerProfile(name, name, name, None, 0, ct.byref(sid))
        if result & 0xffffffff == 0x800700b7:
            result = self.userenv.DeriveAppContainerSidFromAppContainerName(name, ct.byref(sid))
        if result:
            raise OSError(f'CreateAppContainerProfile: 0x{result & 0xffffffff:08x}')
        text = win.LPWSTR()
        try:
            require(self.security.ConvertSidToStringSidW(sid, ct.byref(text)))
            try:
                yield sid, text.value
            finally:
                self.kernel.LocalFree(text)
        finally:
            self.security.FreeSid(sid)

    def grant(self, directory, sid, rights):
        self.set_access(directory, '/grant:r', sid, rights)

    def restrict_profile(self, sid):
        folder = win.LPWSTR()
        result = self.userenv.GetAppContainerFolderPath(sid, ct.byref(folder))
        if result:
            raise OSError(f'GetAppContainerFolderPath: 0x{result & 0xffffffff:08x}')
        try:
            self.set_access(folder.value, '/deny', sid, 'WD,AD,WEA,WA,DE,DC,WDAC,WO')
        finally:
            self.kernel.LocalFree(folder)

    def set_access(self, directory, action, sid, rights):
        result = subprocess.run([self.system / 'System32/icacls.exe', str(directory), action,
                                 f'*{sid}:(OI)(CI)({rights})'], capture_output=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise OSError(f'Could not configure OJ sandbox permissions for {directory}')

    def run(self, argv, cwd, sid, stdin, seconds, memory_mb, stop, compiler_bin=None):
        import msvcrt

        kernel = self.kernel
        with ExitStack() as resources:
            with tempfile.NamedTemporaryFile(dir=cwd.parent, delete=False) as input_buffer:
                input_buffer.write(stdin)
                input_name = input_buffer.name
            resources.callback(Path(input_name).unlink, missing_ok=True)
            input_file = resources.enter_context(open(input_name, 'rb'))
            null = resources.enter_context(open(os.devnull, 'wb'))
            reader, writer = os.pipe()
            output = resources.enter_context(os.fdopen(reader, 'rb', buffering=0))
            pipe = resources.enter_context(os.fdopen(writer, 'wb', buffering=0))
            descriptors = [input_file.fileno(), pipe.fileno(), pipe.fileno() if compiler_bin else null.fileno()]
            handles = [msvcrt.get_osfhandle(descriptor) for descriptor in descriptors]
            unique_handles = list(dict.fromkeys(handles))
            handle_array = (win.HANDLE * len(unique_handles))(*unique_handles)
            for descriptor in set(descriptors):
                os.set_inheritable(descriptor, True)
            job = require(kernel.CreateJobObjectW(None, None))
            resources.callback(kernel.CloseHandle, job)
            port = require(kernel.CreateIoCompletionPort(ct.c_void_p(-1), None, 0, 1))
            resources.callback(kernel.CloseHandle, port)
            completion = CompletionPort(1, port)
            require(kernel.SetInformationJobObject(job, 7, ct.byref(completion), ct.sizeof(completion)))
            limits = JobLimits()
            limits.basic.flags = 0x2000 | 0x100 | 0x200 | 0x08
            limits.basic.active = 1
            limits.process_memory = limits.job_memory = memory_mb * 1024 * 1024
            require(kernel.SetInformationJobObject(job, 9, ct.byref(limits), ct.sizeof(limits)))
            attr_size = ct.c_size_t()
            kernel.InitializeProcThreadAttributeList(None, 3, 0, ct.byref(attr_size))
            attributes = ct.create_string_buffer(attr_size.value)
            require(kernel.InitializeProcThreadAttributeList(attributes, 3, 0, ct.byref(attr_size)))
            resources.callback(kernel.DeleteProcThreadAttributeList, attributes)
            capabilities = Capabilities(sid, None, 0, 0)
            opt_out = win.DWORD(1)
            for attribute, value, length in ((0x20002, handle_array, ct.sizeof(handle_array)),
                                             (0x20009, capabilities, ct.sizeof(capabilities)),
                                             (0x2000f, opt_out, ct.sizeof(opt_out))):
                require(kernel.UpdateProcThreadAttribute(attributes, 0, attribute, ct.byref(value), length, None, None))
            startup = Startup()
            startup.size = ct.sizeof(startup)
            startup.dimensions[7] = 0x100
            startup.stdin, startup.stdout, startup.stderr = handles
            startup.attributes = ct.cast(attributes, ct.c_void_p)
            process = Process()
            env = dict(SystemRoot=str(self.system), LOCALAPPDATA=os.environ['LOCALAPPDATA'], TEMP=str(cwd), TMP=str(cwd),
                       PATH=str(compiler_bin or Path(argv[0]).parent) + ';' + str(self.system / 'System32'))
            environment = ct.create_unicode_buffer('\0'.join(f'{key}={env[key]}' for key in sorted(env, key=str.upper)) + '\0\0')
            command = ct.create_unicode_buffer(subprocess.list2cmdline(list(map(str, argv))))
            flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS | 0x80000 | 0x400 | 0x4
            require(kernel.CreateProcessW(str(argv[0]), command, None, None, True, flags, environment,
                                          str(cwd), ct.byref(startup), ct.byref(process)))
            resources.callback(kernel.CloseHandle, process.thread)
            resources.callback(kernel.CloseHandle, process.process)
            try:
                if not kernel.AssignProcessToJobObject(job, process.process):
                    error = ct.WinError(ct.get_last_error())
                    kernel.TerminateProcess(process.process, 1)
                    raise error
                pipe.close()
                if kernel.ResumeThread(process.thread) == 0xffffffff:
                    raise ct.WinError(ct.get_last_error())
                return self.collect(port, process.process, output, seconds, stop, cwd if compiler_bin else None)
            finally:
                kernel.TerminateJobObject(job, 1)
                kernel.WaitForSingleObject(process.process, 5000)

    def collect(self, port, process, pipe, seconds, stop, build):
        import msvcrt

        deadline = time.monotonic() + seconds
        kernel = self.kernel
        output = bytearray()
        pipe_handle = msvcrt.get_osfhandle(pipe.fileno())
        available, message, key, overlapped = win.DWORD(), win.DWORD(), ct.c_size_t(), ct.c_void_p()
        max_output = 262144
        check_disk = 0.0
        while not stop.is_set():
            while kernel.GetQueuedCompletionStatus(port, ct.byref(message), ct.byref(key), ct.byref(overlapped), 0):
                if message.value in (9, 10):
                    return 'memory_limit', bytes(output)
                if message.value == 3:
                    return 'runtime_error', bytes(output)
            exited = kernel.WaitForSingleObject(process, 0) == 0
            available.value = 0
            if not kernel.PeekNamedPipe(pipe_handle, None, 0, None, ct.byref(available), None):
                if ct.get_last_error() not in (109, 232):
                    raise ct.WinError(ct.get_last_error())
            if available.value:
                if len(output) + available.value > max_output:
                    return 'output_limit', bytes(output)
                output.extend(pipe.read(available.value))
            now = time.monotonic()
            if build and now >= check_disk:
                check_disk = now + .03
                total = 0
                for path in build.iterdir():
                    try:
                        total += path.stat(follow_symlinks=False).st_size
                    except FileNotFoundError:
                        pass
                if total > 64 * 1024 * 1024:
                    return 'output_limit', bytes(output)
            if now >= deadline and not exited:
                return 'timeout', bytes(output)
            if exited and not available.value:
                code = win.DWORD()
                require(kernel.GetExitCodeProcess(process, ct.byref(code)))
                if code.value in (0xc0000017, 0xc000009a, 0xc000012d):
                    return 'memory_limit', bytes(output)
                return ('ok' if not code.value else 'runtime_error'), bytes(output)
            if not available.value:
                stop.wait(.005)
        return 'stopped', b''
