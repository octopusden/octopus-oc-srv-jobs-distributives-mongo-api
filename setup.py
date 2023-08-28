#!/usr/bin/env python3

from setuptools import setup
import sys

if "test" in sys.argv:
    raise NotImplementedError("'python setup.py test' is buggy, please run as 'python -m unittest'")

__version = "2.2.1"

setup(name="oc-distributives-mongo-api",
      version=__version,
      description="Distributives HTTP API worker",
      long_description="Checksums Mobgo-based distributives HTTP API service",
      long_description_content_type="text/plain",

      install_requires=[
          "mongoengine >= 0.23",
          "Werkzeug == 2.0.3",
          "flask == 2.0.3",
          "gunicorn",
          "packaging >= 21.0"
      ],

      packages=["oc_distributives_mongo_api"],
      package_data={},
      scripts = [],
      python_requires=">=3.7",
)
