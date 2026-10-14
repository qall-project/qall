import base64
from pathlib import Path
import requests

from qall import workflow


@workflow(dataloaders=["local_minio"])
def main():

    base_path = Path("local_minio")

    try:
        base_path.glob("*")
    except Exception as e:
        print(
            "Could not contact datloader named 'local_minio'. Launch a minio instance and ensure proper setup through qall CLI (qall add local_minio [...])."
        )
        raise e

    response = requests.get(
        "https://www-uploads.scaleway.com/Quantum_as_a_service_Illustration_Keyvisual_d2bb03f116.png"
    )
    raw_image = response.content
    b64_image = base64.b64encode(raw_image)

    (base_path / "images" / "awesomeness.webp").write_bytes(raw_image)
    print("An eternity later...")

    dataloaded_b64_image = base64.b64encode(
        (base_path / "images" / "awesomeness.webp").read_bytes()
    )
    assert (
        dataloaded_b64_image == b64_image
    ), "The uploaded image is different than the original image."
    print("Image successfully processed!")

    return dataloaded_b64_image
