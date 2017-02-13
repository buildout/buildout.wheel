import os, setuptools, sys
from distutils.core import setup, Extension

setup(name = "extdemo", version = "1.0",
      ext_modules = [Extension('extdemo', ['extdemo.c'])],
      )
