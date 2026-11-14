"""The media worker: an isolated child process that talks to the outside world.

The API process never fetches user-supplied URLs itself. For every task it starts
``python -m app.worker``, sends one JSON task on stdin and reads JSON events from
stdout. Before any third-party code is imported the worker locks itself down
(see :mod:`app.worker.guard`), and the parent can stop it - and any FFmpeg child -
at any moment by killing the process group, which is how cancellation and time
limits work.
"""
