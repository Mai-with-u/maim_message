import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="maim_message",
    version="0.6.1",
    author="tcmofashi",
    url="https://github.com/MaiM-with-u/maim_message",
    author_email="mofashiforzbx@qq.com",
    description="A message handling library for maimcore",
    long_description_content_type="text/markdown",
    package_dir={"": "src"},
    packages=setuptools.find_packages(where="src"),
    python_requires=">=3.9",
)
