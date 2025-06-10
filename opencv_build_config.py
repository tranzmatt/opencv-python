# opencv_build_config.py
# Configuration file for OpenCV CUDA build

import os
import platform

# Build configuration flags
BUILD_CONFIG = {
    # Core build options
    "ENABLE_CONTRIB": True,
    "ENABLE_HEADLESS": False,
    "ENABLE_ROLLING": False,
    "ENABLE_CUDA": True,
    "ENABLE_JAVA": True,
    
    # CUDA configuration
    "CUDA_ROOT": "/usr/local/cuda-12.8",
    "CUDA_VERSION": "12.8",
    "CUDA_ARCH_BIN": "8.0,8.6,8.7,8.9,9.0",  # Adjust based on your GPU
    "CUDA_FAST_MATH": True,
    
    # Performance optimizations
    "ENABLE_TBB": True,
    "ENABLE_OPENMP": True,
    "ENABLE_IPP": False,  # Intel Performance Primitives
    
    # GUI and video I/O
    "WITH_QT": 6,  # Qt version (5 or 6)
    "WITH_GTK": False,
    "WITH_FFMPEG": True,
    "WITH_GSTREAMER": True,
    
    # Image formats
    "WITH_JPEG": True,
    "WITH_PNG": True,
    "WITH_TIFF": True,
    "WITH_OPENEXR": True,
    "WITH_WEBP": True,
    
    # Additional libraries
    "WITH_EIGEN": True,
    "WITH_LAPACK": True,
    "WITH_VTK": True,
    "WITH_GDAL": True,
    "WITH_GDCM": True,
    
    # OpenCL support
    "WITH_OPENCL": True,
    "OPENCL_INCLUDE_DIR": "/usr/include/CL/",
    
    # Build type
    "CMAKE_BUILD_TYPE": "Release",
    "BUILD_EXAMPLES": False,
    "BUILD_TESTS": False,
    "BUILD_PERF_TESTS": False,
    "BUILD_DOCS": False,
}

# System-specific overrides
if platform.system() == "Windows":
    BUILD_CONFIG.update({
        "WITH_MSMF": True,
        "WITH_DSHOW": True,
    })
elif platform.system() == "Darwin":  # macOS
    BUILD_CONFIG.update({
        "WITH_AVFOUNDATION": True,
        "WITH_QUICKTIME": True,
    })
elif platform.system() == "Linux":
    BUILD_CONFIG.update({
        "WITH_V4L": True,
        "WITH_GPHOTO2": True,
        "WITH_1394": False,  # Firewire support
    })

# Environment variable overrides
def apply_env_overrides():
    """Apply configuration overrides from environment variables"""
    for key, default_value in BUILD_CONFIG.items():
        env_key = f"OPENCV_{key}"
        if env_key in os.environ:
            env_value = os.environ[env_key]
            if isinstance(default_value, bool):
                BUILD_CONFIG[key] = env_value.lower() in ('true', '1', 'yes', 'on')
            elif isinstance(default_value, int):
                try:
                    BUILD_CONFIG[key] = int(env_value)
                except ValueError:
                    pass
            else:
                BUILD_CONFIG[key] = env_value

def get_cmake_args():
    """Generate CMAKE arguments from configuration"""
    apply_env_overrides()
    
    args = []
    
    # Convert boolean flags
    for key, value in BUILD_CONFIG.items():
        if key.startswith("WITH_") or key.startswith("BUILD_") or key.startswith("ENABLE_"):
            cmake_key = key if key.startswith(("WITH_", "BUILD_")) else key.replace("ENABLE_", "WITH_")
            if isinstance(value, bool):
                args.append(f"-D{cmake_key}={'ON' if value else 'OFF'}")
            elif value is not None:
                args.append(f"-D{cmake_key}={value}")
    
    # Add specific configuration
    if BUILD_CONFIG["ENABLE_CUDA"]:
        cuda_root = BUILD_CONFIG["CUDA_ROOT"]
        args.extend([
            f"-DCUDA_TOOLKIT_ROOT_DIR={cuda_root}",
            f"-DCUDA_NVCC_EXECUTABLE={cuda_root}/bin/nvcc",
            f"-DCMAKE_CUDA_COMPILER={cuda_root}/bin/nvcc",
            f"-DCUDA_ARCH_BIN={BUILD_CONFIG['CUDA_ARCH_BIN']}",
            f"-DCUDA_FAST_MATH={'ON' if BUILD_CONFIG['CUDA_FAST_MATH'] else 'OFF'}",
            "-DOPENCV_DNN_CUDA=ON",
        ])
    
    args.append(f"-DCMAKE_BUILD_TYPE={BUILD_CONFIG['CMAKE_BUILD_TYPE']}")
    
    return args

def print_configuration():
    """Print current build configuration"""
    apply_env_overrides()
    print("OpenCV Build Configuration:")
    print("=" * 40)
    for key, value in sorted(BUILD_CONFIG.items()):
        print(f"{key:30} = {value}")
    print("=" * 40)
    print("\nGenerated CMAKE args:")
    for arg in get_cmake_args():
        print(f"  {arg}")

if __name__ == "__main__":
    print_configuration()
