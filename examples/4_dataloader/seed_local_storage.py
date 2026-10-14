"""
Seeds a local file:// object storage used by the dataloader example.

Creates /tmp/qall-dataloader-demo with:
  mnist/table.csv      a small CSV dataset
  mnist/notes.txt      a text note
  pics/september/...   a few fake PNG photo blobs
"""

from pathlib import Path

DEMO_ROOT = Path("/tmp/qall-dataloader-demo")


def main():
    mnist = DEMO_ROOT / "mnist"
    pics = DEMO_ROOT / "pics"
    mnist.mkdir(parents=True, exist_ok=True)
    (pics / "september" / "japan").mkdir(parents=True, exist_ok=True)
    (pics / "august" / "france").mkdir(parents=True, exist_ok=True)

    (mnist / "table.csv").write_text("x,y\n1,2\n3,4\n5,6\n")
    (mnist / "notes.txt").write_text("hello dataloader\n")

    (pics / "september" / "japan" / "fuji.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (pics / "august" / "france" / "paris.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    print(f"Seeded dataloader demo storage at {DEMO_ROOT}")


if __name__ == "__main__":
    main()
