"""Process execution interlock; never reads or changes persisted job settings."""
import os


def disabled():
    return os.environ.get('PQM_DISABLE_BACKGROUND_JOBS', '').strip().lower() in {
        '1', 'true', 'yes', 'on'}
