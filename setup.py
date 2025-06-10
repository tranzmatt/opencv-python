import io
import os
import os.path
import sys
import runpy
import subprocess
import re
import sysconfig
import platform
from skbuild import cmaker, setup

# Try to import configuration from opencv_build_config.py
try:
    from opencv_build_config import BUILD_CONFIG, get_cmake_args as get_config_cmake_args
    USE_CONFIG_FILE = True
    print("Using configuration from opencv_build_config.py")
except ImportError:
    USE_CONFIG_FILE = False
    BUILD_CONFIG = {}
    print("opencv_build_config.py not found, using default configuration")


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    CI_BUILD = os.environ.get("CI_BUILD", "False")
    is_CI_build = True if CI_BUILD == "1" else False
    cmake_source_dir = "opencv"
    minimum_supported_numpy = "1.13.3"
    build_contrib = get_build_env_var_by_name("contrib") or BUILD_CONFIG.get("ENABLE_CONTRIB", True)
    build_headless = get_build_env_var_by_name("headless") or BUILD_CONFIG.get("ENABLE_HEADLESS", False)
    build_java = "ON" if (get_build_env_var_by_name("java") or BUILD_CONFIG.get("ENABLE_JAVA", True)) else "OFF"
    build_rolling = get_build_env_var_by_name("rolling") or BUILD_CONFIG.get("ENABLE_ROLLING", False)
    build_cuda = get_build_env_var_by_name("cuda") or BUILD_CONFIG.get("ENABLE_CUDA", False)

    install_requires = [
        'numpy>=1.13.3; python_version<"3.7"',
        'numpy>=1.17.0; python_version>="3.7"', # https://github.com/numpy/numpy/pull/13725
        'numpy>=1.17.3; python_version>="3.8"',
        'numpy>=1.19.3; python_version>="3.9"',
        'numpy>=1.21.2; python_version>="3.10"',
        'numpy>=1.19.3; python_version>="3.6" and platform_system=="Linux" and platform_machine=="aarch64"',
        'numpy>=1.21.0; python_version<="3.9" and platform_system=="Darwin" and platform_machine=="arm64"',
        'numpy>=1.21.4; python_version>="3.10" and platform_system=="Darwin"',
        "numpy>=1.23.5; python_version>='3.11'",
        "numpy>=1.26.0; python_version>='3.12'"
    ]

    # Add CUDA runtime dependencies if CUDA build is enabled
    if build_cuda:
        cuda_requirements = [
            'nvidia-cublas-cu12>=12.1.0.26',
            'nvidia-cuda-cupti-cu12>=12.1.105',
            'nvidia-cuda-nvrtc-cu12>=12.1.105',
            'nvidia-cuda-runtime-cu12>=12.1.105',
            'nvidia-cudnn-cu12>=8.9.2.26',
            'nvidia-cufft-cu12>=11.0.2.54',
            'nvidia-curand-cu12>=10.3.2.106',
            'nvidia-cusolver-cu12>=11.4.5.107',
            'nvidia-cusparse-cu12>=12.1.0.106',
            'nvidia-nccl-cu12>=2.18.1',
            'nvidia-nvtx-cu12>=12.1.105'
        ]
        # Only add CUDA requirements on Linux (CUDA support is primarily for Linux)
        if sys.platform.startswith("linux"):
            install_requires.extend(cuda_requirements)
        else:
            print("Warning: CUDA build requested but CUDA runtime packages are only available on Linux")

    python_version = cmaker.CMaker.get_python_version()
    python_lib_path = cmaker.CMaker.get_python_library(python_version) or ""
    # HACK: For Scikit-build 0.17.3 and newer that returns None or empty sptring for PYTHON_LIBRARY in manylinux2014
    # A small release related to PYTHON_LIBRARY handling changes in 0.17.2; scikit-build 0.17.3 returns an empty string from get_python_library if no Python library is present (like on manylinux), where 0.17.2 returned None, and previous versions returned a non-existent path. Note that adding REQUIRED to find_package(PythonLibs will fail, but it is incorrect (you must not link to libPython.so) and was really just injecting a non-existent path before.
    # TODO: Remove the hack when the issue is handled correctly in main OpenCV CMake.
    if python_lib_path == "":
        python_lib_path = "libpython%sm.a" % python_version
    python_lib_path = python_lib_path.replace("\\", "/")

    python_include_dir = cmaker.CMaker.get_python_include_dir(python_version).replace(
        "\\", "/"
    )

    if os.path.exists(".git"):
        import pip._internal.vcs.git as git

        g = git.Git()  # NOTE: pip API's are internal, this has to be refactored

        g.run_command(["submodule", "sync"])

        if build_rolling:
            g.run_command(
                ["submodule", "update", "--init", "--recursive", "--remote", cmake_source_dir]
            )

            if build_contrib:
                g.run_command(
                    ["submodule", "update", "--init", "--recursive", "--remote", "opencv_contrib"]
                )
        else:
            g.run_command(
                ["submodule", "update", "--init", "--recursive", cmake_source_dir]
            )

            if build_contrib:
                g.run_command(
                    ["submodule", "update", "--init", "--recursive", "opencv_contrib"]
                )

    package_version, build_contrib, build_headless, build_rolling = get_and_set_info(
        build_contrib, build_headless, build_rolling, is_CI_build
    )

    # https://stackoverflow.com/questions/1405913/python-32bit-or-64bit-mode
    is64 = sys.maxsize > 2 ** 32

    package_name = "opencv-python"

    if build_contrib and not build_headless:
        package_name = "opencv-contrib-python"

    if build_contrib and build_headless:
        package_name = "opencv-contrib-python-headless"

    if build_headless and not build_contrib:
        package_name = "opencv-python-headless"

    if build_rolling:
        package_name += "-rolling"
    
    # Add CUDA suffix to package name if CUDA is enabled
    if build_cuda:
        package_name += "-cuda"

    long_description = io.open("README.md", encoding="utf-8").read()

    packages = ["cv2", "cv2.data"]

    package_data = {
        "cv2": ["*%s" % sysconfig.get_config_vars().get("SO"), "version.py"]
        + (["*.dll"] if os.name == "nt" else [])
        + ["LICENSE.txt", "LICENSE-3RD-PARTY.txt"],
        "cv2.data": ["*.xml"],
    }

    # Files from CMake output to copy to package.
    # Path regexes with forward slashes relative to CMake install dir.
    rearrange_cmake_output_data = {
        "cv2": (
            [r"bin/opencv_videoio_ffmpeg\d{4}%s\.dll" % ("_64" if is64 else "")]
            if os.name == "nt"
            else []
        )
        +
        # In Windows, in python/X.Y/<arch>/; in Linux, in just python/X.Y/.
        # Naming conventions vary so widely between versions and OSes
        # had to give up on checking them.
        # If not specifying PY_LIMITED_API, the Python sources go under python/cv2/python-3.MINOR_VERSION/ instead of python/cv2/python-3/
        [
            r"python/cv2/python-%s*/cv2.*"
            % (sys.version_info[0]) if 'CMAKE_ARGS' in os.environ and "-DPYTHON3_LIMITED_API=ON" in os.environ['CMAKE_ARGS']
            else r"python/cv2/python-%s.*/cv2.*"
            % (sys.version_info[0])
        ]
        +
        [
            r"python/cv2/__init__.py"
        ]
        +
        [
            r"python/cv2/.*config.*.py"
        ]
        +
        [ r"python/cv2/py.typed" ] if sys.version_info >= (3, 6) else []
        ,
        "cv2.data": [  # OPENCV_OTHER_INSTALL_PATH
            ("etc" if os.name == "nt" else "share/opencv4") + r"/haarcascades/.*\.xml"
        ],
        "cv2.gapi": [
            "python/cv2" + r"/gapi/.*\.py"
        ],
        "cv2.mat_wrapper": [
            "python/cv2" + r"/mat_wrapper/.*\.py"
        ],
        "cv2.misc": [
            "python/cv2" + r"/misc/.*\.py"
        ],
        "cv2.utils": [
            "python/cv2" + r"/utils/.*\.py"
        ],
    }

    if sys.version_info >= (3, 6):
        rearrange_cmake_output_data["cv2.typing"] = ["python/cv2" + r"/typing/.*\.py"]

    # Files in sourcetree outside package dir that should be copied to package.
    # Raw paths relative to sourcetree root.
    files_outside_package_dir = {"cv2": ["LICENSE.txt", "LICENSE-3RD-PARTY.txt"]}

    ci_cmake_generator = (
        ["-G", "Visual Studio 14" + (" Win64" if is64 else "")]
        if os.name == "nt"
        else ["-G", "Unix Makefiles"]
    )

    # Base CMAKE arguments incorporating your specific configuration
    cmake_args = (
        (ci_cmake_generator if is_CI_build else [])
        + [
            # Python configuration
            "-DPYTHON3_EXECUTABLE=%s" % sys.executable,
            "-DPYTHON_DEFAULT_EXECUTABLE=%s" % sys.executable,
            "-DPYTHON3_INCLUDE_DIR=%s" % python_include_dir,
            "-DPYTHON3_LIBRARY=%s" % python_lib_path,
            "-DBUILD_opencv_python3=ON",
            "-DBUILD_opencv_python2=OFF",
            "-DPYTHON3_LIMITED_API=ON",
            "-DOPENCV_PYTHON3_INSTALL_PATH=python",
            
            # Essential build configuration
            "-DINSTALL_CREATE_DISTRIB=ON",
            "-DBUILD_SHARED_LIBS=OFF",
        ]
        + (
            # CMake flags for windows/arm64 build
            ["-DCMAKE_GENERATOR_PLATFORM=ARM64",
             # Emulated cmake requires following flags to correctly detect
             # target architecture for windows/arm64 build
             "-DOPENCV_WORKAROUND_CMAKE_20989=ON",
             "-DCMAKE_SYSTEM_PROCESSOR=ARM64"]
            if platform.machine() == "ARM64" and sys.platform == "win32"
            # If it is not defined 'linker flags: /machine:X86' on Windows x64
            else ["-DCMAKE_GENERATOR_PLATFORM=x64"] if is64 and sys.platform == "win32"
            else []
          )
        + (
            ["-DOPENCV_EXTRA_MODULES_PATH=" + os.path.abspath("opencv_contrib/modules")]
            if build_contrib
            else []
        )
    )

    # Add configuration from opencv_build_config.py if available
    if USE_CONFIG_FILE:
        try:
            config_cmake_args = get_config_cmake_args()
            cmake_args.extend(config_cmake_args)
            print(f"Added {len(config_cmake_args)} configuration arguments from opencv_build_config.py")
        except Exception as e:
            print(f"Warning: Could not load configuration from opencv_build_config.py: {e}")
    else:
        # Fallback to hardcoded configuration from your CMAKE_ARGS
        fallback_args = [
            # Build configuration from your CMAKE_ARGS
            "-DBUILD_EXAMPLES=OFF",
            "-DBUILD_PROTOBUF=OFF",
            "-DBUILD_PERF_TESTS=OFF",
            "-DBUILD_TESTS=OFF",
            "-DBUILD_DOCS=OFF",
            "-DBUILD_opencv_apps=OFF",
            "-DBUILD_opencv_freetype=OFF",
            "-DBUILD_opencv_dnn=ON",
            "-DBUILD_opencv_dnn_modern=ON",
            "-DBUILD_opencv_face=ON",
            "-DBUILD_opencv_java=%s" % build_java,
            
            # Build type and compilation
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_SKIP_RPATH=ON",
            "-DCMAKE_VERBOSE_MAKEFILE=ON",
            "-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF",
            "-DENABLE_PRECOMPILED_HEADERS=OFF",
            
            # Install configuration
            "-DINSTALL_C_EXAMPLES=ON",
            "-DINSTALL_PYTHON_EXAMPLES=ON",
            "-DOPENCV_GENERATE_PKGCONFIG=ON",
            
            # Library dependencies
            "-DWITH_ADE=OFF",
            "-DWITH_CAROTENE=OFF",
            "-DWITH_EIGEN=ON",
            "-DWITH_FFMPEG=ON",
            "-DWITH_FLATBUFFERS=OFF",
            "-DWITH_GDAL=ON",
            "-DWITH_GDCM=ON",
            "-DWITH_GSTREAMER=ON",
            "-DWITH_GPHOTO2=ON",
            "-DWITH_GTK=OFF",
            "-DWITH_IPP=OFF",
            "-DWITH_ITT=OFF",
            "-DWITH_JASPER=OFF",
            "-DWITH_JPEG=ON",
            "-DWITH_LAPACK=ON",
            "-DWITH_NGRAPH=OFF",
            "-DWITH_OPENCL=ON",
            "-DWITH_OPENEXR=ON",
            "-DWITH_OPENGL=ON",
            "-DWITH_PNG=ON",
            "-DWITH_PROTOBUF=ON",
            "-DWITH_PVAPI=ON",
            "-DWITH_QT=6",
            "-DWITH_QUIRC=ON",
            "-DWITH_TIFF=ON",
            "-DWITH_UNICAP=OFF",
            "-DWITH_VTK=ON",
            "-DWITH_XINE=OFF",
            "-DWITH_TBB=ON",
            "-DWITH_1394=OFF",
            "-DWITH_V4L=ON",
            
            # Protobuf configuration
            "-DPROTOBUF_UPDATE_FILES=ON",
            
            # CURL configuration (adjust paths as needed)
            "-DCURL_INCLUDE_DIR=/usr/include/curl",
            "-DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so.4.7.0",
            
            # OpenCL configuration
            "-DOPENCL_INCLUDE_DIR:PATH=/usr/include/CL/",
        ]
        cmake_args.extend(fallback_args)

    # Add Ubuntu 22.04 / Python 3.10 specific fixes
    if sys.platform.startswith("linux"):
        # Check if we're on Ubuntu 22.04
        try:
            with open('/etc/os-release', 'r') as f:
                os_info = f.read()
                if 'VERSION_ID="22.04"' in os_info or 'jammy' in os_info.lower():
                    ubuntu_22_04_fixes = [
                        "-DOPENCV_PYTHON_DETECT_PYTHON2=OFF",
                        "-DOPENCV_PYTHON_DETECT_PYTHON3=ON",
                        "-DCMAKE_CXX_FLAGS=-Wno-error=restrict",
                        "-DCMAKE_C_FLAGS=-Wno-error=restrict",
                        "-DProtobuf_USE_STATIC_LIBS=OFF",
                        "-DOPENCV_FFMPEG_USE_FIND_PACKAGE=ON",
                        "-DHDF5_USE_STATIC_LIBRARIES=OFF",
                    ]
                    
                    # Python 3.10 specific fixes
                    if sys.version_info[:2] == (3, 10):
                        # Fix Python library detection for 3.10
                        python_lib_paths = [
                            f"/usr/lib/x86_64-linux-gnu/libpython{sys.version_info.major}.{sys.version_info.minor}.so",
                            f"/usr/lib/libpython{sys.version_info.major}.{sys.version_info.minor}.so",
                        ]
                        for lib_path in python_lib_paths:
                            if os.path.exists(lib_path):
                                ubuntu_22_04_fixes.append(f"-DPYTHON3_LIBRARY={lib_path}")
                                break
                    
                    cmake_args.extend(ubuntu_22_04_fixes)
                    print("Applied Ubuntu 22.04 compatibility fixes")
        except FileNotFoundError:
            pass
    if build_cuda:
        # Auto-detect CUDA installation if not explicitly set
        cuda_root = BUILD_CONFIG.get("CUDA_ROOT", os.environ.get("CUDA_ROOT", "/usr/local/cuda-12.8"))
        if not os.path.exists(cuda_root):
            # Fallback to common CUDA locations
            for potential_cuda in ["/usr/local/cuda", "/opt/cuda", "/usr/lib/cuda"]:
                if os.path.exists(potential_cuda):
                    cuda_root = potential_cuda
                    break
        
        # Get CUDA architecture from config or auto-detect
        cuda_arch = BUILD_CONFIG.get("CUDA_ARCH_BIN", os.environ.get("CUDA_ARCH_BIN", "8.0,8.6,8.7,8.9,9.0"))
        
        cuda_args = [
            "-DWITH_CUDA=ON",
            "-DCUDA_NVCC_EXECUTABLE=%s/bin/nvcc" % cuda_root,
            "-DCMAKE_CUDA_COMPILER=%s/bin/nvcc" % cuda_root,
            "-DCUDA_TOOLKIT_ROOT_DIR=%s" % cuda_root,
            "-DCUDA_SDK_ROOT_DIR=%s" % cuda_root,
            "-DCUDA_BIN_PATH=%s/bin" % cuda_root,
            "-DCUDA_INCLUDE_DIRS=%s/include" % cuda_root,
            "-DCUDA_VERSION=%s" % BUILD_CONFIG.get("CUDA_VERSION", "12.8"),
            "-DCUDAToolkit_ROOT=%s" % cuda_root,
            "-DCUDA_ARCH_BIN=%s" % cuda_arch,
            "-DCUDA_FAST_MATH=%s" % ("ON" if BUILD_CONFIG.get("CUDA_FAST_MATH", True) else "OFF"),
            "-DOPENCV_DNN_CUDA=ON",
            "-DWITH_CUBLAS=ON",
            "-DWITH_CUFFT=ON",
            "-DWITH_CURAND=ON",
            "-DWITH_CUDNN=ON",
            "-DCUDA_SEPARABLE_COMPILATION=OFF",
            # Additional CUDA optimizations
            "-DCUDA_NVCC_FLAGS=--expt-relaxed-constexpr",
            "-DWITH_NVCUVID=ON",
            "-DWITH_NVCUVENC=ON",
        ]
        
        # Add NumPy include dirs for CUDA builds
        try:
            import numpy
            numpy_include = numpy.get_include()
            cuda_args.append("-DPYTHON3_NUMPY_INCLUDE_DIRS=%s" % numpy_include)
        except ImportError:
            # Fallback to system numpy if available
            potential_numpy_paths = [
                "/usr/lib/python3/dist-packages/numpy/core/include",
                "/usr/local/lib/python3/dist-packages/numpy/core/include"
            ]
            for np_path in potential_numpy_paths:
                if os.path.exists(np_path):
                    cuda_args.append("-DPYTHON3_NUMPY_INCLUDE_DIRS=%s" % np_path)
                    break
        
        cmake_args.extend(cuda_args)
        print(f"CUDA support enabled with toolkit at: {cuda_root}")
        print(f"CUDA architectures: {cuda_arch}")

    if build_headless:
        # it seems that cocoa cannot be disabled so on macOS the package is not truly headless
        cmake_args.append("-DWITH_WIN32UI=OFF")
        cmake_args.append("-DWITH_QT=OFF")
        cmake_args.append("-DWITH_GTK=OFF")
        if is_CI_build:
            cmake_args.append(
                "-DWITH_MSMF=OFF"
            )  # see: https://github.com/skvark/opencv-python/issues/263

    if sys.platform.startswith("linux") and not is64 and "bdist_wheel" in sys.argv:
        subprocess.check_call("patch -p0 < patches/patchOpenEXR", shell=True)

    # OS-specific components during CI builds
    if is_CI_build:

        if (
            not build_headless
            and "bdist_wheel" in sys.argv
            and sys.platform.startswith("linux")
        ):
            cmake_args.append("-DWITH_QT=6")  # Use Qt6 as specified in your config
            subprocess.check_call("patch -p1 < patches/patchQtPlugins", shell=True)

            if sys.platform.startswith("linux"):
                rearrange_cmake_output_data["cv2.qt.plugins.platforms"] = [
                    (r"lib/qt/plugins/platforms/libqxcb\.so")
                ]

                # add fonts for Qt6
                fonts = []
                for file in os.listdir("/usr/share/fonts/dejavu"):
                    if file.endswith(".ttf"):
                        fonts.append(
                            (r"lib/qt/fonts/dejavu/%s\.ttf" % file.split(".")[0])
                        )

                rearrange_cmake_output_data["cv2.qt.fonts"] = fonts

            if sys.platform == "darwin":
                rearrange_cmake_output_data["cv2.qt.plugins.platforms"] = [
                    (r"lib/qt/plugins/platforms/libqcocoa\.dylib")
                ]

        if sys.platform.startswith("linux"):
            cmake_args.append("-DWITH_V4L=ON")
            cmake_args.append("-DWITH_LAPACK=ON")
            cmake_args.append("-DENABLE_PRECOMPILED_HEADERS=OFF")

    # works via side effect
    RearrangeCMakeOutput(
        rearrange_cmake_output_data, files_outside_package_dir, package_data.keys()
    )

    setup(
        name=package_name,
        version=package_version,
        url="https://github.com/opencv/opencv-python",
        license="Apache 2.0",
        description="Wrapper package for OpenCV python bindings with CUDA support.",
        long_description=long_description,
        long_description_content_type="text/markdown",
        packages=packages,
        package_data=package_data,
        maintainer="OpenCV Team",
        ext_modules=EmptyListWithLength(),
        install_requires=install_requires,
        python_requires=">=3.6",
        classifiers=[
            "Development Status :: 5 - Production/Stable",
            "Environment :: Console",
            "Intended Audience :: Developers",
            "Intended Audience :: Education",
            "Intended Audience :: Information Technology",
            "Intended Audience :: Science/Research",
            "License :: OSI Approved :: Apache Software License",
            "Operating System :: MacOS",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: POSIX",
            "Operating System :: Unix",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3 :: Only",
            "Programming Language :: Python :: 3.6",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
            "Programming Language :: Python :: 3.13",
            "Programming Language :: C++",
            "Programming Language :: Python :: Implementation :: CPython",
            "Topic :: Scientific/Engineering",
            "Topic :: Scientific/Engineering :: Image Recognition",
            "Topic :: Software Development",
        ],
        cmake_args=cmake_args,
        cmake_source_dir=cmake_source_dir,
    )

    print("OpenCV is raising funds to keep the library free for everyone, and we need the support of the entire community to do it. Donate to OpenCV on GitHub:\nhttps://github.com/sponsors/opencv\n")

class RearrangeCMakeOutput:
    """
        Patch SKBuild logic to only take files related to the Python package
        and construct a file hierarchy that SKBuild expects (see below)
    """

    _setuptools_wrap = None

    # Have to wrap a function reference, or it's converted
    # into an instance method on attr assignment
    import argparse

    wraps = argparse.Namespace(_classify_installed_files=None)
    del argparse

    package_paths_re = None
    packages = None
    files_outside_package = None

    def __init__(self, package_paths_re, files_outside_package, packages):
        cls = self.__class__
        assert not cls.wraps._classify_installed_files, "Singleton object"
        import skbuild.setuptools_wrap

        cls._setuptools_wrap = skbuild.setuptools_wrap
        cls.wraps._classify_installed_files = (
            cls._setuptools_wrap._classify_installed_files
        )
        cls._setuptools_wrap._classify_installed_files = (
            self._classify_installed_files_override
        )

        cls.package_paths_re = package_paths_re
        cls.files_outside_package = files_outside_package
        cls.packages = packages

    def __del__(self):
        cls = self.__class__
        cls._setuptools_wrap._classify_installed_files = (
            cls.wraps._classify_installed_files
        )
        cls.wraps._classify_installed_files = None
        cls._setuptools_wrap = None

    def _classify_installed_files_override(
        self,
        install_paths,
        package_data,
        package_prefixes,
        py_modules,
        new_py_modules,
        scripts,
        new_scripts,
        data_files,
        cmake_source_dir,
        cmake_install_reldir,
    ):
        """
            From all CMake output, we're only interested in a few files
            and must place them into CMake install dir according
            to Python conventions for SKBuild to find them:
                package\
                    file
                    subpackage\
                        etc.
        """

        cls = self.__class__

        # 'relpath'/'reldir' = relative to CMAKE_INSTALL_DIR/cmake_install_dir
        # 'path'/'dir' = relative to sourcetree root
        cmake_install_dir = os.path.join(
            cls._setuptools_wrap.CMAKE_INSTALL_DIR(), cmake_install_reldir
        )
        install_relpaths = [
            os.path.relpath(p, cmake_install_dir) for p in install_paths
        ]
        fslash_install_relpaths = [
            p.replace(os.path.sep, "/") for p in install_relpaths
        ]
        relpaths_zip = list(zip(fslash_install_relpaths, install_relpaths))

        final_install_relpaths = []

        print("Copying files from CMake output")

        # add lines from the old __init__.py file to the config file
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts', '__init__.py'), 'r') as custom_init:
            custom_init_data = custom_init.read()

        # OpenCV generates config with different name for case with PYTHON3_LIMITED_API=ON
        config_py = os.path.join(cmake_install_dir, 'python', 'cv2', 'config-%s.%s.py'
                                 % (sys.version_info[0], sys.version_info[1]))
        if not os.path.exists(config_py):
            config_py = os.path.join(cmake_install_dir, 'python', 'cv2', 'config-%s.py' % sys.version_info[0])

        with open(config_py, 'w') as opencv_init_config:
            opencv_init_config.write(custom_init_data)

        if sys.version_info >= (3, 6):
            for p in install_relpaths:
                if p.endswith(".pyi"):
                    target_rel_path = os.path.relpath(p, "python/cv2")
                    cls._setuptools_wrap._copy_file(
                        os.path.join(cmake_install_dir, p),
                        os.path.join(cmake_install_dir, "cv2", target_rel_path),
                        hide_listing=False,
                    )
                    final_install_relpaths.append(os.path.join("cv2", target_rel_path))

        del install_relpaths, fslash_install_relpaths

        for package_name, relpaths_re in cls.package_paths_re.items():
            package_dest_reldir = package_name.replace(".", os.path.sep)
            for relpath_re in relpaths_re:
                found = False
                r = re.compile(relpath_re + "$")
                for fslash_relpath, relpath in relpaths_zip:
                    m = r.match(fslash_relpath)
                    if not m:
                        continue
                    found = True
                    new_install_relpath = os.path.join(
                        package_dest_reldir, os.path.basename(relpath)
                    )
                    cls._setuptools_wrap._copy_file(
                        os.path.join(cmake_install_dir, relpath),
                        os.path.join(cmake_install_dir, new_install_relpath),
                        hide_listing=False,
                    )
                    final_install_relpaths.append(new_install_relpath)
                    del m, fslash_relpath, new_install_relpath
                else:
                    # gapi can be missed if ADE was not downloaded (network issue)
                    if not found and "gapi" not in relpath_re:
                        raise Exception("Not found: '%s'" % relpath_re)
                del r, found

        del relpaths_zip

        print("Copying files from non-default sourcetree locations")

        for package_name, paths in cls.files_outside_package.items():
            package_dest_reldir = package_name.replace(".", os.path.sep)
            for path in paths:
                new_install_relpath = os.path.join(
                    package_dest_reldir,
                    # Don't yet have a need to copy
                    # to subdirectories of package dir
                    os.path.basename(path),
                )
                cls._setuptools_wrap._copy_file(
                    path,
                    os.path.join(cmake_install_dir, new_install_relpath),
                    hide_listing=False,
                )
                final_install_relpaths.append(new_install_relpath)

        final_install_paths = [
            os.path.join(cmake_install_dir, p) for p in final_install_relpaths
        ]

        # Check scikit-build version compatibility and call accordingly
        try:
            import skbuild
            skbuild_version = getattr(skbuild, '__version__', '0.11.1')
            
            # For scikit-build 0.11.1 specifically (Ubuntu 22.04)
            # Parameters: install_paths, package_data, package_prefixes, py_modules, 
            #            new_py_modules, scripts, new_scripts, data_files, 
            #            cmake_source_dir, cmake_install_dir
            if skbuild_version == '0.11.1':
                return (cls.wraps._classify_installed_files)(
                    final_install_paths,      # install_paths
                    package_data,             # package_data  
                    package_prefixes,         # package_prefixes
                    py_modules,               # py_modules
                    new_py_modules,           # new_py_modules
                    scripts,                  # scripts
                    new_scripts,              # new_scripts
                    data_files,               # data_files
                    "",                       # cmake_source_dir
                    cmake_install_reldir      # cmake_install_dir
                )
            
            # For other 0.11.x versions, use keyword arguments to be safe
            elif skbuild_version.startswith('0.11'):
                return (cls.wraps._classify_installed_files)(
                    install_paths=final_install_paths,
                    package_data=package_data,
                    package_prefixes=package_prefixes,
                    py_modules=py_modules,
                    new_py_modules=new_py_modules,
                    scripts=scripts,
                    new_scripts=new_scripts,
                    data_files=data_files,
                    cmake_source_dir="",
                    cmake_install_dir=cmake_install_reldir
                )
            
            # For newer versions (0.12+)
            else:
                import inspect
                original_func = cls.wraps._classify_installed_files
                sig = inspect.signature(original_func)
                
                call_args = {
                    'install_paths': final_install_paths,
                    'package_data': package_data,
                    'package_prefixes': package_prefixes,
                    'py_modules': py_modules,
                    'new_py_modules': new_py_modules,
                    'scripts': scripts,
                    'new_scripts': new_scripts,
                    'data_files': data_files,
                    'cmake_source_dir': "",
                }
                
                if 'cmake_install_reldir' in sig.parameters:
                    call_args['cmake_install_reldir'] = cmake_install_reldir
                elif '_cmake_install_dir' in sig.parameters:
                    call_args['_cmake_install_dir'] = cmake_install_reldir
                elif 'cmake_install_dir' in sig.parameters:
                    call_args['cmake_install_dir'] = cmake_install_reldir
                
                return original_func(**call_args)
                
        except Exception as e:
            print(f"Warning: scikit-build compatibility issue: {e}")
            # This should not happen now that we know the exact signature
            raise e


def get_and_set_info(contrib, headless, rolling, ci_build):
    # cv2/version.py should be generated by running find_version.py
    version = {}
    here = os.path.abspath(os.path.dirname(__file__))
    version_file = os.path.join(here, "cv2", "version.py")

    # generate a fresh version.py always when Git repository exists
    # (in sdists the version.py file already exists)
    if os.path.exists(".git"):
        old_args = sys.argv.copy()
        sys.argv = ["", str(contrib), str(headless), str(rolling), str(ci_build)]
        runpy.run_path("find_version.py", run_name="__main__")
        sys.argv = old_args

    with open(version_file) as fp:
        exec(fp.read(), version)

    return version["opencv_version"], version["contrib"], version["headless"], version["rolling"]


def get_build_env_var_by_name(flag_name):
    flag_set = False

    try:
        flag_set = bool(int(os.getenv("ENABLE_" + flag_name.upper(), None)))
    except Exception:
        pass

    if not flag_set:
        try:
            flag_set = bool(int(open(flag_name + ".enabled").read(1)))
        except Exception:
            pass

    return flag_set


def check_cuda_availability():
    """Check if CUDA is available on the system"""
    try:
        # Check for nvcc
        result = subprocess.run(['nvcc', '--version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    
    # Check for CUDA libraries
    cuda_paths = ["/usr/local/cuda", "/opt/cuda", "/usr/lib/cuda"]
    for path in cuda_paths:
        if os.path.exists(os.path.join(path, "bin", "nvcc")):
            return True
    
    return False


def get_cuda_compute_capabilities():
    """Detect available CUDA compute capabilities"""
    try:
        # Try to detect GPU compute capabilities
        result = subprocess.run(['nvidia-smi', '--query-gpu=compute_cap', '--format=csv,noheader,nounits'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            caps = set()
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    caps.add(line.strip().replace('.', ''))
            if caps:
                return ','.join(sorted(caps))
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    
    # Fallback to common architectures
    return "8.0,8.6,8.7,8.9,9.0"


# This creates a list which is empty but returns a length of 1.
# Should make the wheel a binary distribution and platlib compliant.
class EmptyListWithLength(list):
    def __len__(self):
        return 1


if __name__ == "__main__":
    main()
