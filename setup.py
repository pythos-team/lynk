from setuptools import setup, find_packages
import os

# Safe README read
long_description = ""
if os.path.exists("README.md"):
    with open("README.md", encoding="utf-8") as f:
        long_description = f.read()

setup(
    name="lynkio",
    version="1.1.2",  # Bump version to reflect optional‑only extras
    author="Alex Austin",
    author_email="benmap40@gmail.com",
    description=(
        "Lynk – Python only Realtime Server Framework"
        "HTTP + WebSockets + Database in one engine."
        "No dependencies."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pythos-team/soketdb",
    license="MIT",
    packages=find_packages(),
    
    include_package_data=True,
    

    # ✅ Core: no third‑party packages required – everything works out of the box
    install_requires=[],

    # 🔁 Optional extras – install only what you need
    extras_require={
        "huggingface": [
            "huggingface_hub~=0.16",
        ],
        "aws": [
            "boto3~=1.26",
        ],
        "gdrive": [
            "google-api-python-client~=2.70",
            "google-auth-oauthlib~=1.0",
            "google-auth-httplib2~=0.1",
        ],
        "dropbox": [
            "dropbox~=11.36",
        ],
        "encryption": [
            "cryptography~=39.0",
        ],
        "full": [
            "huggingface_hub~=0.16",
            "boto3~=1.26",
            "google-api-python-client~=2.70",
            "google-auth-oauthlib~=1.0",
            "google-auth-httplib2~=0.1",
            "dropbox~=11.36",
            "cryptography~=39.0",
        ],
        "dev": [
            "pytest~=7.0",
            "pytest-cov~=4.0",
            "black~=22.0",
            "mypy~=0.990",
            "flake8~=5.0",
        ],
    },

    entry_points={
        "console_scripts": [
            "lynkio=lynkio:app",   # Assumes the module is named soketdb.py
        ],
    },

    python_requires=">=3.7",
    zip_safe=False,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Operating System :: OS Independent",
        "Topic :: Database",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],

    keywords=[
        "database",
        "json",
        "offline",
        "lightweight",
        "local-storage",
        "ai",
        "huggingface",
        "cloud",
        "aws",
        "gdrive",
        "dropbox",
        "encryption",
        "real-time",
        "event-engine",
        "http",
        "websocket",
        "asyncio",
        "routing",
        "middleware",
        "pubsub",
        "server",
    ],

    project_urls={
        "Bug Reports": "https://github.com/pythos-team/lynk/issues",
        "Source": "https://github.com/pythos-team/lynk",
        "Documentation": "https://github.com/pythos-team/lynk#readme",
    },
)