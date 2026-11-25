"""One background evaluator keeps classroom HTTP work independent of submissions."""
import asyncio
import logging
import sqlite3
from threading import Event, Thread


log = logging.getLogger(__name__)


class OJQueue:
    def __init__(self, store, runner):
        self.store = store
        self.runner = runner
        self.wake = Event()
        self.stop = Event()
        self.thread = None

    def start(self):
        self.stop.clear()
        recover = getattr(self.runner, 'recover', None)
        if recover is not None:
            recover()
        self.store.recover_queue()
        self.thread = Thread(target=self.work, name='oj-queue', daemon=True)
        self.thread.start()

    async def shutdown(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            await asyncio.to_thread(self.thread.join)

    def work(self):
        while not self.stop.is_set():
            self.wake.clear()
            try:
                task = self.store.claim()
                if task is None:
                    self.wake.wait(2)
                    continue
                try:
                    result = self.runner.evaluate(task, self.stop)
                except Exception:
                    log.exception('OJ evaluation failed for submission %s', task['id'])
                    result = dict(verdict='judge_error', score=0)
                if result is None:
                    continue
                while not self.stop.is_set():
                    try:
                        self.store.complete(task['id'], result)
                        break
                    except sqlite3.OperationalError:
                        log.exception('Could not save OJ result')
                        self.stop.wait(1)
            except sqlite3.OperationalError:
                log.exception('Could not claim OJ work')
                self.stop.wait(1)
