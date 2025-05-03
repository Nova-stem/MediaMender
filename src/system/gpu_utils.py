import platform
import subprocess
import urllib.request
import shutil
import logging
import os
from pathlib import Path

def is_nvidia_gpu_present() -> bool:
    return shutil.which("nvidia-smi") is not None

def is_cuda_runtime_available() -> bool:
    common_paths = [
        "cudart64_110.dll", "cudart64_101.dll",
        "/usr/local/cuda/lib64/libcudart.so",
        "/usr/local/cuda/lib/libcudart.dylib"
    ]
    for path in common_paths:
        if Path(path).exists():
            return True
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        return "CUDA Version" in result.stdout
    except Exception:
        return False

def is_torch_cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available() and torch.version.cuda is not None
    except ImportError:
        return False

def install_cuda_enabled_torch() -> bool:
    try:
        subprocess.run(
            ["pip", "install", "torch", "--index-url", "https://download.pytorch.org/whl/cu118"],
            check=True
        )
        return is_torch_cuda_available()
    except Exception as e:
        logging.error(f"❌ Torch/CUDA install failed: {e}")
        return False

def get_cuda_installer_url(cuda_version: str = "12.3.0") -> str:
    system = platform.system()
    arch = platform.machine()
    if system == "Windows" and arch in {"AMD64", "x86_64"}:
        return f"https://developer.download.nvidia.com/compute/cuda/{cuda_version}/network_installers/cuda_{cuda_version}_windows_network.exe"
    elif system == "Linux" and arch == "x86_64":
        return f"https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-repo-ubuntu2204_{cuda_version}-1_amd64.deb"
    else:
        raise RuntimeError(f"Unsupported system/architecture: {system} {arch}")

def download_cuda_installer(url: str, dest_path: Path, dry_run: bool = False) -> bool:
    try:
        if dry_run:
            logging.info(f"[DRY RUN] Would download CUDA installer from {url} to {dest_path}")
            return True
        urllib.request.urlretrieve(url, dest_path)
        return dest_path.exists()
    except Exception as e:
        logging.error(f"❌ CUDA installer download failed: {e}")
        return False

def run_cuda_installer(installer_path: Path, dry_run: bool = False) -> bool:
    try:
        if dry_run:
            logging.info(f"[DRY RUN] Would run CUDA installer: {installer_path}")
            return True

        if platform.system() == "Windows":
            os.startfile(installer_path, "runas")
        else:
            subprocess.run(["chmod", "+x", str(installer_path)], check=True)
            subprocess.run(["sudo", str(installer_path)], check=True)
        return True
    except Exception as e:
        logging.error(f"❌ CUDA installer launch failed: {e}")
        return False
