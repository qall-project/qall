import asyncio
import random

from qorus import task, workflow

from utils.hw_task import hw


@task()
def add(x, y):
    return x + y


@task(entrypoint=False)
def mul(x, y):
    tmp = 0
    for _ in range(x):
        tmp = add(tmp, y)
    return tmp


def divide(x, y):
    return mul(x, 1 / y)


@workflow()
async def main():
    a = await hw()
    b = add(a, 3)
    n = random.randint(1, 2)
    for _ in range(n):
        c = divide(2, b)
    return c


if __name__ == "__main__":
    print(asyncio.run(main()))
