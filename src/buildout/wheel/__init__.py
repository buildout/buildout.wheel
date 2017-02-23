import logging
import os
import os.path
import shutil
import sys
import pkg_resources
import setuptools.package_index
import wheel.install
import pip.pep425tags
import zc.buildout.easy_install
import distutils.command.install


logger = logging.getLogger(__name__)

NAMESPACE_STUB_PATH = os.path.join(os.path.dirname(__file__),
                                   'namespace_stub.py')
assert os.path.isfile(NAMESPACE_STUB_PATH)


orig_distros_for_location = setuptools.package_index.distros_for_location
original_wheel_to_egg = zc.buildout.easy_install.wheel_to_egg
orig_Installer = zc.buildout.easy_install.Installer


class Installer(orig_Installer):
    """
    zc.buildout.easy_install.Installer class that knows how to install `wheels`
    """

    def _call_easy_install(self, spec, dest):
        if not spec.endswith('.whl'):
            orig_Installer._call_easy_install(spec, dest)
        location = WheelInstaller(spec).install_into(dest)
        return [location]


class WheelInstaller(object):
    """
    A WheelFile adapter that can:

     * return a DistInfoDistribution that buildout can install

     * install the wheel into a directory to be added to `sys.path`
    """

    _dist_extension = '.dist'
    wheel = None

    def __init__(self, location):
        # use pip's notion of supported tags, not wheel's:
        context = pip.pep425tags.get_supported
        try:
            self.wheel = wheel.install.WheelFile(location, context=context)
        except wheel.install.BadWheelFile:
            pass

    @property
    def compatible(self):
        return self.wheel is not None and self.wheel.compatible

    def install_into(self, target):
        """
        Installs a wheel as a self contained distribution into target
        """
        basename = os.path.splitext(os.path.basename(self.wheel.filename))[0]
        distname = basename + self._dist_extension
        location = os.path.join(target, distname)
        distinfo_location = os.path.join(location, self.wheel.distinfo_name)
        # drop everything inside the .dist-info directory, keyed by section
        # name, except the code itself:
        overrides = {
            key: (location if key in ('platlib', 'purelib')
                  else os.path.join(distinfo_location, key))
            for key in distutils.command.install.SCHEME_KEYS
        }
        self.wheel.install(overrides=overrides)
        # Fix namespaces missing __init__ for Python 2 since we're not feeding
        # the wheel dirs to `site.addsitedir()` and so Python will ignore .pth
        # files in the wheel dirs.
        metadata = pkg_resources.PathMetadata(
            location, os.path.join(location, self.wheel.distinfo_name)
        )
        dist = self.distribution(location, metadata=metadata)
        if (sys.version_info < (3, 3) and
                metadata.has_metadata('namespace_packages.txt')):
            self._plant_namespace_declarations(dist)
        return dist

    @staticmethod
    def _plant_namespace_declarations(dist):
        paths = zc.buildout.easy_install.get_namespace_package_paths(dist)
        for __init__filename in paths:
            if not os.path.exists(__init__filename):
                shutil.copyfile(NAMESPACE_STUB_PATH, __init__filename)

    def distribution_info(self):
        """
        Parsed info from the wheel name, with a setuptools compatible platform
        """
        info = self.wheel.parsed_filename.groupdict()
        if info['plat'] == 'any' and info['abi'] == 'none':
            # Pure Python
            info['plat'] = None
        elif self.compatible:
            # compatible but abi/platform-specific wheel. Pretend we're a
            # perfect platform match to avoid pkg_resources ignoring the dist
            # since it doesn't understand, e.g. manylinux1.
            info['plat'] = pkg_resources.get_build_platform()
        else:
            # force pkg_resources to ignore this wheel
            # I just hope someone doesn't invent an arch called `incompatible`
            # just to troll us.
            info['plat'] = 'incompatible'
        return info

    def distribution(self, location, metadata=None):
        """ Get DistInfoDistribution for wheel """
        info = self.distribution_info()
        return pkg_resources.DistInfoDistribution(
            location=location,
            metadata=metadata,
            project_name=info['name'],
            version=info['ver'],
            platform=info['plat'],
            # trick buildout into believing this dist is a BINARY_DIS
            # so it invokes our `_call_easy_install` override:
            precedence=pkg_resources.BINARY_DIST,
        )


def distros_for_location(location, basename, metadata=None):
    """
    Yield egg or source distribution objects based on basename.

    Here we override setuptools to give wheels a chance.
    """
    if basename.endswith('.whl'):
        wi = WheelInstaller(basename)
        if wi.compatible:
            # It's a match. Treat it as a binary
            # distro. Buildout will sort it out.
            return [wi.distribution(location, metadata)]
        # Not a match, short circuit:
        return ()
    return orig_distros_for_location(location, basename, metadata=metadata)


def wheel_to_egg(dist, tmp):
    # NOOP, just to make buildout stop complaining.
    # Installer._call_easy_install() above will handle it.
    return dist


def load(buildout):
    setuptools.package_index.distros_for_location = distros_for_location
    zc.buildout.easy_install.Installer = Installer
    zc.buildout.easy_install.wheel_to_egg = wheel_to_egg
    logger.debug('Patched in wheel support')


def unload(buildout):
    zc.buildout.easy_install.wheel_to_egg = original_wheel_to_egg
    zc.buildout.easy_install.Installer = orig_Installer
    setuptools.package_index.distros_for_location = orig_distros_for_location
