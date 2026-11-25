"""Compile C++17 and run a sample, custom input, or immutable test groups."""
import os
from pathlib import Path
import shlex
import shutil
import tempfile
import time


COMPILER_PROFILE = 'Classtream.OJ.Compiler'
PROGRAM_PROFILE = 'Classtream.OJ.Program'


def comparable(data):
    lines = data.replace(b'\r\n', b'\n').split(b'\n')
    if lines[-1] == b'':
        lines.pop()
    return [line.rstrip(b' \t') for line in lines]


def matches_output(actual, expected):
    actual_lines = comparable(actual)
    expected_lines = comparable(expected)
    return actual_lines == expected_lines or (actual.endswith(b'\n') and actual_lines == expected_lines + [b''])


class WindowsJudge:
    def __init__(self, compiler=None, scratch=None):
        self.compiler = compiler
        self.scratch = scratch

    def recover(self):
        if self.scratch is None:
            return
        root = Path(self.scratch).absolute()
        if root != root.resolve():
            raise OSError('OJ work directory must not be a redirect')
        root.mkdir(parents=True, exist_ok=True)
        for folder in root.glob('classstream-oj-*'):
            if folder.is_dir() and folder.resolve() == folder and folder.parent == root:
                shutil.rmtree(folder)

    def evaluate(self, task, stop):
        executable = self.compiler or os.environ.get('CLASSTREAM_OJ_GXX')
        if os.name != 'nt' or not executable or not Path(executable).is_file():
            return dict(verdict='judge_error', score=0, detail='教师机尚未配置 OJ C++17 评测环境')
        from oj_sandbox import WindowsSandbox

        sandbox = WindowsSandbox()
        compiler = Path(executable).resolve()
        with tempfile.TemporaryDirectory(prefix='classstream-oj-', dir=self.scratch) as temporary:
            root = Path(temporary)
            build = root / 'build'
            build.mkdir()
            (build / 'main.cpp').write_bytes(task['source'].encode('utf-8'))
            with sandbox.profile(COMPILER_PROFILE) as (sid, sid_text):
                sandbox.restrict_profile(sid_text)
                sandbox.grant(build, sid_text, 'M')
                status, output = self.compile(sandbox, compiler, build, sid, stop)
            if stop.is_set():
                return None
            if status != 'ok':
                text = output.decode('utf-8', 'replace')[:8000].strip()
                if status == 'judge_error' or (not text and status == 'runtime_error'):
                    return dict(verdict='judge_error', score=0, detail='编译器无法在评测环境中运行')
                return dict(verdict='compile_error', score=0, detail=text or '编译超出资源限制')
            run = root / 'run'
            run.mkdir()
            built = build / 'solution.exe'
            if not built.is_file() or built.is_symlink() or built.stat().st_size > 64 * 1024 * 1024:
                return dict(verdict='compile_error', score=0, detail='编译未生成有效程序')
            shutil.copyfile(built, run / 'solution.exe')
            with sandbox.profile(PROGRAM_PROFILE) as (sid, sid_text):
                sandbox.restrict_profile(sid_text)
                sandbox.grant(run, sid_text, 'RX')
                return self.run_cases(task, stop, sandbox, sid, run)

    @staticmethod
    def compile(sandbox, compiler, build, sid, stop):
        driver = [compiler, '-###', '-std=c++17', '-O2', '-static', '-fno-lto', '-fno-use-linker-plugin',
                  '-fdiagnostics-color=never', '-save-temps=obj', 'main.cpp', '-o', 'solution.exe']
        deadline = time.monotonic() + 20

        def invoke(command):
            return sandbox.run(command, build, sid, b'', max(.01, deadline - time.monotonic()), 1024, stop,
                               compiler_bin=compiler.parent)

        status, output = invoke(driver)
        if status != 'ok':
            return 'judge_error', b''
        plan = [shlex.split(line) for line in output.decode('utf-8', 'replace').splitlines() if line.startswith(' ')]
        expected = ['cc1plus.exe', 'cc1plus.exe', 'as.exe', 'collect2.exe']
        if [Path(command[0]).name for command in plan if command] != expected:
            return 'judge_error', b''
        toolchain = compiler.parent.parent
        for command in plan:
            if stop.is_set():
                return 'stopped', b''
            binary = Path(command[0]).resolve()
            if not binary.is_relative_to(toolchain) or not binary.is_file():
                return 'judge_error', b''
            command[0] = binary
            if binary.name == 'collect2.exe':
                command = [compiler.parent / 'ld.exe', *[argument for argument in command[1:] if argument != '-fno-lto']]
            status, output = invoke(command)
            if status != 'ok':
                return status, output
        return 'ok', b''

    @staticmethod
    def run_cases(task, stop, sandbox, sid, directory):
        sample_only = task['kind'] == 'sample'
        custom_input = task.get('custom_input') if sample_only else None
        if custom_input is not None:
            status, output = sandbox.run([directory / 'solution.exe'], directory, sid, custom_input.encode('utf-8'),
                                         task['time_ms'] / 1000, task['memory_mb'], stop)
            if stop.is_set():
                return None
            return dict(verdict='executed' if status == 'ok' else status,
                        score=0, output=output.decode('utf-8', 'replace')[:8000])
        groups = ([dict(input=task['sample_input'], output=task['sample_output'], score=0)]
                  if sample_only else task['groups'])
        cases = []
        score = 0
        for group in groups:
            status, output = sandbox.run([directory / 'solution.exe'], directory, sid, group['input'].encode('utf-8'),
                                         task['time_ms'] / 1000, task['memory_mb'], stop)
            if stop.is_set():
                return None
            if status == 'ok':
                status = 'accepted' if matches_output(output, group['output'].encode('utf-8')) else 'wrong_answer'
            cases.append(dict(verdict=status, points=group['score']))
            if status == 'accepted':
                score = max(score, group['score'])
        failed = [case['verdict'] for case in cases if case['verdict'] != 'accepted']
        verdict = ('partial' if score else failed[0]) if failed else 'accepted'
        result = dict(verdict=verdict, score=score, cases=cases)
        if sample_only:
            result['output'] = output.decode('utf-8', 'replace')[:8000]
        return result
