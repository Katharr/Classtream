"""OJ acceptance at the real HTTP application boundary, with isolated data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-lan'))


def verify(data):
    os.environ['CLASSTREAM_DATA'] = str(data)
    os.environ['CLASSTREAM_HOME'] = str(data)
    from app import database
    from app.paths import DB_PATH
    from compat import create_application
    from fastapi.testclient import TestClient
    from oj_store import OJStore

    database.init_db()
    database.create_admin('teacher', 'test-secret', 'Teacher')
    gate = threading.Event()

    class FixtureRunner:
        def evaluate(self, task, stop):
            while not gate.wait(.03):
                if stop.is_set():
                    return None
            return dict(verdict='accepted', score=task['max_score'])

    app = create_application('http://127.0.0.1', oj_runner=FixtureRunner())
    with TestClient(app, client=('127.0.0.1', 12345)) as teacher:
        student = TestClient(app, client=('192.0.2.2', 12345))
        assert not database.get_active_session()
        assert student.get('/oj').status_code == 200
        assert student.get('/api/oj/sheets').status_code == 401
        signed_in = teacher.post('/api/admin/login', json={'username': 'teacher', 'password': 'test-secret'})
        assert signed_in.status_code == 200, signed_in.text
        teacher.headers['X-Admin-Token'] = signed_in.json()['token']
        assert student.get('/api/oj/teacher/students', headers=teacher.headers).status_code == 403
        assert teacher.post('/api/oj/teacher/students', json={'username': 'Ada'}).status_code == 201
        assert teacher.post('/api/oj/teacher/students', json={'username': 'ada'}).status_code == 409
        roster = teacher.get('/api/oj/teacher/students').json()
        assert [row['username'] for row in roster['students']] == ['Ada']
        password = roster['default_password']
        assert student.post('/api/oj/login', json={'username': 'Ada', 'password': 'wrong'}).status_code == 401
        assert student.post('/api/oj/login', json={'username': 'ada', 'password': password}).status_code == 200
        assert student.get('/api/oj/sheets').json() == []
        assert student.get('/api/oj/teacher/students').status_code == 403
        identifier = roster['students'][0]['id']
        assert teacher.post(f'/api/oj/teacher/students/{identifier}/reset').status_code == 204
        assert student.get('/api/oj/sheets').status_code == 401
        assert student.post('/api/oj/login', json={'username': 'Ada', 'password': password}).status_code == 200
        assert student.get('/oj/teacher').status_code == 403
        assert teacher.get('/oj/teacher').status_code == 200

        def create(route, data):
            response = teacher.post('/api/oj/teacher/' + route, json=data)
            assert response.status_code == 201, response.text
            return response.json()['id']

        problem = dict(title='求和', statement='读入两个整数，输出其和。', sample_input='1 2\n', sample_output='3\n',
                       groups=[dict(input='12 24\n', output='36\n', score=10)])
        problem_id = create('problems', problem)
        other_id = create('problems', {**problem, 'title': '另一题'})
        first = create('sheets', dict(title='第一课', problem_ids=[other_id, problem_id], open=True))
        second = create('sheets', dict(title='第二课', problem_ids=[problem_id], open=True))
        assert [(row['id'], row['open']) for row in student.get('/api/oj/sheets').json()] == [(second, True), (first, False)]
        history = student.get(f'/api/oj/sheets/{first}').json()
        assert [row['id'] for row in history['problems']] == [other_id, problem_id]
        assert all(row['latest_submission'] is None for row in history['problems'])
        teacher_sheet = teacher.get(f'/api/oj/teacher/sheets/{first}').json()
        assert all('latest_submission' not in row for row in teacher_sheet['problems'])
        route = f'/api/oj/sheets/{first}/problems/{problem_id}'
        visible = student.get(route).json()
        assert visible['sample_output'] == '3\n' and not visible['open']
        assert 'groups' not in visible and visible['time_ms'] == 1000 and visible['memory_mb'] == 256
        assert student.get(f'/api/oj/sheets/{second}/problems/{other_id}').status_code == 404
        response = teacher.put(f'/api/oj/teacher/problems/{problem_id}', json={**problem, 'title': '整数求和'})
        assert response.status_code == 200 and response.json()['version'] == 2, response.text
        assert student.get(route).json()['title'] == '整数求和'
        assert teacher.post(f'/api/oj/teacher/sheets/{first}/open').status_code == 204
        assert student.get(route).json()['open']
        assert not student.get(f'/api/oj/sheets/{second}').json()['open']

        def submit(client, path, kind='judge'):
            return client.post(path + '/submissions', json=dict(source='int main() {}', kind=kind))

        def wait(client, path, status):
            for _ in range(100):
                row = client.get(path).json()
                if row['status'] == status:
                    return row
                time.sleep(.03)
            raise AssertionError(row)

        closed = f'/api/oj/sheets/{second}/problems/{problem_id}'
        assert submit(student, closed).status_code == 409
        assert submit(student, closed, 'sample').status_code == 409
        accepted = submit(student, route)
        assert accepted.status_code == 202, accepted.text
        submission_id = accepted.json()['id']
        submission = f'/api/oj/submissions/{submission_id}'
        assert wait(student, submission, 'running')['version'] == 2
        assert student.get(f'/api/oj/sheets/{first}').json()['problems'][1]['latest_submission'] == {
            'status': 'running', 'score': None, 'verdict': None, 'max_score': 10}
        assert submit(student, route, 'sample').status_code == 202
        assert submit(student, route, 'sample').status_code == 202
        assert submit(student, route).status_code == 429
        other_route = f'/api/oj/sheets/{first}/problems/{other_id}'
        assert submit(student, other_route, 'sample').status_code == 202
        invalid = student.post(other_route + '/submissions', json=dict(kind='judge', source='int main() {}', custom_input='7'))
        assert invalid.status_code == 422
        assert submit(student, other_route).status_code == 202
        assert teacher.put(f'/api/oj/teacher/problems/{problem_id}', json={**problem, 'title': '新版本'}).status_code == 200
        stale = student.post(route + '/submissions', json=dict(kind='sample', source='int main() {}', version=2))
        assert stale.status_code == 409 and stale.json()['code'] == 'problem_version_changed'
        assert teacher.get(f'/api/oj/teacher/problems/{problem_id}?version=2').json()['title'] == '整数求和'
        others = []
        for number in range(19):
            username = f'Student{number}'
            create('students', dict(username=username))
            learner = TestClient(app, client=('192.0.2.3', 12345))
            assert learner.post('/api/oj/login', json=dict(username=username, password=password)).status_code == 200
            others.append(learner)
        assert others[0].get(submission).status_code == 404
        assert all(row['latest_submission'] is None for row in others[0].get(f'/api/oj/sheets/{first}').json()['problems'])
        with ThreadPoolExecutor(max_workers=19) as pool:
            queued = list(pool.map(lambda learner: submit(learner, route), others))
        assert all(response.status_code == 202 for response in queued), [response.text for response in queued]
        assert all(learner.get(f"/api/oj/submissions/{response.json()['id']}").json()['status'] == 'queued'
                   for learner, response in zip(others, queued))
        gate.set()
        finished = wait(student, submission, 'finished')
        assert finished['version'] == 2 and finished['verdict'] == 'accepted' and finished['score'] == 10
        current = student.get(f'/api/oj/sheets/{first}').json()['problems'][1]
        assert current['version'] == 3 and current['latest_submission'] == {
            'status': 'finished', 'score': 10, 'verdict': 'accepted', 'max_score': 10}
        assert student.get(f'/api/oj/sheets/{second}').json()['problems'][0]['latest_submission'] is None
        for learner, response in zip(others, queued):
            record = wait(learner, f"/api/oj/submissions/{response.json()['id']}", 'finished')
            assert record['version'] == 3 and record['verdict'] == 'accepted'
        assert 'source' not in student.get('/api/oj/submissions').json()[0]
        assert teacher.get(f'/api/oj/teacher/submissions/{submission_id}').json()['source'] == 'int main() {}'
        assert len(teacher.get('/api/oj/teacher/submissions').json()) == 24
        assert teacher.post('/api/oj/teacher/students', json={'username': '小林'}).status_code == 201
        assert others[0].post('/api/oj/login', json={'username': '小林', 'password': password}).status_code == 200
        gate.clear()
        interrupted_problem = create('problems', {**problem, 'title': '重启恢复'})
        interrupted_sheet = create('sheets', dict(title='重启验证', problem_ids=[interrupted_problem], open=True))
        response = submit(student, f'/api/oj/sheets/{interrupted_sheet}/problems/{interrupted_problem}')
        assert response.status_code == 202, response.text
        interrupted = f"/api/oj/submissions/{response.json()['id']}"
        assert wait(student, interrupted, 'running')['title'] == '重启恢复'

    with OJStore(DB_PATH).connect(write=True) as connection:
        connection.execute('ALTER TABLE oj_submissions DROP COLUMN custom_input')
    gate.set()
    with TestClient(app, client=('127.0.0.1', 12345)):
        assert wait(student, interrupted, 'finished')['score'] == 10
        assert student.get(submission).json()['version'] == 2

    prep = data / 'prep'
    library = prep / 'OJ题目'
    library.mkdir(parents=True)
    config = data / 'config.json'
    config.write_text(json.dumps({'prep_dir': str(prep)}), 'utf-8')
    path = library / 'prepared.json'
    prepared = dict(schema_version=1, source_id='fixture/m1', title='自编题', statement='两数求和',
                    input_format='两个整数', output_format='一个整数', constraints='整数非负',
                    tags=['二分', '右边界'], time_ms=1000, memory_mb=256,
                    sample_cases=[dict(input='1 2\n', output='3\n')],
                    judge_cases=[dict(input='12 24\n', output='36\n', score=100)])
    path.write_text(json.dumps(prepared), 'utf-8')
    with TestClient(app, client=('127.0.0.1', 12345)) as teacher:
        prefix = '/api/oj/teacher'
        sync = prefix + '/problems/sync'
        assert teacher.post(sync).status_code == 403
        teacher.headers['X-Admin-Token'] = teacher.post('/api/admin/login', json={
            'username': 'teacher', 'password': 'test-secret'}).json()['token']
        assert teacher.post(sync).json()['added'] == 1
        imported, = [row for row in teacher.get(prefix + '/problems').json() if row.get('source_id') == 'fixture/m1']
        pid = imported['id']
        assert imported['version'] == 1 and imported['available'] and imported['max_score'] == 100
        assert teacher.post(sync).json()['unchanged'] == 1
        sheet_body = dict(title='备课题试点', open=True, problem_ids=[pid])
        old_sheet = teacher.post(prefix + '/sheets', json=sheet_body).json()['id']
        path.write_text(json.dumps({**prepared, 'title': '自编题新版'}), 'utf-8')
        assert teacher.post(sync).json()['updated'] == 1
        new_sheet = teacher.post(prefix + '/sheets', json=sheet_body).json()['id']
        for sid, version in ((old_sheet, 1), (new_sheet, 2)):
            visible = student.get(f'/api/oj/sheets/{sid}/problems/{pid}').json()
            assert visible['version'] == version and visible['sample_cases'] == prepared['sample_cases']
            assert visible['tags'] == prepared['tags'] and 'groups' not in visible and 'judge_cases' not in visible
        path.write_text('invalid', 'utf-8')
        assert len(teacher.post(sync).json()['issues']) == 1
        assert teacher.post(prefix + '/sheets', json=sheet_body).status_code == 422
        assert student.get(f'/api/oj/sheets/{old_sheet}/problems/{pid}').json()['version'] == 1


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        verify(Path(directory))
    print('PASS: OJ accounts, permissions, sheets, versions, cooldown and twenty-student queue')
