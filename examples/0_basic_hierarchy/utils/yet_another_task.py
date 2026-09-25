from qorus import task


@task()
def yet_another_task():
    print("yet another task")
    return "yet another task" * 2
