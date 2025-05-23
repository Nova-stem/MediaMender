#src/gpu_utils.py
#23 May 2025

import asyncio
import platform
#import subprocess
#import urllib.request
import shutil
import logging
import os
from pathlib import Path

from src.system.async_utils import stream_download, stream_subprocess, run_subprocess_capture, make_executable


def is_nvidia_gpu_present() -> bool:
    return shutil.which("nvidia-smi") is not None

async def is_cuda_runtime_available(logger=None) -> bool:
    common_paths = [
        "cudart64_110.dll", "cudart64_101.dll",
        "/usr/local/cuda/lib64/libcudart.so",
        "/usr/local/cuda/lib/libcudart.dylib"
    ]

    for path in common_paths:
        if Path(path).exists():
            return True

    try:
        output = await run_subprocess_capture(["nvidia-smi"], logger=logger)
        return "CUDA Version" in output
    except Exception as e:
        logger.error(f"Command failed: nvidia-smi - {e}")
        return False

def is_torch_cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available() and torch.version.cuda is not None
    except ImportError:
        return False

def install_cuda_enabled_torch(dry_run: bool = False, logger=None) -> bool:
    try:
        logger.info(f"Downloading CUDA installer via pip to https://download.pytorch.org/whl/cu118")
        if dry_run:
            return True
        asyncio.run(install_torch(logger))
        return is_torch_cuda_available()
    except Exception as e:
        logger.error(f"Torch/CUDA install failed: {e}")
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

def download_cuda_installer(url: str, dest_path: Path, dry_run: bool = False, logger=None) -> bool:
    logger = logger or logging.getLogger(__name__)
    logger.info(f"Downloading CUDA installer from {url} to {dest_path}")
    if dry_run:
        return True
    success = stream_download(url, dest_path, logger=logger)
    if not success:
        logger.error(f"CUDA installer download failed: {url}")
        return False
    return True

def run_cuda_installer(installer_path: Path, dry_run: bool = False, logger=None) -> bool:
    logger = logger or logging.getLogger(__name__)
    try:
        logger.info(f"Running CUDA installer: {installer_path}")
        if dry_run:
            return True
        if platform.system() == "Windows":
            os.startfile(installer_path, "runas")
        else:
            asyncio.run(make_executable(installer_path, logger))
            asyncio.run(run_cuda_setup(installer_path, logger))
        return True
    except Exception as e:
        logger.error(f"CUDA installer launch failed: {e}")
        return False

async def install_torch(logger):
    def log_output(line): logger.info(f"[TORCH INSTALL] {line}")
    return await stream_subprocess(["pip", "install", "torch", "--extra-index-url", "https://download.pytorch.org/whl/cu118"],
                                   on_output=log_output,
                                   logger=logger)

async def run_cuda_setup(installer_path, logger):
    def log_output(line): logger.info(f"[CUDA INSTALL] {line}")
    return await stream_subprocess(["sudo", str(installer_path)],
                                   on_output=log_output,
                                   logger=logger)

#async def set_executable(path, logger):
#    return await stream_subprocess(["chmod", "+x", str(path)], logger=logger)

async def is_cuda_available(logger):
    output = await run_subprocess_capture(["nvidia-smi"], logger=logger)
    return "CUDA Version" in output