import cv2
import itertools
import numpy as np
from pathlib import Path
from PIL import Image

from qall import task, workflow


def write_img_array(arr: np.ndarray, filepath: Path):
    import io

    img = Image.fromarray(arr)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    filepath.write_bytes(buffer.getvalue())


@task(dataloaders=["scw_s3"])
def download_images() -> list[str]:

    remote_path = Path("dataloaders") / "bucket" / "SIDD"
    local_path = Path("unifs") / "noisy_images"
    local_path.mkdir(exist_ok=True)

    extensions = (".jpeg", ".png", ".webp")
    files = list(
        itertools.chain.from_iterable(
            remote_path.glob("*" + extension) for extension in extensions
        )
    )

    files = tuple(remote_path.glob("*"))
    print(f"Files: {files}")

    images_files = list()
    for idx, file in enumerate(files):
        name = f"{idx}_noisy_image.webp"
        path = local_path / name
        raw_image = file.read_bytes()
        path.write_bytes(raw_image)
        images_files.append(str(path.absolute()))

    return images_files


@task()
def process_images(images_files: list[str]) -> list[str]:

    print(
        f"Files found on unifs ({Path(images_files[0]).parent}) : {tuple(Path(images_files[0]).parent.glob("*"))}"
    )

    processed_path = Path("unifs") / "processed_images"
    processed_path.mkdir(exist_ok=True)

    processed_images_files = list()
    for idx, file in enumerate(images_files):
        image = np.array(Image.open(file))
        # Prepare grayscale version for edge detection
        if len(image.shape) == 3:
            # Assuming BGR color space, standard for OpenCV
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Edge detection to get a mask of high gradients
        # Canny computes gradients and applies thresholding to find solid edges
        edge_mask = cv2.Canny(gray, threshold1=50, threshold2=150)
        edge_file = processed_path / f"{idx}_edge_mask.png"
        write_img_array(edge_mask, edge_file)

        # Create a boolean mask (True for edges, False for low-gradient areas)
        mask_bool = edge_mask > 0

        mask_file = processed_path / f"{idx}_mask_bool.png"
        write_img_array(mask_bool, mask_file)

        # If the original image has 3 channels, expand mask to (H, W, 1) for broadcasting
        if len(image.shape) == 3:
            mask_bool = mask_bool[:, :, np.newaxis]

        # Create a blurred copy to remove noise in low-gradient areas
        blurred = cv2.GaussianBlur(image, (11, 11), 0)

        # Combine the images
        final_img = np.where(mask_bool, image, blurred)

        # Save the image
        final_img = Image.fromarray(final_img)
        name = f"{idx}_processed_image.webp"
        path = processed_path / name
        final_img.save(path, "webp")
        processed_images_files.append(str(path.absolute()))

    return processed_images_files


@task(dataloaders=["scw_s3"])
def upload_images(processed_images_files: list[str]) -> int:

    path = Path("dataloaders") / "bucket" / "processed_images"
    path.mkdir(exist_ok=True)

    counter = 0
    for idx, file in enumerate(processed_images_files):
        raw_image = Path(file).read_bytes()
        remote_image_path = path / f"{idx}_processed_image.webp"
        remote_image_path.write_bytes(raw_image)
        counter += 1

    return counter


@workflow()
def main():
    # A 3 sub-tasks workflow that:
    # (i) loads images from a remote object storage
    # (ii) performs some computer vision operations on them
    # (iii) uploads them back on a neighboring directory

    images = download_images()
    processed_images = process_images(images)
    nb_processed_images = upload_images(processed_images)

    assert len(images) == nb_processed_images

    print("Images successfully processed! Check you storage for results.")
