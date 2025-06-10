#!/bin/bash
# build_opencv_cuda.sh
# Script to build OpenCV with CUDA support

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration
CUDA_VERSION=${CUDA_VERSION:-"12.8"}
CUDA_ROOT=${CUDA_ROOT:-"/usr/local/cuda-${CUDA_VERSION}"}
OPENCV_VERSION=${OPENCV_VERSION:-"4.x"}
BUILD_TYPE=${BUILD_TYPE:-"Release"}
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

# Detect GPU architecture
detect_gpu_arch() {
    echo_info "Detecting GPU architecture..."
    if command -v nvidia-smi &> /dev/null; then
        GPU_ARCHS=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits | tr '\n' ',' | sed 's/,$//' | sed 's/\./,/g')
        if [ -n "$GPU_ARCHS" ]; then
            echo_success "Detected GPU architectures: $GPU_ARCHS"
            export CUDA_ARCH_BIN="$GPU_ARCHS"
        else
            echo_warning "Could not detect GPU architecture, using default: 8.0,8.6,8.7,8.9,9.0"
            export CUDA_ARCH_BIN="8.0,8.6,8.7,8.9,9.0"
        fi
    else
        echo_warning "nvidia-smi not found, using default architectures: 8.0,8.6,8.7,8.9,9.0"
        export CUDA_ARCH_BIN="8.0,8.6,8.7,8.9,9.0"
    fi
}

# Check dependencies
check_dependencies() {
    echo_info "Checking dependencies..."
    
    # Check CUDA
    if [ ! -d "$CUDA_ROOT" ]; then
        echo_error "CUDA not found at $CUDA_ROOT"
        echo_error "Please install CUDA or set CUDA_ROOT environment variable"
        exit 1
    fi
    
    if [ ! -f "$CUDA_ROOT/bin/nvcc" ]; then
        echo_error "nvcc not found at $CUDA_ROOT/bin/nvcc"
        exit 1
    fi
    
    echo_success "CUDA found at $CUDA_ROOT"
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo_error "Python 3 not found"
        exit 1
    fi
    
    echo_success "Python $PYTHON_VERSION found"
    
    # Check CMake
    if ! command -v cmake &> /dev/null; then
        echo_error "CMake not found. Please install CMake"
        exit 1
    fi
    
    CMAKE_VERSION=$(cmake --version | head -n1 | cut -d' ' -f3)
    echo_success "CMake $CMAKE_VERSION found"
    
    # Check required Python packages
    echo_info "Checking Python packages..."
    python3 -c "import numpy; print(f'NumPy {numpy.__version__} found')" || {
        echo_error "NumPy not found. Please install: pip install numpy"
        exit 1
    }
    
    python3 -c "import skbuild; print(f'scikit-build found')" || {
        echo_error "scikit-build not found. Please install: pip install scikit-build"
        exit 1
    }
}

# Install system dependencies
install_system_deps() {
    echo_info "Installing system dependencies..."
    
    if command -v apt-get &> /dev/null; then
        # Ubuntu/Debian
        sudo apt-get update
        sudo apt-get install -y \
            build-essential cmake git pkg-config \
            libjpeg-dev libtiff5-dev libpng-dev \
            libavcodec-dev libavformat-dev libswscale-dev \
            libgtk-3-dev libcanberra-gtk3-module \
            libxvidcore-dev libx264-dev libgtk-3-dev \
            libtbb-dev libatlas-base-dev gfortran \
            libprotobuf-dev protobuf-compiler \
            libgoogle-glog-dev libgflags-dev \
            libgphoto2-dev libeigen3-dev libhdf5-dev \
            libvtk9-dev libgdal-dev
    elif command -v yum &> /dev/null; then
        # RHEL/CentOS/Fedora
        sudo yum groupinstall -y "Development Tools"
        sudo yum install -y cmake git pkgconfig \
            libjpeg-turbo-devel libpng-devel libtiff-devel \
            ffmpeg-devel gtk3-devel \
            tbb-devel atlas-devel \
            protobuf-devel protobuf-compiler \
            glog-devel gflags-devel \
            libgphoto2-devel eigen3-devel hdf5-devel \
            vtk-devel gdal-devel
    else
        echo_warning "Unknown package manager. Please install dependencies manually."
    fi
}

# Set up environment
setup_environment() {
    echo_info "Setting up build environment..."
    
    # Set CUDA environment
    export PATH="$CUDA_ROOT/bin:$PATH"
    export LD_LIBRARY_PATH="$CUDA_ROOT/lib64:$LD_LIBRARY_PATH"
    export CUDA_HOME="$CUDA_ROOT"
    
    # Set build flags
    export ENABLE_CONTRIB=1
    export ENABLE_CUDA=1
    export ENABLE_JAVA=1
    
    # Optimize for build machine
    export MAKEFLAGS="-j$(nproc)"
    
    echo_success "Environment configured"
}

# Main build function
build_opencv() {
    echo_info "Starting OpenCV build with CUDA support..."
    
    # Clean previous builds
    if [ -d "build" ]; then
        echo_info "Cleaning previous build..."
        rm -rf build
    fi
    
    # Create build flags file
    echo "1" > contrib.enabled
    echo "1" > cuda.enabled
    echo "1" > java.enabled
    
    # Build
    echo_info "Building wheel..."
    python3 setup.py bdist_wheel
    
    echo_success "Build completed!"
    
    # Check output
    if [ -d "dist" ]; then
        echo_info "Built wheels:"
        ls -la dist/*.whl
    fi
}

# Install built wheel
install_wheel() {
    echo_info "Installing built wheel..."
    
    if [ -d "dist" ]; then
        WHEEL_FILE=$(ls dist/*.whl | head -n1)
        if [ -n "$WHEEL_FILE" ]; then
            pip3 install "$WHEEL_FILE" --force-reinstall
            echo_success "Wheel installed: $WHEEL_FILE"
        else
            echo_error "No wheel file found in dist/"
            exit 1
        fi
    else
        echo_error "dist/ directory not found"
        exit 1
    fi
}

# Test installation
test_installation() {
    echo_info "Testing OpenCV installation..."
    
    python3 -c "
import cv2
print(f'OpenCV version: {cv2.__version__}')
print(f'CUDA devices: {cv2.cuda.getCudaEnabledDeviceCount()}')
print(f'Build info:')
print(cv2.getBuildInformation())
" || {
        echo_error "OpenCV test failed"
        exit 1
    }
    
    echo_success "OpenCV installation test passed!"
}

# Main execution
main() {
    echo_info "OpenCV CUDA Build Script"
    echo_info "========================"
    
    # Parse command line arguments
    INSTALL_DEPS=false
    INSTALL_WHEEL=false
    TEST_INSTALL=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --install-deps)
                INSTALL_DEPS=true
                shift
                ;;
            --install-wheel)
                INSTALL_WHEEL=true
                shift
                ;;
            --test)
                TEST_INSTALL=true
                shift
                ;;
            --help)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  --install-deps   Install system dependencies"
                echo "  --install-wheel  Install built wheel"
                echo "  --test          Test installation"
                echo "  --help          Show this help"
                exit 0
                ;;
            *)
                echo_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    if [ "$INSTALL_DEPS" = true ]; then
        install_system_deps
    fi
    
    check_dependencies
    detect_gpu_arch
    setup_environment
    build_opencv
    
    if [ "$INSTALL_WHEEL" = true ]; then
        install_wheel
    fi
    
    if [ "$TEST_INSTALL" = true ]; then
        test_installation
    fi
    
    echo_success "Build script completed successfully!"
}

# Run main function
main "$@"
