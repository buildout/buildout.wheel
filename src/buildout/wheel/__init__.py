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
    `Environment` would auto-detect.
    """

    def __init__(self, *args, **kwargs):
        orig_Installer.__init__(self, *args, **kwargs)
        # Sorry to throw away all the previous hard work creating self._env
        # but we need to replace it with our special Environment.
        self._env = Environment(self._path, dest=self._dest)


class WheelDir(wheel.install.WheelFile):
    """
    WheelFile that can:

     * return a DistInfoDistribution that buildout can install

     * install itself into a directory and return the respective
       `DistInfoDistribution`.
    """

    _dist_extension = '.dist'

    def __init__(self, *args, **kwargs):
        # use pip's notion of supported tags, not wheel's:
        kwargs.setdefault('context', pip.pep425tags.get_supported)
        super(WheelDir, self).__init__(*args, **kwargs)

    def install_into(self, target):
        p = os.path
        distname = (p.splitext(p.basename(self.filename))[0] +
                    self._dist_extension)
        location = p.join(target, distname)
        # drop everything inside the metadata directory, keyed by section name,
        # except the code itself:
        overrides = {
            key: (location if key in ('platlib', 'purelib')
                  else p.join(location, self.distinfo_name, key))
            for key in distutils.command.install.SCHEME_KEYS
        }
        self.install(overrides=overrides)

        metadata = pkg_resources.PathMetadata(
            location, p.join(location, self.distinfo_name)
        )
        # Fix namespaces missing __init__ for Python 2 since we're not feeding
        # the wheel dirs to `site.addsitedir()` and so will ignore .pth files
        # in the wheel dirs.
        if (sys.version_info < (3, 3) and
                metadata.has_metadata('namespace_packages.txt')):
            self._plant_namespace_declarations(location, metadata)
        return self.distribution(location, metadata=metadata)

    def _plant_namespace_declarations(self, root, metadata):
        base = [root]
        init = ['__init__.py']
        for namespace in metadata.get_metadata_lines('namespace_packages.txt'):
            __init__filename = base + namespace.split('.') + init
            dest = os.path.join(*__init__filename)
            if not os.path.exists(dest):
                shutil.copyfile(NAMESPACE_STUB_PATH, dest)

    @wheel.decorator.reify
    def distribution_info(self):
        info = self.parsed_filename.groupdict()
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

    def distribution(self, location=None, metadata=None):
        info = self.distribution_info
        return pkg_resources.DistInfoDistribution(
            location=location if location is not None else self.filename,
            metadata=metadata,
            project_name=info['name'],
            version=info['ver'],
            platform=info['plat'],
            # trick buildout into believing this dist is an egg with anoter
            # extension so it copies the dist into `eggs-directory`:
            precedence=pkg_resources.EGG_DIST,
        )


def distros_for_location(location, basename, metadata=None):
    """
    Yield egg or source distribution objects based on basename.

    Here we override to give wheels a chance.
    """
    if basename.endswith('.whl'):
        try:
            wf = WheelDir(basename)
        except wheel.install.BadWheelFile:
            pass
        else:
            if wf.compatible:
                # It's a match. Treat it as an egg-like
                # distro. Buildout will sort it out.
                return [wf.distribution(location, metadata)]
        # Not a match, short circuit:
        return ()
    return orig_distros_for_location(location, basename, metadata=metadata)


_temp_dirs = []


def wheel_to_egg(dist, tmp):
    # Ignore `tmp`. It could be the download cache and using it for anything
    # other than creating tempdirs as subdirectories risks collisions
    # between buildout runs using a shared download cache.
    # See https://github.com/buildout/buildout/issues/345
    # Instead, create the egg-like dist in a tempdir and set it to be cleaned
    # up when the dist goes out of scope.
    target = tempfile.mkdtemp()
    _temp_dirs.append(target)
    dist = WheelDir(dist.location).install_into(target)

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
    if _temp_dirs:
        logger.debug('Cleaning up temporary directories...')
        for temp_dir in _temp_dirs:
            shutil.rmtree(temp_dir)
        del _temp_dirs[:]
        logger.debug('Done.')
