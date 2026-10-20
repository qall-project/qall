import base64
from pathlib import Path
import requests

from qall import workflow


# This example needs the prior setup of a dataloader named 'local_minio' binding to -> 'minio_path'
# i.e.: qall dataloader add local_minio s3://<your_bucket> minio_path/ --key=minioadmin --secret=minioadmin --endpoint_url=http://127.0.0.1:9000
# Above are default credentials when running a local minio instance, change them as needed.

@workflow(dataloaders=["local_minio"])
def main():

    base_path = Path("dataloaders") / "minio_path"

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
