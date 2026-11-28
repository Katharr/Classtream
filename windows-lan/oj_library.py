"""Validate and synchronize locally prepared classroom OJ problems."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from threading import Lock

from oj_sandbox import MAX_OUTPUT_BYTES


SOURCE_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,79}/[a-z0-9][a-z0-9_-]{0,79}', re.ASCII)
MAX_FILE_BYTES = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(data):
    require(type(data.get('schema_version')) is int and data['schema_version'] == 1, '不支持的格式版本')
    problem = {}
    for field, limit in (('title', 120), ('statement', 32768), ('input_format', 32768),
                         ('output_format', 32768), ('constraints', 32768)):
        value = data.get(field)
        require(isinstance(value, str) and 0 < len(value.strip()) <= limit, f'请检查字段 {field}')
        problem[field] = value.strip()
    for field, lower, upper in (('time_ms', 50, 10000), ('memory_mb', 16, 512)):
        value = data.get(field)
        require(type(value) is int and lower <= value <= upper, f'请检查字段 {field}')
        problem[field] = value

    tags = data.get('tags')
    require(isinstance(tags, list) and len(tags) <= 40, '请检查字段 tags')
    unique = {}
    for tag in tags:
        require(isinstance(tag, str) and 0 < len(tag.strip()) <= 80, '请检查字段 tags')
        unique.setdefault(tag.strip().casefold(), tag.strip())
    problem['tags'] = list(unique.values())

    for field in ('sample_cases', 'judge_cases'):
        cases = data.get(field)
        require(isinstance(cases, list) and len(cases) <= 20, f'请检查字段 {field}')
        normalized = []
        for index, case in enumerate(cases, 1):
            label = f'{field} 第 {index} 点'
            require(isinstance(case, dict), f'{label}格式错误')
            run_case = {}
            for key, limit in (('input', MAX_FILE_BYTES), ('output', MAX_OUTPUT_BYTES)):
                value = case.get(key)
                require(isinstance(value, str), f'{label}缺少 {key}')
                require(len(value.encode('utf-8')) <= limit, f'{label}的 {key} 超出评测容量')
                run_case[key] = value
            if field == 'judge_cases':
                score = case.get('score')
                require(type(score) is int and 0 < score <= 100, f'{label}分值无效')
                run_case['score'] = score
            normalized.append(run_case)
        problem[field] = normalized
    require(problem['sample_cases'], '缺少公开样例')
    require(not problem['judge_cases'] or sum(case['score'] for case in problem['judge_cases']) == 100,
            '正式测试点分值之和必须为 100')
    return problem


class PreparedLibrary:
    def __init__(self, config_path, store):
        self.config_path = config_path
        self.store = store
        self.lock = Lock()

    def sync(self):
        with self.lock:
            return self.scan()

    def scan(self):
        report = dict(configured=True, added=0, updated=0, unchanged=0, issues=[])
        try:
            config = json.loads(self.config_path.read_text('utf-8-sig')) if self.config_path.exists() else {}
            prep_dir = config.get('prep_dir')
            if not prep_dir:
                return {**report, 'configured': False}
            require(isinstance(prep_dir, str) and Path(prep_dir).is_absolute(), '备课路径必须为绝对路径')
            prep_root = Path(prep_dir).resolve(strict=True)
            root = (prep_root / 'OJ题目').resolve(strict=True)
            require(root == prep_root / 'OJ题目' and root.is_dir(), '备课题目目录无效')
            files = sorted(path for directory, _, names in root.walk(on_error=raise_scan_error)
                           for path in (directory / name for name in names) if path.suffix.lower() == '.json')
        except (OSError, ValueError, AttributeError):
            return {**report, 'warning': '无法读取备课题目目录，正在使用上次同步结果'}

        candidates = []
        for path in files:
            file = path.relative_to(root).as_posix()
            try:
                require(path.resolve(strict=True) == path and path.is_file(), '文件路径无效')
                with path.open('rb') as stream:
                    content = stream.read(MAX_FILE_BYTES + 1)
                require(len(content) <= MAX_FILE_BYTES, '文件超出导入容量')
                data = json.loads(content.decode('utf-8-sig'))
                require(isinstance(data, dict), '题目必须为 JSON 对象')
                source_id = data.get('source_id')
                require(isinstance(source_id, str) and SOURCE_ID.fullmatch(source_id), '来源 ID 无效')
                candidates.append((source_id, file, data))
            except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
                report['issues'].append(dict(file=file, reason='无法读取或解析题目 JSON'))
            except ValueError as error:
                report['issues'].append(dict(file=file, reason=str(error)))

        counts = Counter(source_id for source_id, _, _ in candidates)
        problems = {}
        for source_id, file, data in candidates:
            try:
                require(counts[source_id] == 1, '来源 ID 重复')
                problem = validate(data)
                require(problem['judge_cases'], '待补评测数据')
                canonical = json.dumps(problem, ensure_ascii=False, sort_keys=True).encode('utf-8')
                problems[source_id] = (problem, hashlib.sha256(canonical).hexdigest())
            except UnicodeError:
                report['issues'].append(dict(file=file, reason='文本编码无效'))
            except ValueError as error:
                report['issues'].append(dict(file=file, reason=str(error)))
        report.update(self.store.sync_prepared(problems))
        return report


def raise_scan_error(error):
    raise error
