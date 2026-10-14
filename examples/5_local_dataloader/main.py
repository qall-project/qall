from pathlib import Path

from qall import task


@task(entrypoint=True, dataloaders=["local_spec"])
def main():

    base = Path("dataloaders") / "spec_file"
    print(tuple(base.glob("*.md")))

    readme = base / "README.md"
    text = readme.read_text()

    return text
