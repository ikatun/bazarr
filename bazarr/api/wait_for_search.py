"""Fail-closed completion acknowledgement for external subtitle orchestration."""
import time

from app.jobs_queue import jobs_queue


def wait_for_search(job_id, timeout=540):
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        return {'error': 'Search is already queued; retry after completion'}, 409
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = jobs_queue.get_job_status(job_id)
        if status == 'completed':
            result = jobs_queue.get_job_returned_value(job_id)
            if isinstance(result, tuple) and len(result) == 2 and result[1] == 204:
                return {'completed': True}, 200
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
                return result
            return {'error': 'Search completed without a valid result'}, 503
        if status not in ('pending', 'running'):
            return {'error': 'Search failed or completion evidence is unavailable'}, 503
        time.sleep(0.25)
    return {'error': 'Search completion timed out'}, 503
