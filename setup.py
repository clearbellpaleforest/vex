"""Minimal setup.py so pip install can resolve the local package."""

from setuptools import setup, find_packages

setup(
    name="vex-daemon",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "fastapi==0.138.2",
        "uvicorn==0.49.0",
        "aiosqlite==0.22.1",
        "mcp==1.28.1",
    ],
    python_requires=">=3.10",
)
