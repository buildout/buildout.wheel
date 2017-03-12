name = 'buildout.wheel'
version = '0.2.0'

install_requires = [
    'zc.buildout >=2.8', 'setuptools', 'wheel', 'six', 'pip']
extras_require = dict(test=[])

entry_points = """
[zc.buildout.extension]
wheel = buildout.wheel:load

[zc.buildout.unloadextension]
wheel = buildout.wheel:unload
"""

from setuptools import setup

long_description = open('README.rst').read() + '\n' + open('CHANGES.rst').read()

setup(
    author = 'Jim Fulton',
    author_email = 'jim@jimfulton.info',
    license = 'MIT License',
    url='https://github.com/buildout/buildout.wheel',
    name = name,
    version = version,
    long_description = long_description,
    description = long_description.strip().split('\n')[1],
    packages = [name.split('.')[0], name],
    namespace_packages = [name.split('.')[0]],
    package_dir = {'': 'src'},
    install_requires = install_requires,
    zip_safe = False,
    entry_points=entry_points,
    package_data = {name: ['*.txt', '*.test', '*.html']},
    extras_require = extras_require,
    tests_require = extras_require['test'],
    test_suite = name+'.tests.test_suite',
    include_package_data = True,

    keywords = "development build",
    classifiers = [
        'Development Status :: 5 - Production/Stable',
        'Framework :: Buildout',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Software Development :: Libraries :: Python Modules',
       ],

    )
