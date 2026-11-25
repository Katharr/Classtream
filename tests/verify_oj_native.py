"""Real Windows C++17 evaluation through HTTP using synthetic source and data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-lan'))


def verify(data, scratch):
    os.environ['CLASSTREAM_DATA'] = str(data)
    from app import database
    from compat import create_application
    from fastapi.testclient import TestClient

    database.init_db()
    database.create_admin('teacher', 'test-secret', 'Teacher')
    marker = data / 'private.txt'
    marker.write_text('fixture teacher data', 'utf-8')
    leftover = scratch / 'classstream-oj-crash-fixture'
    leftover.mkdir(parents=True)
    (leftover / 'main.cpp').write_text('int main(){}', 'utf-8')
    app = create_application('http://127.0.0.1')
    with TestClient(app, client=('127.0.0.1', 12000)) as teacher:
        assert not leftover.exists()
        teacher.headers['x-admin-token'] = teacher.post('/api/admin/login', json={
            'username': 'teacher', 'password': 'test-secret'}).json()['token']
        teacher_api = '/api/oj/teacher'
        password = teacher.get(teacher_api + '/students').json()['default_password']

        def create(path, payload):
            response = teacher.post(teacher_api + path, json=payload)
            assert response.status_code == 201, response.text
            return response.json()['id']

        tests = [
            ('sample', 'accepted', 0, '#include <iostream>\nint main(){std::cout << "3  \\n";}', 256),
            ('judge', 'partial', 10, '#include <iostream>\nint main(){std::cout << 3;}', 256),
            ('judge', 'accepted', 100, '#include <iostream>\nint main(){auto [a,b]=std::pair{0,0}; std::cin>>a>>b; std::cout<<a+b<<" \\n";}', 256),
            ('judge', 'wrong_answer', 0, 'int main(){}', 256),
            ('judge', 'compile_error', 0, 'int main( {}', 256),
            ('judge', 'runtime_error', 0, 'int main(){return 3;}', 256),
            ('judge', 'timeout', 0, 'int main(){volatile unsigned value=0; for(;;) ++value;}', 256),
            ('judge', 'memory_limit', 0, '#include <windows.h>\nint main(){return VirtualAlloc(nullptr, 80<<20, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE) ? 0 : 1;}', 32),
            ('sample', 'accepted', 0, '#include <fstream>\n#include <iostream>\nint main(){std::cout << (std::ifstream(' + json.dumps(marker.as_posix()) + ') ? "readable" : "3");}', 256),
            ('judge', 'compile_error', 0, '#include ' + json.dumps(marker.as_posix()) + '\nint main(){}', 256),
            ('sample', 'accepted', 0, '#include <iostream>\nint main(){std::cout << "3\\n\\n";}', 256),
            ('sample', 'wrong_answer', 0, '#include <iostream>\nint main(){std::cout << "3\\n\\n\\n";}', 256),
        ]
        problems = [create('/problems', dict(title='求和', statement='两数求和', sample_input='1 2\n',
                    sample_output='3\n', time_ms=500, memory_mb=memory,
                    groups=[dict(input='1 2\n', output='3\n', score=10), dict(input='200 900\n', output='1100\n', score=100)]))
                    for _, _, _, _, memory in tests]
        sheet_id = create('/sheets', dict(title='课堂练习', open=True, problem_ids=problems))
        create('/students', {'username': 'Ada'})
        client = TestClient(app, client=('192.0.2.20', 12000))
        assert client.post('/api/oj/login', json=dict(username='Ada', password=password)).status_code == 200
        for problem, (kind, verdict, points, source, _) in zip(problems, tests):
            reply = client.post(f'/api/oj/sheets/{sheet_id}/problems/{problem}/submissions', json=dict(kind=kind, source=source))
            assert reply.status_code == 202, reply.text
            route = f"/api/oj/submissions/{reply.json()['id']}"
            deadline = time.monotonic() + 28
            while time.monotonic() < deadline:
                result = client.get(route).json()
                if result['status'] == 'finished':
                    break
                time.sleep(.05)
            assert result['verdict'] == verdict and result['score'] == points, result
            assert not list(scratch.iterdir()), list(scratch.iterdir())
        assert len(client.get('/api/oj/submissions').json()) == len(tests)


if __name__ == '__main__':
    os.environ.setdefault('CLASSTREAM_HOME', str(ROOT.parent / 'teacher'))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        verify(root, root / 'oj-work')
    print('PASS: OJ C++17, partial/full score, compile/runtime/time/memory verdicts, output and cleanup')
