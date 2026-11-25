"""Persistent OJ data in the classroom's existing SQLite database."""
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import secrets
import sqlite3
import time


class OJError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


class OJStore:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self, write=False):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection

    def initialize(self):
        with self.connect(write=True) as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS oj_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oj_students (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                    session_hash BLOB UNIQUE, session_until REAL
                );
                CREATE TABLE IF NOT EXISTS oj_problems (id INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS oj_problem_versions (
                    problem_id INTEGER NOT NULL REFERENCES oj_problems(id), version INTEGER NOT NULL,
                    title TEXT NOT NULL, statement TEXT NOT NULL, sample_input TEXT NOT NULL,
                    sample_output TEXT NOT NULL, time_ms INTEGER NOT NULL, memory_mb INTEGER NOT NULL,
                    groups_json TEXT NOT NULL, max_score INTEGER NOT NULL, PRIMARY KEY(problem_id, version)
                );
                CREATE TABLE IF NOT EXISTS oj_sheets (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, is_open INTEGER NOT NULL DEFAULT 0 CHECK(is_open IN (0, 1))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS oj_one_open_sheet ON oj_sheets(is_open) WHERE is_open=1;
                CREATE TABLE IF NOT EXISTS oj_sheet_problems (
                    sheet_id INTEGER NOT NULL REFERENCES oj_sheets(id),
                    problem_id INTEGER NOT NULL REFERENCES oj_problems(id), position INTEGER NOT NULL,
                    PRIMARY KEY(sheet_id, problem_id), UNIQUE(sheet_id, position)
                );
                CREATE TABLE IF NOT EXISTS oj_submissions (
                    id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES oj_students(id),
                    sheet_id INTEGER NOT NULL REFERENCES oj_sheets(id), problem_id INTEGER NOT NULL, version INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('sample', 'judge')), source TEXT NOT NULL,
                    created_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'queued', result_json TEXT,
                    FOREIGN KEY(problem_id, version) REFERENCES oj_problem_versions(problem_id, version)
                );
                CREATE INDEX IF NOT EXISTS oj_cooldown ON oj_submissions(student_id, problem_id, id DESC);
                CREATE INDEX IF NOT EXISTS oj_student_history ON oj_submissions(student_id, id DESC);
                CREATE INDEX IF NOT EXISTS oj_queue ON oj_submissions(status, id);
            ''')
            connection.execute('INSERT OR IGNORE INTO oj_settings VALUES (?, ?)',
                               ('default_password', secrets.token_hex(4)))

    @staticmethod
    def default_password(connection):
        return connection.execute("SELECT value FROM oj_settings WHERE key='default_password'").fetchone()[0]

    @staticmethod
    def password_hash(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)

    def students(self):
        with self.connect() as connection:
            students = [dict(row) for row in connection.execute('SELECT id, username FROM oj_students ORDER BY id')]
            return dict(students=students, default_password=self.default_password(connection))

    def add_student(self, username):
        with self.connect(write=True) as connection:
            salt = secrets.token_bytes(16)
            password_hash = self.password_hash(self.default_password(connection), salt)
            try:
                cursor = connection.execute('INSERT INTO oj_students(username, salt, password_hash) VALUES (?, ?, ?)',
                                            (username, salt, password_hash))
            except sqlite3.IntegrityError as exc:
                raise OJError(409, '用户名已存在') from exc
            return dict(id=cursor.lastrowid, username=username)

    def reset_student(self, student_id):
        with self.connect(write=True) as connection:
            salt = secrets.token_bytes(16)
            password_hash = self.password_hash(self.default_password(connection), salt)
            cursor = connection.execute('''UPDATE oj_students SET salt=?, password_hash=?,
                                           session_hash=NULL, session_until=NULL WHERE id=?''',
                                        (salt, password_hash, student_id))
            if not cursor.rowcount:
                raise OJError(404, '学员不存在')

    def login(self, username, password, lifetime):
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM oj_students WHERE username=?', (username,)).fetchone()
        candidate = self.password_hash(password, row['salt'] if row else bytes(16))
        if not row or not hmac.compare_digest(candidate, row['password_hash']):
            raise OJError(401, '用户名或密码错误')
        token = secrets.token_urlsafe(32)
        with self.connect(write=True) as connection:
            cursor = connection.execute('''UPDATE oj_students SET session_hash=?, session_until=?
                                           WHERE id=? AND salt=?''',
                                        (self.token_hash(token), time.time() + lifetime, row['id'], row['salt']))
            if not cursor.rowcount:
                raise OJError(401, '请重新登录')
        return token, dict(id=row['id'], username=row['username'])

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode('utf-8')).digest()

    def identity(self, token):
        if len(token) != 43:
            raise OJError(401, '请登录')
        with self.connect() as connection:
            row = connection.execute('SELECT id, username FROM oj_students WHERE session_hash=? AND session_until>?',
                                     (self.token_hash(token), time.time())).fetchone()
            if row is None:
                raise OJError(401, '请登录')
            return dict(row)

    def logout(self, token):
        if len(token) == 43:
            with self.connect(write=True) as connection:
                connection.execute('UPDATE oj_students SET session_hash=NULL, session_until=NULL WHERE session_hash=?',
                                   (self.token_hash(token),))

    @staticmethod
    def problem_summary(connection, problem_id):
        row = connection.execute('''SELECT problem_id AS id, version, title, max_score FROM oj_problem_versions
                                    WHERE problem_id=? ORDER BY version DESC LIMIT 1''', (problem_id,)).fetchone()
        return dict(row) if row else None

    def problems(self):
        with self.connect() as connection:
            return [self.problem_summary(connection, row['id'])
                    for row in connection.execute('SELECT id FROM oj_problems ORDER BY id DESC')]

    @staticmethod
    def require_problem(connection, problem_id, version=None, teacher=False):
        row = connection.execute('''SELECT * FROM oj_problem_versions WHERE problem_id=? AND (? IS NULL OR version=?)
                                    ORDER BY version DESC LIMIT 1''', (problem_id, version, version)).fetchone()
        if row is None:
            raise OJError(404, '题目版本不存在')
        result = dict(row)
        result['id'] = result.pop('problem_id')
        groups = result.pop('groups_json')
        if teacher:
            result['groups'] = json.loads(groups)
        return result

    def problem(self, problem_id, version):
        with self.connect() as connection:
            return self.require_problem(connection, problem_id, version, teacher=True)

    def save_problem(self, problem, problem_id=None):
        with self.connect(write=True) as connection:
            version = 1
            if problem_id is None:
                problem_id = connection.execute('INSERT INTO oj_problems DEFAULT VALUES').lastrowid
            else:
                previous = self.require_problem(connection, problem_id)
                version = previous['version'] + 1
            groups = problem['groups']
            connection.execute('''INSERT INTO oj_problem_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                               (problem_id, version, problem['title'], problem['statement'], problem['sample_input'],
                                problem['sample_output'], problem['time_ms'], problem['memory_mb'],
                                json.dumps(groups, ensure_ascii=False), max(group['score'] for group in groups)))
            return dict(id=problem_id, version=version)

    @staticmethod
    def sheet_summary(row):
        return dict(id=row['id'], title=row['title'], open=bool(row['is_open']))

    def sheets(self):
        with self.connect() as connection:
            return [self.sheet_summary(row) for row in connection.execute('SELECT * FROM oj_sheets ORDER BY id DESC')]

    @staticmethod
    def require_sheet(connection, sheet_id):
        row = connection.execute('SELECT * FROM oj_sheets WHERE id=?', (sheet_id,)).fetchone()
        if row is None:
            raise OJError(404, '题单不存在')
        return row

    def sheet(self, sheet_id):
        with self.connect() as connection:
            result = self.sheet_summary(self.require_sheet(connection, sheet_id))
            result['problems'] = [self.problem_summary(connection, row['problem_id']) for row in connection.execute(
                'SELECT problem_id FROM oj_sheet_problems WHERE sheet_id=? ORDER BY position', (sheet_id,))]
            return result

    def save_sheet(self, sheet, sheet_id=None):
        with self.connect(write=True) as connection:
            if sheet_id is None:
                sheet_id = connection.execute('INSERT INTO oj_sheets(title) VALUES (?)', (sheet['title'],)).lastrowid
            else:
                self.require_sheet(connection, sheet_id)
                connection.execute('UPDATE oj_sheets SET title=? WHERE id=?', (sheet['title'], sheet_id))
                connection.execute('DELETE FROM oj_sheet_problems WHERE sheet_id=?', (sheet_id,))
            try:
                connection.executemany('INSERT INTO oj_sheet_problems VALUES (?, ?, ?)',
                                       ((sheet_id, problem_id, position)
                                        for position, problem_id in enumerate(sheet['problem_ids'])))
            except sqlite3.IntegrityError as exc:
                raise OJError(422, '题目不存在或重复') from exc
            if sheet['open']:
                self.set_open(connection, sheet_id)
            return dict(id=sheet_id)

    @staticmethod
    def set_open(connection, sheet_id):
        connection.execute('UPDATE oj_sheets SET is_open=0 WHERE is_open=1')
        connection.execute('UPDATE oj_sheets SET is_open=1 WHERE id=?', (sheet_id,))

    def open_sheet(self, sheet_id):
        with self.connect(write=True) as connection:
            self.require_sheet(connection, sheet_id)
            self.set_open(connection, sheet_id)

    def require_sheet_problem(self, connection, sheet_id, problem_id):
        sheet = self.require_sheet(connection, sheet_id)
        if connection.execute('SELECT 1 FROM oj_sheet_problems WHERE sheet_id=? AND problem_id=?',
                              (sheet_id, problem_id)).fetchone() is None:
            raise OJError(404, '题目不在此题单中')
        return sheet

    def sheet_problem(self, sheet_id, problem_id):
        with self.connect() as connection:
            sheet = self.require_sheet_problem(connection, sheet_id, problem_id)
            return {**self.require_problem(connection, problem_id), 'open': bool(sheet['is_open'])}

    def submit(self, student_id, sheet_id, problem_id, kind, source, expected_version):
        with self.connect(write=True) as connection:
            if not self.require_sheet_problem(connection, sheet_id, problem_id)['is_open']:
                raise OJError(409, '历史题单只能查看')
            version = self.require_problem(connection, problem_id)['version']
            if expected_version is not None and expected_version != version:
                raise OJError(409, '题目已更新。请刷新题面后重新提交', 'problem_version_changed')
            now = time.time()
            last = connection.execute('''SELECT created_at FROM oj_submissions WHERE student_id=? AND problem_id=?
                                        ORDER BY id DESC LIMIT 1''', (student_id, problem_id)).fetchone()
            if last and last['created_at'] + 30 > now:
                remaining = max(1, int(last['created_at'] + 30 - now + .999))
                raise OJError(429, f'请在 {remaining} 秒后重试')
            if connection.execute("SELECT count(*) FROM oj_submissions WHERE status IN ('queued', 'running')").fetchone()[0] >= 40:
                raise OJError(503, '评测队列已满，请稍后重试')
            cursor = connection.execute('''INSERT INTO oj_submissions
                (student_id, sheet_id, problem_id, version, kind, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (student_id, sheet_id, problem_id, version, kind, source, now))
            return dict(id=cursor.lastrowid, version=version, status='queued')

    @staticmethod
    def submission_view(row):
        result = dict(row)
        stored = result.pop('result_json')
        if stored:
            result.update(json.loads(stored))
        return result

    def submissions(self, student_id=None, before=None):
        with self.connect() as connection:
            rows = connection.execute('''SELECT sub.id, sub.sheet_id, sub.problem_id, sub.version, sub.kind,
                    sub.created_at, sub.status, sub.result_json, student.username, problem.title, problem.max_score
                FROM oj_submissions sub JOIN oj_students student ON student.id=sub.student_id
                JOIN oj_problem_versions problem ON problem.problem_id=sub.problem_id AND problem.version=sub.version
                WHERE (? IS NULL OR sub.student_id=?) AND (? IS NULL OR sub.id<?) ORDER BY sub.id DESC LIMIT 50''',
                (student_id, student_id, before, before))
            return [self.submission_view(row) for row in rows]

    def submission(self, submission_id, student_id=None):
        with self.connect() as connection:
            row = connection.execute('''SELECT sub.*, student.username, problem.title, problem.max_score
                FROM oj_submissions sub JOIN oj_students student ON student.id=sub.student_id
                JOIN oj_problem_versions problem ON problem.problem_id=sub.problem_id AND problem.version=sub.version
                WHERE sub.id=? AND (? IS NULL OR sub.student_id=?)''', (submission_id, student_id, student_id)).fetchone()
            if row is None:
                raise OJError(404, '提交不存在')
            return self.submission_view(row)

    def recover_queue(self):
        with self.connect(write=True) as connection:
            connection.execute("UPDATE oj_submissions SET status='queued' WHERE status='running'")

    def claim(self):
        with self.connect(write=True) as connection:
            row = connection.execute("SELECT * FROM oj_submissions WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return None
            connection.execute("UPDATE oj_submissions SET status='running' WHERE id=?", (row['id'],))
            problem = self.require_problem(connection, row['problem_id'], row['version'], teacher=True)
            return {**problem, 'id': row['id'], 'kind': row['kind'], 'source': row['source']}

    def complete(self, submission_id, result):
        with self.connect(write=True) as connection:
            connection.execute("UPDATE oj_submissions SET status='finished', result_json=? WHERE id=?",
                               (json.dumps(result, ensure_ascii=False), submission_id))
