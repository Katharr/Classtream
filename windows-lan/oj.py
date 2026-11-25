"""Standalone teacher and student OJ routes."""
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi import Path as RoutePath, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from oj_store import OJError


ASSETS = Path(__file__).parent
COOKIE = 'classtream_oj'
SESSION_SECONDS = 12 * 60 * 60
Username = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r'^[\p{L}\p{N}_.-]{1,32}$')]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
CaseText = Annotated[str, StringConstraints(max_length=65_536)]
PositiveID = Annotated[int, Field(gt=0, le=2**63 - 1)]
RouteID = Annotated[int, RoutePath(gt=0, le=2**63 - 1)]
QueryID = Annotated[int, Query(gt=0, le=2**63 - 1)]
NO_CACHE = {'Cache-Control': 'no-store'}


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class StudentForm(Payload):
    username: Username


class LoginForm(StudentForm):
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class GroupForm(Payload):
    input: CaseText
    output: CaseText
    score: Annotated[int, Field(ge=1, le=10000)]


class ProblemForm(Payload):
    title: Title
    statement: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32768)]
    sample_input: CaseText = ''
    sample_output: CaseText = ''
    time_ms: Annotated[int, Field(ge=50, le=10000)] = 1000
    memory_mb: Annotated[int, Field(ge=16, le=512)] = 256
    groups: Annotated[list[GroupForm], Field(min_length=1, max_length=20)]


class SheetForm(Payload):
    title: Title
    problem_ids: Annotated[list[PositiveID], Field(max_length=100)]
    open: bool = False


class SubmissionForm(Payload):
    source: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    kind: Literal['sample', 'judge'] = 'judge'
    version: PositiveID | None = None


def body(model, limit):
    async def parse(request: Request):
        if request.headers.get('content-type', '').split(';', 1)[0].lower() != 'application/json':
            raise OJError(415, '请求必须为 JSON')
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise OJError(413, '内容超出大小限制')
            data.extend(chunk)
        try:
            return model.model_validate_json(data)
        except ValidationError as exc:
            field = exc.errors(include_url=False, include_input=False)[0]['loc']
            location = '.'.join(map(str, field))
            raise OJError(422, f'请检查字段 {location}' if location else '表单格式不正确') from exc

    return parse


def install_oj(application, store, queue, local_teacher, is_local):
    student = APIRouter(prefix='/api/oj')

    def require_teacher(request: Request):
        if not local_teacher(request):
            raise OJError(403, '请在教师机登录教师账号')

    teacher = APIRouter(prefix='/api/oj/teacher', dependencies=[Depends(require_teacher)])

    @application.exception_handler(OJError)
    async def oj_error(_, exception):
        content = {'detail': str(exception)}
        if exception.code:
            content['code'] = exception.code
        return JSONResponse(content, status_code=exception.status, headers=NO_CACHE)

    @application.get('/oj')
    @application.get('/oj/teacher')
    def page(request: Request):
        if request.url.path.endswith('/teacher') and not is_local(request):
            raise OJError(403, '请在教师机打开 OJ 管理')
        return FileResponse(ASSETS / 'oj.html', headers={**NO_CACHE,
                            'Content-Security-Policy': "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"})

    @application.get('/oj/assets/{name}')
    def asset(name: str):
        if name not in ('oj.css', 'oj.js'):
            raise OJError(404, '资源不存在')
        return FileResponse(ASSETS / name, headers=NO_CACHE)

    def session(request: Request):
        return store.identity(request.cookies.get(COOKIE, ''))

    @student.post('/login')
    def login(request: Request, form=Depends(body(LoginForm, 2048))):
        token, identity = store.login(form.username, form.password, SESSION_SECONDS)
        response = JSONResponse(identity, headers=NO_CACHE)
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, path='/api/oj',
                            secure=request.url.scheme == 'https', httponly=True, samesite='strict')
        return response

    @student.post('/logout')
    def logout(request: Request):
        store.logout(request.cookies.get(COOKIE, ''))
        response = Response(status_code=204, headers=NO_CACHE)
        response.delete_cookie(COOKIE, path='/api/oj', httponly=True, samesite='strict')
        return response

    @student.get('/me')
    def me(identity=Depends(session)):
        return JSONResponse(identity, headers=NO_CACHE)

    @student.get('/sheets')
    def sheets(_=Depends(session)):
        return JSONResponse(store.sheets(), headers=NO_CACHE)

    @student.get('/sheets/{sheet_id}')
    def sheet(sheet_id: RouteID, _=Depends(session)):
        return JSONResponse(store.sheet(sheet_id), headers=NO_CACHE)

    @student.get('/sheets/{sheet_id}/problems/{problem_id}')
    def sheet_problem(sheet_id: RouteID, problem_id: RouteID, _=Depends(session)):
        return JSONResponse(store.sheet_problem(sheet_id, problem_id), headers=NO_CACHE)

    @student.post('/sheets/{sheet_id}/problems/{problem_id}/submissions')
    def submit(sheet_id: RouteID, problem_id: RouteID, identity=Depends(session),
               form=Depends(body(SubmissionForm, 524_288))):
        if not form.source.strip() or '\x00' in form.source:
            raise OJError(422, '请输入 C++17 源码')
        result = store.submit(identity['id'], sheet_id, problem_id, form.kind, form.source, form.version)
        queue.wake.set()
        return JSONResponse(result, status_code=202, headers=NO_CACHE)

    @student.get('/submissions')
    def own_submissions(before: QueryID = None, identity=Depends(session)):
        return JSONResponse(store.submissions(identity['id'], before), headers=NO_CACHE)

    @student.get('/submissions/{submission_id}')
    def own_submission(submission_id: RouteID, identity=Depends(session)):
        return JSONResponse(store.submission(submission_id, identity['id']), headers=NO_CACHE)

    @teacher.get('/students')
    def students():
        return JSONResponse(store.students(), headers=NO_CACHE)

    @teacher.post('/students')
    def add_student(form=Depends(body(StudentForm, 1024))):
        return JSONResponse(store.add_student(form.username), status_code=201, headers=NO_CACHE)

    @teacher.post('/students/{student_id}/reset')
    def reset_student(student_id: RouteID):
        store.reset_student(student_id)
        return Response(status_code=204, headers=NO_CACHE)

    @teacher.get('/problems')
    def problems():
        return JSONResponse(store.problems(), headers=NO_CACHE)

    @teacher.get('/problems/{problem_id}')
    def problem(problem_id: RouteID, version: QueryID = None):
        return JSONResponse(store.problem(problem_id, version), headers=NO_CACHE)

    @teacher.post('/problems')
    def create_problem(form=Depends(body(ProblemForm, 4_194_304))):
        return JSONResponse(store.save_problem(form.model_dump()), status_code=201, headers=NO_CACHE)

    @teacher.put('/problems/{problem_id}')
    def update_problem(problem_id: RouteID, form=Depends(body(ProblemForm, 4_194_304))):
        return JSONResponse(store.save_problem(form.model_dump(), problem_id), headers=NO_CACHE)

    @teacher.get('/sheets')
    def teacher_sheets():
        return JSONResponse(store.sheets(), headers=NO_CACHE)

    @teacher.get('/sheets/{sheet_id}')
    def teacher_sheet(sheet_id: RouteID):
        return JSONResponse(store.sheet(sheet_id), headers=NO_CACHE)

    @teacher.post('/sheets')
    def create_sheet(form=Depends(body(SheetForm, 8192))):
        return JSONResponse(store.save_sheet(form.model_dump()), status_code=201, headers=NO_CACHE)

    @teacher.put('/sheets/{sheet_id}')
    def update_sheet(sheet_id: RouteID, form=Depends(body(SheetForm, 8192))):
        return JSONResponse(store.save_sheet(form.model_dump(), sheet_id), headers=NO_CACHE)

    @teacher.post('/sheets/{sheet_id}/open')
    def open_sheet(sheet_id: RouteID):
        store.open_sheet(sheet_id)
        return Response(status_code=204, headers=NO_CACHE)

    @teacher.get('/submissions')
    def all_submissions(before: QueryID = None):
        return JSONResponse(store.submissions(before=before), headers=NO_CACHE)

    @teacher.get('/submissions/{submission_id}')
    def teacher_submission(submission_id: RouteID):
        return JSONResponse(store.submission(submission_id), headers=NO_CACHE)

    application.include_router(teacher)
    application.include_router(student)
