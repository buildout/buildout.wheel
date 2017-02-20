import os
import os.path
import shutil
import sys
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

class SelfDestructingEgg(pkg_resources.Distribution):
    """Since the location for creating the egg is inside the download directory
    We must self destruct to avoid having both the wheel and the generated egg
    there at the same time."""
    def __del__(self):
        shutil.rmtree(self.location)

class WheelFile(wheel.install.WheelFile):

    def __init__(self, *args, **kwargs):
        # use pip's notion of supported tags, not wheel's:
        kwargs.setdefault('context', pip.pep425tags.get_supported)
        super(WheelFile, self).__init__(*args, **kwargs)

    def lay_egg_into(self, target):
        join = os.path.join
        # drop everything inside the metadata directory, keyed by section name,
        # except the code itself
        location = join(target, self.egg_name)
        overrides = {
            key: (location if key in ('platlib', 'purelib')
                    else join(location, self.distinfo_name, key))
            for key in distutils.command.install.SCHEME_KEYS
        }
        self.install(overrides=overrides)
        # pkg_resources special-cases directories in sys.path with `.egg`
        # extension and expect their metadata directory to be called EGG-INFO
        # instead of the `[name]-[version].dist-info` directory of wheels.
        egg_info_location = join(location, 'EGG-INFO')
        os.rename(join(location, self.distinfo_name), egg_info_location)
        # See docstring of SelfDestructingEgg above for why it's needed:
        metadata = pkg_resources.PathMetadata(location, egg_info_location)
        egg = self.distribution(location, metadata=metadata,
                                class_=SelfDestructingEgg)
        # Fix namespaces with missing __init__
        if (sys.version_info < (3, 3) and
                egg.has_metadata('namespace_packages.txt')):
            for namespace in egg.get_metadata_lines('namespace_packages.txt'):
                __init__filename = namespace.split('.') + ['__init__.py']
                dest = join(location, *__init__filename)
                if not os.path.exists(dest):
                    shutil.copyfile(NAMESPACE_STUB_PATH, dest)
        return egg

    @wheel.decorator.reify
    def egg_name(self):
        return self.distribution().egg_name() + '.egg'

    @wheel.decorator.reify
    def is_platform_specific(self):
        return (self.parsed_filename.group('abi') != 'none' or
                self.parsed_filename.group('plat') != 'any')

    @wheel.decorator.reify
    def egg_platform(self):
        if self.compatible and self.is_platform_specific:
            # pretend we're a perfect match to avoid issues
            # TODO: is this really necessary for buildout? Will buildout ignore
            # manylinux1_x86_64 eggs in it's own eggs directory?
            return pkg_resources.get_build_platform()
        else:
            plat = self.parsed_filename.group('plat')
            return plat if plat != 'any' else None

    def distribution(self, location=None, metadata=None,
                     class_=pkg_resources.Distribution):
        parsed = self.parsed_filename.groupdict()
        return class_(
            location=location if location is not None else self.filename,
            metadata=metadata,
            project_name=parsed['name'],
            version=parsed['ver'],
            platform=self.egg_platform,
        )

def distros_for_location(location, basename, metadata=None):
    """Yield egg or source distribution objects based on basename

    Here we override to give wheels a chance"""
    if basename.endswith('.whl'):
        try:
            wf = WheelFile(basename)
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
    wf = WheelFile(dist.location)
    return wf.lay_egg_into(tmp)

def load(buildout):
    setuptools.package_index.distros_for_location = distros_for_location
    zc.buildout.easy_install.wheel_to_egg = wheel_to_egg
