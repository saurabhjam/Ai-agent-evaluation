import contextvars
import logging
from collections import defaultdict
import asyncio
from typing import Dict, List, Set

current_eval_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_eval_id", default="")

class EvalLogManager:
    def __init__(self):
        self.logs: Dict[str, List[dict]] = defaultdict(list)
        # Store tuple of (queue, loop)
        self.listeners: Dict[str, Set[tuple]] = defaultdict(set)
        
    def add_log(self, eval_id: str, log_entry: dict):
        self.logs[eval_id].append(log_entry)
        for queue, loop in self.listeners[eval_id]:
            # Thread-safe put
            def _put(q, entry):
                try:
                    q.put_nowait(entry)
                except asyncio.QueueFull:
                    pass
            loop.call_soon_threadsafe(_put, queue, log_entry)
                
    def get_logs(self, eval_id: str) -> List[dict]:
        return self.logs.get(eval_id, [])
        
    def subscribe(self, eval_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        self.listeners[eval_id].add((queue, loop))
        return queue
        
    def unsubscribe(self, eval_id: str, queue: asyncio.Queue):
        # We need to find the tuple matching the queue
        if eval_id in self.listeners:
            for item in list(self.listeners[eval_id]):
                if item[0] is queue:
                    self.listeners[eval_id].remove(item)

log_manager = EvalLogManager()

class EvalLogHandler(logging.Handler):
    def emit(self, record):
        eval_id = current_eval_id.get()
        if not eval_id:
            return
            
        log_entry = {
            "timestamp": self.formatter.formatTime(record, self.formatter.datefmt) if self.formatter else record.created,
            "level": record.levelname,
            "message": self.format(record),
            "logger": record.name
        }
        log_manager.add_log(eval_id, log_entry)

def setup_eval_logger():
    handler = EvalLogHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
