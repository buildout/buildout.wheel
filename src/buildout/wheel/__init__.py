import glob
import os
import os.path
import shutil
import sys
import tempfile
import pkg_resources
import setuptools.package_index
import wheel.install
import wheel.decorator
import pip.pep425tags
import zc.buildout.easy_install
import distutils.command.install


NAMESPACE_STUB_PATH = os.path.join(os.path.dirname(__file__),
                                   'namespace_stub.py')
assert os.path.isfile(NAMESPACE_STUB_PATH)


orig_distros_for_location = setuptools.package_index.distros_for_location
original_wheel_to_egg = zc.buildout.easy_install.wheel_to_egg
orig_Installer = zc.buildout.easy_install.Installer


class Installer(orig_Installer):
    """Installer class that enriches the environment with all the wheels in the
    egg directory, since `Environment` can't find them on its own like it can
    find eggs.
    """

    def __init__(self, *args, **kwargs):
        orig_Installer.__init__(self, *args, **kwargs)
        dest = self._dest
        # include unpacked wheel directories in path after `self._dest`:
        wheeldirs = [
            wheeldir for wheeldir in glob.glob(os.path.join(dest, '*.whl'))
            if os.path.isdir(wheeldir)
        ]
        path = self._path
        path[1:1] = wheeldirs
        # Sorry to throw away all the previous hard work creating self._env
        # but it didn't take the wheel directories into account:
        self._env = pkg_resources.Environment(path)


class SelfDestructingDistro(pkg_resources.DistInfoDistribution):
    """Since the location for creating the egg is inside the download directory
    which could be the download cache, this wheel was created in a tempdir
    inside it and we must clean up the tempdir to avoid leaving garbage behind.
    """
    def __del__(self):
        shutil.rmtree(os.path.dirname(self.location))


class WheelDir(wheel.install.WheelFile):

    def __init__(self, *args, **kwargs):
        # use pip's notion of supported tags, not wheel's:
        kwargs.setdefault('context', pip.pep425tags.get_supported)
        super(WheelDir, self).__init__(*args, **kwargs)

    def get_temp_dist(self):
        join = os.path.join
        target = tempfile.mkdtemp()
        location = join(target, os.path.basename(self.filename))
        # drop everything inside the metadata directory, keyed by section name,
        # except the code itself:
        overrides = {
            key: (location if key in ('platlib', 'purelib')
                  else join(location, self.distinfo_name, key))
            for key in distutils.command.install.SCHEME_KEYS
        }
        self.install(overrides=overrides)

        metadata = pkg_resources.PathMetadata(
            location, join(location, self.distinfo_name)
        )
        # Fix namespaces missing __init__ for Python 2 since we're not feeding
        # the wheel dirs to `site.addsitedir()` and so will ignore .pth files
        # in the wheel dirs.
        if (sys.version_info < (3, 3) and
                metadata.has_metadata('namespace_packages.txt')):
            for namespace in metadata.get_metadata_lines('namespace_packages.txt'):
                __init__filename = namespace.split('.') + ['__init__.py']
                dest = join(location, *__init__filename)
                if not os.path.exists(dest):
                    shutil.copyfile(NAMESPACE_STUB_PATH, dest)
        # See docstring of SelfDestructingDistro above for why it's needed:
        dist = self.distribution(location, metadata=metadata,
                                 class_=SelfDestructingDistro)
        return dist

    @wheel.decorator.reify
    def distribution_info(self):
        info = self.parsed_filename.groupdict()
        if info['plat'] == 'any':
            # Pure Python
            info['plat'] = None
        elif self.compatible:
            # abi/platform specific, but compatible wheel. Pretend we're a
            # perfect match to avoid setuptool ignoring the wheel since it
            # doesn't understand, e.g. manylinux1.
            info['plat'] = pkg_resources.get_build_platform()
        return info

    def distribution(self, location=None, metadata=None,
                     class_=pkg_resources.DistInfoDistribution):
        info = self.distribution_info
        return class_(
            location=location if location is not None else self.filename,
            metadata=metadata,
            project_name=info['name'],
            version=info['ver'],
            platform=info['plat'],
            # make sure buildout believes it's an egg with anoter extension:
            precedence=pkg_resources.EGG_DIST,
        )


def distros_for_location(location, basename, metadata=None):
    """Yield egg or source distribution objects based on basename

    Here we override to give wheels a chance"""
    if basename.endswith('.whl'):
        try:
            wf = WheelDir(basename)
        except wheel.install.BadWheelFile:
            pass
        else:
            if wf.compatible:
                # It's a match. Treat it as an egg
                # distro. Buildout will sort it out.
                return [wf.distribution(location, metadata)]
        # Not a match, short circuit:
        return ()
    return orig_distros_for_location(location, basename, metadata=metadata)


def wheel_to_egg(dist, tmp):
    # Ignore `tmp`. It could be the download cache and using it for anything
    # other than creating tempdirs as subdirectories risks collisions
    # between buildout runs using a shared download cache.
    return WheelDir(dist.location).get_temp_dist()


def load(buildout):
    setuptools.package_index.distros_for_location = distros_for_location
    zc.buildout.easy_install.Installer = Installer
    zc.buildout.easy_install.wheel_to_egg = wheel_to_egg
