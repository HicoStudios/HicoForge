"""
Job queue + worker thread.

Owns one FIFO queue and one worker thread. Each Job is a (slot_index,
tool_id, source_path). The worker pops jobs, builds the processor on
demand, runs `process_one`, and emits Qt-friendly callbacks for the UI:

  on_started(slot_index, source_path)
  on_progress(slot_index, source_path, message)
  on_finished(slot_index, source_path, output_path)
  on_error(slot_index, source_path, error_message)
  on_queue_changed(pending_count, active_slots)

The MainWindow connects these to update tile badges and status footer.
"""

import threading
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List

from PySide6.QtCore import QObject, Signal


@dataclass
class Job:
    slot_index: int
    tool_id: str
    source_path: Path


class JobQueueSignals(QObject):
    started = Signal(int, str)             # slot, source path
    progress = Signal(int, str, str)       # slot, source path, message
    finished = Signal(int, str, str)       # slot, source path, output path
    error = Signal(int, str, str)          # slot, source path, error
    queueChanged = Signal(int, int)        # pending count, total processed since start
    statusMessage = Signal(str)            # opaque status messages from cache, etc.


class JobQueue:
    def __init__(self,
                 build_processor_fn: Callable[..., object],
                 ):
        """
        build_processor_fn(tool_id, slot_index) -> BaseProcessor
            Resolves a tool_id to a freshly-built processor instance,
            using any per-slot setting overrides. slot_index may be a
            real slot (0..11) or a synthetic All-mode pseudo-slot.
            Raises UnsupportedProcessorError if backend isn't ready yet.
        """
        self.signals = JobQueueSignals()
        self._build_processor = build_processor_fn
        self._q: queue.Queue[Optional[Job]] = queue.Queue()
        self._stop = threading.Event()
        self._processed_count = 0

        self._worker = threading.Thread(target=self._run, daemon=True, name="HicoForge-worker")
        self._worker.start()

    def enqueue(self, slot_index: int, tool_id: str, source: Path):
        self._q.put(Job(slot_index, tool_id, source))
        self.signals.queueChanged.emit(self._q.qsize(), self._processed_count)

    def enqueue_many(self, slot_index: int, tool_id: str, sources: list[Path]):
        for s in sources:
            self._q.put(Job(slot_index, tool_id, s))
        self.signals.queueChanged.emit(self._q.qsize(), self._processed_count)

    def pending_count(self) -> int:
        return self._q.qsize()

    def snapshot_pending(self) -> List[dict]:
        """Return all currently-queued jobs as plain dicts (for persistence)."""
        out: List[dict] = []
        # queue.Queue has no safe iterator; pop everything into a list and put
        # back in order. The worker thread can also pull jobs concurrently, so
        # this is a best-effort snapshot — we accept losing jobs the worker has
        # already pulled.
        with self._q.mutex:
            for job in list(self._q.queue):
                if job is None:
                    continue
                out.append({
                    "slot_index": job.slot_index,
                    "tool_id": job.tool_id,
                    "source_path": str(job.source_path),
                })
        return out

    def restore_pending(self, items: List[dict]) -> int:
        """Re-enqueue jobs from a previous session. Returns count restored."""
        n = 0
        for d in items:
            try:
                src = Path(d["source_path"])
                if not src.exists():
                    continue  # skip jobs whose source file is gone
                self._q.put(Job(
                    slot_index=int(d.get("slot_index", -1)),
                    tool_id=str(d.get("tool_id", "")),
                    source_path=src,
                ))
                n += 1
            except Exception:
                continue
        if n:
            self.signals.queueChanged.emit(self._q.qsize(), self._processed_count)
        return n

    def shutdown(self):
        self._stop.set()
        self._q.put(None)  # wake worker
        try:
            self._worker.join(timeout=3)
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None or self._stop.is_set():
                break

            self.signals.started.emit(job.slot_index, str(job.source_path))
            try:
                processor = self._build_processor(job.tool_id, job.slot_index)
            except Exception as e:
                self.signals.error.emit(job.slot_index, str(job.source_path), str(e))
                self.signals.queueChanged.emit(self._q.qsize(), self._processed_count)
                continue

            try:
                def progress_cb(msg: str, _slot=job.slot_index, _src=str(job.source_path)):
                    self.signals.progress.emit(_slot, _src, msg)

                out_path = processor.process_one(job.source_path, progress=progress_cb)
                self._processed_count += 1
                self.signals.finished.emit(job.slot_index, str(job.source_path), str(out_path))
            except Exception as e:
                self.signals.error.emit(job.slot_index, str(job.source_path), str(e))
            finally:
                self.signals.queueChanged.emit(self._q.qsize(), self._processed_count)
