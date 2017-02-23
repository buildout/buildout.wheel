import glob
import logging
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


logger = logging.getLogger(__name__)

NAMESPACE_STUB_PATH = os.path.join(os.path.dirname(__file__),
                                   'namespace_stub.py')
assert os.path.isfile(NAMESPACE_STUB_PATH)


orig_distros_for_location = setuptools.package_index.distros_for_location
original_wheel_to_egg = zc.buildout.easy_install.wheel_to_egg
orig_Installer = zc.buildout.easy_install.Installer


def _get_dest_dist_paths(dest):
    p = os.path
    eggs = glob.glob(p.join(dest, '*.egg'))
    dists = [p.dirname(dist_info) for dist_info in
             glob.glob(p.join(dest, '*', '*.dist-info'))]
    # sort them like pkg_resources.find_on_path() would
    return pkg_resources._by_version_descending(set(eggs + dists))


class Environment(pkg_resources.Environment):
    """
    An pkg_resources.Environment specialiation that knows how to scan all
    dists under `eggs-directory`, regardless of whether they're actual eggs.
    """

    def __init__(self, search_path, dest):
        self.__dest = pkg_resources.normalize_path(dest)
        pkg_resources.Environment.__init__(self, search_path)

    def scan(self, search_path=None):
        # replace `self.__dest` (the `eggs-directory`) inside `search_path`
        # with all distributions (egg or otherwise) located in `self.__dest`
        # since `pkg_resources.Environment` can detect eggs in `self.__dest`,
        # but not other kinds of dists:
        if (search_path and
                pkg_resources.normalize_path(search_path[0]) == self.__dest):
            search_path[0:1] = _get_dest_dist_paths(self.__dest)
        return pkg_resources.Environment.scan(self, search_path)

    def add(self, dist):
        # pkg_resources.find_on_path(), used by self.scan() via
        # find_distributions(), creates all non-.egg dists as
        # precedence=DEVELOP_DIST.
        # Fix precedence to EGG_DIST of all packages under `self.__dest`
        if dist.location.startswith(self.__dest + '/'):
            dist.precedence = pkg_resources.EGG_DIST
        return pkg_resources.Environment.add(self, dist)


class Installer(orig_Installer):
    """
    zc.buildout.easy_install.Installer class that feeds all dists in
    `eggs-directory` to `pkg_resources.Environment`, not just the eggs that
    `Environment` would auto-detect, and knows how to install `wheels`.
    """

    def __init__(self, *args, **kwargs):
        orig_Installer.__init__(self, *args, **kwargs)
        # Sorry to throw away all the previous hard work creating self._env
        # but we need to replace it with our special Environment.
        self._env = Environment(self._path, dest=self._dest)

    def _call_easy_install(self, spec, ws, dest, dist):
        if not spec.endswith('.whl'):
            return orig_Installer._call_easy_install(spec, ws, dest, dist)
        tmp = tempfile.mkdtemp(dir=dest)
        try:
            # this causes the dist tree to be written twice in tempdirs inside
            # `dest`, but the alternative would be to trick
            # `setuptools.archive_util.unpack_archive` into unpacking wheels
            # which requirs dealing with
            # `setuptools.archive_util.unpack_archive.default_filter`.
            dist = WheelInstaller(spec).install_into(tmp)
            move = zc.buildout.easy_install._move_to_eggs_dir_and_compile
            newloc = move(dist, dest)
            return pkg_resources.Environment([newloc])[dist.project_name]
        finally:
            shutil.rmtree(tmp)


class WheelInstaller(object):
    """
    A WheelFile adapter that can:

     * return a DistInfoDistribution that buildout can install

     * install the wheel into a directory and return the respective
       `DistInfoDistribution`.
    """

    _dist_extension = '.dist'

    def __init__(self, location):
        # use pip's notion of supported tags, not wheel's:
        context = pip.pep425tags.get_supported
        try:
            self.wheel = wheel.install.WheelFile(location, context=context)
        except wheel.install.BadWheelFile:
            self.wheel = False

    @property
    def compatible(self):
        return self.wheel and self.wheel.compatible

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

        metadata = pkg_resources.PathMetadata(
            location, os.path.join(location, self.wheel.distinfo_name)
        )
        # Fix namespaces missing __init__ for Python 2 since we're not feeding
        # the wheel dirs to `site.addsitedir()` and so Python will ignore .pth
        # files in the wheel dirs.
        if (sys.version_info < (3, 3) and
                metadata.has_metadata('namespace_packages.txt')):
            self._plant_namespace_declarations(location, metadata)
        # The installed distribution is egg-like to please buildout
        return self.distribution(location, metadata=metadata,
                                 precedence=pkg_resources.EGG_DIST)

    @staticmethod
    def _plant_namespace_declarations(root, metadata):
        base = [root]
        init = ['__init__.py']
        for namespace in metadata.get_metadata_lines('namespace_packages.txt'):
            __init__filename = os.path.join(*(
                base + namespace.split('.') + init
            ))
            if not os.path.exists(__init__filename):
                shutil.copyfile(NAMESPACE_STUB_PATH, __init__filename)

    @wheel.decorator.reify
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

    def distribution(self, location, metadata=None,
                     precedence=pkg_resources.BINARY_DIST):
        info = self.distribution_info
        return pkg_resources.DistInfoDistribution(
            location=location,
            metadata=metadata,
            project_name=info['name'],
            version=info['ver'],
            platform=info['plat'],
            # trick buildout into believing this dist is an egg with anoter
            # extension so it copies the dist into `eggs-directory`:
            precedence=precedence,
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
