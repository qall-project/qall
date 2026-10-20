from pathlib import Path

from qall import task


# This example needs the prior setup of a dataloader named 'local_spec' binding a local directory containing a README.md file to -> 'local_directory'
# i.e.: qall dataloader add local_spec file://<path_to_qall_directory>/ local_directory

@task(entrypoint=True, dataloaders=["local_spec"])
def main():

    base = Path("dataloaders") / "local_directory"
    print(tuple(base.glob("*.md")))

    readme = base / "README.md"
    text = readme.read_text()

    return text
