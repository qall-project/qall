from qorus import task

from .intermediate_non_task_func import blob


@task()
async def hw():
    from pprint import pprint as pp

    pp("Hello World!")
    pp(blob())
    return 42
