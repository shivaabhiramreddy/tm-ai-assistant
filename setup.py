from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="tm_ai_assistant",
    version="0.0.1",
    description="AI Business Assistant for Truemeal Feeds ERP",
    author="Fertile Green Industries Pvt Ltd",
    author_email="shivaabhiramreddy@gmail.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
